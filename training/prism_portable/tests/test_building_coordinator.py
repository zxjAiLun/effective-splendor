"""Synthetic transaction integration; no Arena games or competitive claims."""
import copy

import pytest

from training.prism_portable.engine.export import export_weights
from training.prism_portable.engine.io import sha256_file, tensor_identity
from training.prism_portable.engine.model import PrismModel
from training.prism_portable.engine.ppo.building import (
    BASE_CATALOG_FINGERPRINT, default_building_config,
)
from training.prism_portable.engine.ppo.coordinator import Run
from training.prism_portable.tests.test_building_style import projected
from training.prism.tests.ppo_support import game, run_config, schedule


@pytest.mark.parametrize("enabled", [False, True])
def test_building_targets_metrics_and_optimizer_survive_reopen(tmp_path, enabled):
    weights = tmp_path / "weights.json"
    export_weights(PrismModel(), weights, BASE_CATALOG_FINGERPRINT)
    cfg = run_config(sha256_file(weights))
    cfg.update(format="prism-ppo-run-v3", arena_contract_sha256="0" * 64,
               catalog_fingerprint=BASE_CATALOG_FINGERPRINT, style=default_building_config())
    cfg["ppo"].update(style_beta=0.3 if enabled else 0.0,
                      style_value_weight=0.5 if enabled else 0.0)
    run = Run.create(tmp_path / "run", cfg, weights)
    snapshot = run.begin_cycle(schedule())
    behavior = run._behavior_cache[snapshot["snapshot_sha256"]]
    shard = game(behavior, count=2, actions=1)
    visible = projected([0, 42])
    for row, projection in zip(shard["decisions"], visible["decisions"]):
        row.update(observation=copy.deepcopy(projection["observation"]),
                   visible_history=copy.deepcopy(projection.get("visible_history", [])),
                   legal_actions=[copy.deepcopy(projection["chosen_action"])],
                   chosen_action=copy.deepcopy(projection["chosen_action"]))
    with run._transaction():
        run.state["jobs"][shard["job_id"]] = {
            "status": "COMPLETE", "attempt": 1, "artifact": run.store.put_json(shard),
        }
        run.state["decisions"] = 2
        run._commit()
    run.seal()
    batch = run.store.get_json(run.state["batch"])
    if enabled:
        assert all(row["style_return"] == pytest.approx(1 / 24) for row in batch["rows"])
        extracted = [row for row in run.state["metrics"] if row["event"] == "style_extracted"]
        assert len(extracted) == 1
        assert extracted[0]["mean_building_utility"] == pytest.approx(1 / 24)
        assert extracted[0]["mean_early_bonus_auc12"] > 0
        assert "mean_rush_auc" not in extracted[0]
        assert "vp_threshold_by_horizon_rate" not in extracted[0]
    else:
        assert not any(row["event"] == "style_extracted" for row in run.state["metrics"])
    resumed = Run.open(tmp_path / "run")
    assert resumed.learner.model.style_enabled is enabled
    before = tensor_identity(resumed.learner.model.state_dict())
    metrics = resumed.step()
    assert metrics["optimizer_applied"]
    final = Run.open(tmp_path / "run")
    assert tensor_identity(final.learner.model.state_dict()) != before
    assert final.state["global_step"] == 1
    params = list(final.learner.optimizer.param_groups[0]["params"])
    assert len(params) == (36 if enabled else 32)
