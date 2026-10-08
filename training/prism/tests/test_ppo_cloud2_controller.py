"""Synthetic controller checks: no real agents, games, seeds or production DB."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

from scripts import prism_ppo_cloud2_controller as controller

POOL = Path(__file__).resolve().parents[3] / "apps" / "splendor-pool"
sys.path.insert(0, str(POOL))
from splendor_pool.config import Config
from splendor_pool.models import create_custom_spec
from splendor_pool.store import Store


class FakeEvaluator:
    BOOTSTRAP_SEED = 1
    _mean = staticmethod(lambda values: sum(values) / len(values))
    _bootstrap_ci = staticmethod(lambda values, seed: [min(values), max(values)])
    sha256_file = staticmethod(lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest())

    def __init__(self):
        self.started = []
        self.fail = False

    def validate_config(self, value, path):
        return value

    def check_assets(self, config):
        for spec in [config["engine"], *config["candidates"].values(), *config["opponents"].values()]:
            assert self.sha256_file(spec["program"]) == spec["sha256"]
            for asset in spec.get("files", []):
                assert self.sha256_file(asset["path"]) == asset["sha256"]

    def run_eval(self, path, output):
        result_path = output / "result.json"
        if result_path.exists():
            return controller.load(result_path)
        if self.fail:
            raise RuntimeError("synthetic invalid terminal")
        cfg = controller.load(path)
        label = next(iter(cfg["candidates"]))
        self.started.append(label)
        values = [0.25, 0.5] if label == "parent" else [0.5, 0.75]
        result = {"seeds": cfg["seeds"], "candidate_opponent": {label: {
            opponent: {"per_seed_score_rate": values} for opponent in cfg["opponents"]}}}
        controller.save(result_path, result)
        return result


@pytest.fixture
def setup(tmp_path):
    store = Store(Config.default(tmp_path / "pool"))
    store.initialize()
    for name in ("old-prism", "old-heuristic"):
        store.add_model(create_custom_spec(name, ["old-agent"], program="old-engine"))
    evaluator = FakeEvaluator()
    engine = tmp_path / "engine"
    engine.write_text("synthetic executable")
    weights = tmp_path / "weights.json"
    weights.write_text("synthetic weights")
    spec = {"program": str(engine), "sha256": evaluator.sha256_file(engine),
            "args": ["agent-prism-sample", "--weights", str(weights), "--seed", "1"],
            "files": [{"path": str(weights), "sha256": evaluator.sha256_file(weights)}]}
    ready = tmp_path / "c1.ready.json"
    controller.save(ready, {"path": str(weights), "sha256": evaluator.sha256_file(weights),
                            "cycle": 1, "training_commit": "a" * 64})
    plan = {"format": controller.FORMAT, "root": str(tmp_path / "round"),
            "engine": {"program": str(engine), "sha256": spec["sha256"]},
            "catalog_fingerprint": "b" * 64, "action_seed": 1, "seeds": [1, 2],
            "timeouts": {}, "parent": spec, "opponents": {"frozen": spec},
            "checkpoints": [{"label": "c1", "cycle": 1, "weights_ready": str(ready)}],
            "mixed_matches": 2, "wait_seconds": 100}
    return plan, store, evaluator


def complete_fake(store, target, error=False):
    old = store.get_model_by_name("old-prism").id
    with store.connection() as con:
        con.execute("INSERT INTO matches(seed,status,p0_id,p1_id,winner_id) VALUES(1,?,?,?,?)",
                    ("error" if error else "completed", target, old, target))


def tick_worker(store):
    def tick(seconds):
        assert not store.is_paused()
        enabled = [m for m in store.list_models() if m.enabled and
                   (m.name.startswith(controller.TRIAL_PREFIX) or m.name == "prism-v01-t1-m54")]
        target = next((m.id for m in enabled if m.name.startswith(controller.TRIAL_PREFIX)), enabled[0].id)
        complete_fake(store, target)
    return tick


def test_rounds_reuse_parent_and_preserve_old_models(setup):
    plan, store, evaluator = setup
    old = [(m.id, m.name, m.config, m.elo) for m in store.list_models()]
    run = controller.Controller(plan, store, evaluator, sleep=tick_worker(store))
    run.run()
    assert run.state["complete"] and store.is_paused()
    assert evaluator.started == ["parent", "c1"]
    assert controller.load(Path(plan["root"]) / "c1-paired-delta.json")["mean_delta_score_rate"] == 0.25
    for model_id, name, config, elo in old:
        assert store.get_model(model_id).config == config
        assert store.get_model(model_id).name == name
        assert store.get_model(model_id).enabled
    count = len(store.list_models())
    controller.Controller(plan, store, evaluator, sleep=tick_worker(store)).run()
    assert evaluator.started == ["parent", "c1"]
    assert len(store.list_models()) == count
    with store.connection() as con:
        assert con.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 4


def test_mixed_restart_reuses_original_start_id_and_deadline(setup):
    plan, store, evaluator = setup
    run = controller.Controller(plan, store, evaluator, clock=lambda: 10, sleep=tick_worker(store))
    target = run.enroll("prism-v01-t1-m54", plan["parent"])
    run.state["rounds"]["parent"] = {"mixed_start_id": 0, "elo_before": {str(target): 1500.0}}
    run.persist()
    complete_fake(store, target)
    resumed = controller.Controller(plan, store, evaluator, clock=lambda: 30, sleep=tick_worker(store))
    assert resumed.state["deadline"] == 110
    resumed.mixed("parent", target)
    assert resumed.state["rounds"]["parent"]["mixed_start_id"] == 0
    summary = controller.load(Path(plan["root"]) / "parent-mixed-summary.json")
    assert summary["interval"]["games"] == 2
    assert summary["total_new_pool_games"] == 2
    assert store.is_paused()


def test_failure_pauses_without_enrollment(setup):
    plan, store, evaluator = setup
    evaluator.fail = True
    run = controller.Controller(plan, store, evaluator)
    with pytest.raises(RuntimeError, match="synthetic invalid terminal"):
        run.run()
    assert store.is_paused() and len(store.list_models()) == 2
    assert not run.state["complete"]
    assert "synthetic invalid terminal" in run.state["error"]


def test_plan_and_enrollment_drift_rejected(setup):
    plan, store, evaluator = setup
    run = controller.Controller(plan, store, evaluator)
    altered = dict(plan, mixed_matches=3)
    with pytest.raises(ValueError, match="plan drift"):
        controller.Controller(altered, store, evaluator)
    run.enroll("prism-v01-t1-m54", plan["parent"])
    bad = dict(plan["parent"], args=["greedy-agent"])
    with pytest.raises(ValueError, match="immutable model config"):
        run.enroll("prism-v01-t1-m54", bad)


def test_checkpoint_hash_and_cycle_rejected(setup):
    plan, store, evaluator = setup
    run = controller.Controller(plan, store, evaluator)
    ready = Path(plan["checkpoints"][0]["weights_ready"])
    asset = controller.load(ready)
    controller.save(ready, dict(asset, cycle=4))
    with pytest.raises(ValueError, match="metadata mismatch"):
        run.descriptor(plan["checkpoints"][0])
    controller.save(ready, dict(asset, sha256="c" * 64))
    with pytest.raises(ValueError, match="weight drift"):
        run.descriptor(plan["checkpoints"][0])


def test_mixed_error_pauses_and_earlier_candidate_disabled(setup):
    plan, store, evaluator = setup
    run = controller.Controller(plan, store, evaluator)
    old = run.enroll(controller.TRIAL_PREFIX + "c1", plan["parent"])
    target = run.enroll(controller.TRIAL_PREFIX + "c4", plan["parent"])
    run.state["rounds"]["c4"] = {}
    run.sleep = lambda seconds: complete_fake(store, target, error=True)
    with pytest.raises(RuntimeError, match="match error"):
        run.mixed("c4", target)
    assert store.is_paused() and not store.get_model(old).enabled
    assert store.get_model(target).enabled
    assert store.get_model_by_name("old-prism").enabled


def test_paired_seed_order_rejected(setup):
    plan, store, evaluator = setup
    with pytest.raises(ValueError, match="seed order"):
        controller.paired_delta(evaluator, plan, {"seeds": [2, 1]}, {"seeds": [1, 2]}, "c1")
