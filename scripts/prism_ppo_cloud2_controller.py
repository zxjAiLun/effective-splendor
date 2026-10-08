"""Bounded M54 fixed-T1 and mixed-pool rounds; stdlib, no training stack.

The plan pins engine/assets, shared development seeds, parent, checkpoints,
wall deadline and total pool games per mixed round. Fixed matches never enter
SQLite/Elo. Existing model configs and Elo history are preserved. An already
started mixed interval resumes from its original match ID, not from restart.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

FORMAT = "m54-cloud2-controller-v1"
TRIAL_PREFIX = "prism-m54-trial-v1-"


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def import_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def paired_delta(evaluator, plan, parent, candidate, label):
    if parent["seeds"] != plan["seeds"] or candidate["seeds"] != plan["seeds"]:
        raise ValueError("paired result seed order mismatch")
    by_opponent = {}
    blocks = []
    for opponent in plan["opponents"]:
        a = candidate["candidate_opponent"][label][opponent]["per_seed_score_rate"]
        b = parent["candidate_opponent"]["parent"][opponent]["per_seed_score_rate"]
        if len(a) != len(plan["seeds"]) or len(b) != len(a):
            raise ValueError("paired seed block length mismatch")
        delta = [x - y for x, y in zip(a, b)]
        blocks.append(delta)
        by_opponent[opponent] = {
            "mean_delta_score_rate": evaluator._mean(delta),
            "ci95_by_seed": evaluator._bootstrap_ci(delta, evaluator.BOOTSTRAP_SEED),
        }
    joint = [evaluator._mean([block[i] for block in blocks])
             for i in range(len(plan["seeds"]))]
    return {"verdict": "DEVELOPMENT_ONLY_NOT_PROMOTED", "checkpoint": label,
            "seeds": plan["seeds"], "mean_delta_score_rate": evaluator._mean(joint),
            "ci95_by_seed": evaluator._bootstrap_ci(joint, evaluator.BOOTSTRAP_SEED),
            "by_opponent": by_opponent}


class Controller:
    def __init__(self, plan, store, evaluator, *, clock=time.time, sleep=time.sleep):
        if plan.get("format") != FORMAT:
            raise ValueError("controller plan format")
        if type(plan.get("mixed_matches")) is not int or not 1 <= plan["mixed_matches"] <= 4096:
            raise ValueError("bounded mixed_matches required")
        if type(plan.get("wait_seconds")) is not int or not 1 <= plan["wait_seconds"] <= 86400:
            raise ValueError("bounded wait_seconds required")
        labels = [row["label"] for row in plan["checkpoints"]]
        if len(set(labels)) != len(labels) or any(
                row["label"] != "c" + str(row["cycle"]) or row["cycle"] not in (1, 4, 8)
                for row in plan["checkpoints"]):
            raise ValueError("checkpoint labels/cycles")
        self.plan, self.store, self.evaluator = plan, store, evaluator
        self.clock, self.sleep = clock, sleep
        self.root = Path(plan["root"])
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_path = self.root / "controller-state.json"
        if self.state_path.exists():
            self.state = load(self.state_path)
            if self.state["plan_sha256"] != digest(plan):
                raise ValueError("immutable controller plan drift")
        else:
            self.state = {"format": FORMAT, "plan_sha256": digest(plan), "rounds": {},
                          "started_at": clock(), "deadline": clock() + plan["wait_seconds"],
                          "protected_models": {str(m.id): {
                              "name": m.name, "model_type": m.model_type, "config": m.config,
                              "weight": m.weight, "enabled": m.enabled,
                              "initial_elo": m.elo, "initial_games": m.games}
                              for m in store.list_models() if not m.name.startswith(TRIAL_PREFIX)}}
        self.state["pid"] = os.getpid()
        self.persist()

    def persist(self):
        save(self.state_path, self.state)

    def deadline_check(self, reason):
        if self.clock() >= self.state["deadline"]:
            raise TimeoutError(reason)

    def wait_idle(self):
        while True:
            with self.store.connection() as con:
                live = con.execute("SELECT COUNT(*) FROM matches WHERE status IN ('pending','running')").fetchone()[0]
            if not live:
                return
            self.deadline_check("pool did not become idle")
            self.sleep(0.25)

    def check_protected(self):
        for key, old in self.state["protected_models"].items():
            model = self.store.get_model(int(key))
            if not model or any(getattr(model, field) != old[field]
                                for field in ("name", "model_type", "weight", "enabled")) or model.config != old["config"]:
                raise ValueError("pre-existing model configuration drift: " + key)

    def descriptor(self, checkpoint):
        if checkpoint is None:
            return self.plan["parent"], None
        ready = Path(checkpoint["weights_ready"])
        while not ready.is_file():
            self.deadline_check("training checkpoint not published: " + checkpoint["label"])
            self.sleep(10)
        asset = load(ready)
        if set(asset) != {"path", "sha256", "cycle", "training_commit"} or asset["cycle"] != checkpoint["cycle"]:
            raise ValueError("checkpoint ready metadata mismatch")
        if not isinstance(asset["training_commit"], str) or len(asset["training_commit"]) != 64:
            raise ValueError("training commit identity")
        if self.evaluator.sha256_file(asset["path"]) != asset["sha256"]:
            raise ValueError("checkpoint weight drift")
        engine = self.plan["engine"]
        return {"program": engine["program"], "sha256": engine["sha256"],
                "args": ["agent-prism-sample", "--weights", asset["path"], "--seed", str(self.plan["action_seed"])],
                "files": [{"path": asset["path"], "sha256": asset["sha256"]}]}, asset

    def enroll(self, name, descriptor):
        from splendor_pool.models import create_custom_spec
        expected = create_custom_spec(name, descriptor["args"], program=descriptor["program"], weight=1.0)
        old = self.store.get_model_by_name(name)
        if old:
            if old.model_type != "custom" or old.config != expected.config or old.weight != expected.weight:
                raise ValueError("existing immutable model config mismatch: " + name)
            return old.id
        return self.store.add_model(expected)

    def mixed(self, label, model_id):
        row = self.state["rounds"][label]
        if row.get("mixed_complete"):
            return
        self.check_protected()
        for model in self.store.list_models():
            if model.name.startswith(TRIAL_PREFIX) and model.id != model_id:
                self.store.update_model(model.id, enabled=False)
        self.store.update_model(model_id, enabled=True)
        if "mixed_start_id" not in row:
            with self.store.connection() as con:
                row["mixed_start_id"] = con.execute("SELECT COALESCE(MAX(id),0) FROM matches").fetchone()[0]
            row["elo_before"] = {str(m.id): m.elo for m in self.store.list_models()}
            self.persist()
        start = row["mixed_start_id"]
        self.deadline_check("bounded mixed round deadline")
        self.store.pause(False)
        try:
            while True:
                with self.store.connection() as con:
                    count = con.execute("SELECT COUNT(*) FROM matches WHERE id>? AND status='completed'", (start,)).fetchone()[0]
                    failures = con.execute("SELECT COUNT(*) FROM matches WHERE id>? AND status='error'", (start,)).fetchone()[0]
                if failures:
                    raise RuntimeError("new mixed pool match error; paused for inspection")
                if count >= self.plan["mixed_matches"]:
                    break
                self.deadline_check("bounded mixed round deadline")
                self.sleep(0.25)
        finally:
            self.store.pause(True)
        self.wait_idle()
        with self.store.connection() as con:
            records = [dict(r) for r in con.execute("SELECT * FROM matches WHERE id>? AND status='completed' ORDER BY id", (start,))]
        own = [r for r in records if model_id in (r["p0_id"], r["p1_id"])]
        wins = sum(r["winner_id"] == model_id for r in own)
        draws = sum(r["winner_id"] is None for r in own)
        model = self.store.get_model(model_id)
        snapshot = {"id": model.id, "name": model.name, "elo": model.elo,
                    "games": model.games, "wins": model.wins, "draws": model.ties, "losses": model.losses}
        summary = {"verdict": "MIXED_POOL_DIAGNOSTIC_NOT_FIXED_BENCHMARK", "round": label,
                   "start_id": start, "end_id": max(r["id"] for r in records),
                   "target_total_pool_games": self.plan["mixed_matches"], "total_new_pool_games": len(records),
                   "sampled_model": snapshot, "interval": {"games": len(own), "wins": wins, "draws": draws,
                   "losses": len(own) - wins - draws, "score_rate": (wins + draws / 2) / len(own) if own else None},
                   "elo_before": row["elo_before"], "elo_after": {str(m.id): m.elo for m in self.store.list_models()},
                   "stop_contract": "pause at threshold; single in-flight match may finish", "records": records}
        save(self.root / (label + "-mixed-summary.json"), summary)
        row.update(mixed_complete=True, mixed_completed_games=len(records), mixed_end_id=summary["end_id"],
                   model_snapshot=snapshot)
        self.persist()
        print(json.dumps({"event": "mixed_complete", "label": label, "interval": summary["interval"], "model": snapshot}), flush=True)

    def run(self):
        parent_result = None
        try:
            self.store.pause(True)
            self.wait_idle()
            self.check_protected()
            for label, checkpoint in [("parent", None)] + [(r["label"], r) for r in self.plan["checkpoints"]]:
                self.state.update(waiting_for=label, error=None)
                self.persist()
                descriptor, asset = self.descriptor(checkpoint)
                self.store.pause(True)
                self.wait_idle()
                config = {k: self.plan[k] for k in ("engine", "catalog_fingerprint", "action_seed", "seeds", "timeouts", "opponents")}
                config.update(format="prism-ppo-fixed-eval-v1", candidates={label: descriptor})
                path = self.root / (label + "-fixed.config.json")
                if path.exists() and load(path) != config:
                    raise ValueError("controller fixed config drift")
                save(path, config)
                self.evaluator.check_assets(self.evaluator.validate_config(config, path))
                result = self.evaluator.run_eval(path, self.root / (label + "-fixed"))
                row = self.state["rounds"].setdefault(label, {})
                if asset is not None:
                    if "checkpoint" in row and row["checkpoint"] != asset:
                        raise ValueError("immutable checkpoint ready drift")
                    row["checkpoint"] = asset
                row.update(fixed_complete=True, fixed_result=str(self.root / (label + "-fixed") / "result.json"))
                self.persist()
                if label == "parent":
                    parent_result = result
                else:
                    delta = paired_delta(self.evaluator, self.plan, parent_result, result, label)
                    delta["reused_parent_result"] = str(self.root / "parent-fixed" / "result.json")
                    save(self.root / (label + "-paired-delta.json"), delta)
                name = "prism-v01-t1-m54" if checkpoint is None else TRIAL_PREFIX + label
                model_id = self.enroll(name, descriptor)
                row["pool_model_id"] = model_id
                self.persist()
                self.mixed(label, model_id)
            self.state.update(complete=True, waiting_for=None, finished_at=self.clock())
            self.persist()
        except BaseException as exc:
            self.state.update(error=type(exc).__name__ + ": " + str(exc), complete=False)
            self.persist()
            raise
        finally:
            self.store.pause(True)


@contextmanager
def controller_lock(root):
    import fcntl
    Path(root).mkdir(parents=True, exist_ok=True)
    with (Path(root) / "controller.lock").open("a+") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    args = parser.parse_args()
    plan = load(args.plan)
    sys.path.insert(0, plan["pool_root"])
    from splendor_pool.config import Config
    from splendor_pool.store import Store
    store = Store(Config.load(Path(plan["pool_root"]) / "config.toml"))
    evaluator = import_file("m54_fixed_eval", plan["eval_script"])
    with controller_lock(plan["root"]):
        Controller(plan, store, evaluator).run()


if __name__ == "__main__":
    main()
