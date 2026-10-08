"""Opt-in M54 interop tests. Only existing replays and synthetic states; no games."""
import json
import os
from pathlib import Path
import subprocess
import threading

import pytest
import torch

from training.prism.data import collate_states
from training.prism.io import parse_json, read_json, sha256_file, write_json
from training.prism.ppo.audit import audit_game
from training.prism.ppo.contract import validate_audit, validate_row
from training.prism.ppo.learner import Learner, prepare_batch
from training.prism.ppo.model import new_model
from training.prism.ppo.runtime import configure
from training.prism.ppo.sampling import Behavior
from training.prism.ppo.service import BehaviorServer
from training.prism.tests.ppo_support import config, game


@pytest.fixture
def interop():
    required = ("M54_RUST_TEST_EXE", "M54_CLI_EXE", "M54_EXISTING_REPLAY", "M54_BOUNDARY_FIXTURES", "M54_EXISTING_WEIGHTS")
    if any(name not in os.environ for name in required):
        pytest.skip("opt-in requires isolated binaries and existing fixtures")
    paths = {name: Path(os.environ[name]) for name in required}
    assert all(path.is_file() for path in paths.values())
    return paths


def run_rust(paths, name, env):
    result = subprocess.run([str(paths["M54_RUST_TEST_EXE"]), "--exact",
                             "prism_ppo_command::integration_tests::" + name, "--ignored", "--nocapture"],
                            capture_output=True, text=True, env=env, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_rust_agent_python_service_real_wire(tmp_path, interop):
    runtime = configure("cpu", 2)
    catalog = read_json(interop["M54_EXISTING_WEIGHTS"])["catalog_fingerprint"]
    behavior = Behavior(new_model(style_enabled=True), catalog_fingerprint=catalog, action_seed=23, runtime=runtime)
    sidecar = tmp_path / "decisions.jsonl"
    with BehaviorServer(("127.0.0.1", 0), behavior, "m54-engineering-token") as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        env = os.environ | {"M54_TEST_ENDPOINT": f"127.0.0.1:{server.server_address[1]}",
                            "M54_TEST_BEHAVIOR": behavior.identity, "M54_TEST_SIDECAR": str(sidecar)}
        try:
            stdout = run_rust(interop, "python_service_synthetic_decisions", env)
        finally:
            server.shutdown(); thread.join(10)
    assert not thread.is_alive()
    rows = [parse_json(line) for line in sidecar.read_text().splitlines()]
    assert len(rows) == 2
    assert [row["request"]["decision_index"] for row in rows] == [0, 1]
    assert rows[0]["observation"]["public"]["phase"] == "main"
    assert rows[1]["observation"]["public"]["phase"] == "choose_noble"
    for row in rows:
        validate_row(row)
        behavior.verify(row, logp_tolerance=1e-6, value_tolerance=1e-6)
    assert "m54-engineering-token" not in sidecar.read_text()
    write_json(tmp_path / "wire-evidence.json", {"rows": 2, "behavior_id": behavior.identity, "rust_output": stdout})


def test_existing_replay_auditor_success_and_tampering(tmp_path, interop):
    source = interop["M54_EXISTING_REPLAY"]
    source_hash = sha256_file(source)
    directory = tmp_path / "audit"
    env = os.environ | {"M54_TEST_REPLAY": str(source), "M54_TEST_AUDIT_DIR": str(directory)}
    run_rust(interop, "existing_replay_audit_and_tamper_rejection", env)
    for actor in range(2):
        result = read_json(directory / f"actor{actor}-audit.json")
        validate_audit(result, behavior_id="a" * 64, catalog_fingerprint=result["catalog_fingerprint"], max_decisions=1000)
        # Rust test mutated its input to exercise rejection. Reconstruct only the
        # ALREADY-AUDITED rows, then exercise the Python pinned-binary wrapper.
        sidecar = tmp_path / f"restored-actor{actor}.jsonl"
        sidecar.write_text("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in result["decisions"]), encoding="utf-8")
        reread = audit_game(interop["M54_CLI_EXE"], sha256_file(interop["M54_CLI_EXE"]), source,
                            sidecar, tmp_path / f"wrapper{actor}.json", behavior_id="a" * 64,
                            job_id="existing-replay-fixture", actor=actor)
        assert reread["result"] == result["result"]
        assert len(reread["decisions"]) == len(result["decisions"])
    assert sha256_file(source) == source_hash


def test_updated_ppo_export_python_rust_parity(tmp_path, interop):
    runtime = configure("cpu", 2)
    catalog = read_json(interop["M54_EXISTING_WEIGHTS"])["catalog_fingerprint"]
    model = new_model(style_enabled=True)
    behavior = Behavior(model, catalog_fingerprint=catalog, action_seed=11, runtime=runtime)
    cfg = config(style_beta=0.2, style_value_weight=0.5)
    batch = prepare_batch([game(behavior)], behavior, cfg, max_decisions=10,
                          style_returns={("synthetic-job", 0): 0.8})
    Learner(model, cfg).step(batch, [0, 1])  # synthetic optimizer test, not training a candidate
    weights = tmp_path / "weights.json"
    model.export(weights, catalog, provenance={"scope": "synthetic PPO export parity only"})
    raw = [parse_json(line) for line in interop["M54_BOUNDARY_FIXTURES"].read_text(encoding="utf-8").splitlines()]
    states = [row.get("input", row) for row in raw]
    inputs = tmp_path / "inputs.jsonl"
    inputs.write_text("".join(json.dumps(state) + "\n" for state in states), encoding="utf-8")
    output = tmp_path / "rust.jsonl"
    result = subprocess.run([str(interop["M54_CLI_EXE"]), "prism-predict", "--weights", str(weights),
                             "--input", str(inputs), "--output", str(output)], capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr
    predictions = [parse_json(line) for line in output.read_text().splitlines()]
    assert len(predictions) == len(states) > 0
    worst = 0.0
    with torch.inference_mode():
        for state, pred in zip(states, predictions):
            logits, value, _ = model.forward_batch(collate_states([state]))
            rust = torch.tensor(pred["logits"], dtype=torch.float32)
            torch.testing.assert_close(logits[0], rust, atol=1e-4, rtol=1e-4)
            assert value.sigmoid().item() == pytest.approx(pred["value"], abs=1e-4, rel=1e-4)
            worst = max(worst, (logits[0] - rust).abs().max().item())
    write_json(tmp_path / "parity-evidence.json", {"states": len(states), "max_abs_logit_difference": worst,
                                                 "atol": 1e-4, "rtol": 1e-4, "weights_sha256": sha256_file(weights)})
