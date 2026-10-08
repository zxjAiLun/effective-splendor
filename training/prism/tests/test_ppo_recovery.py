import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import torch

from training.prism.export import export_weights
from training.prism.io import read_json, sha256_file, tensor_identity, write_json
from training.prism.model import PrismModel
from training.prism.ppo.coordinator import Run, validate_config
from training.prism.ppo.sampling import Behavior
from training.prism.ppo.store import CommitStore
from training.prism.tests.ppo_support import CATALOG, game, run_config, schedule


@pytest.mark.parametrize("event", ["payload_written", "commit_written", "head_published"])
def test_process_crash_commit_boundary_and_lock_release(tmp_path, event):
    identity = "a" * 64
    store = CommitStore(tmp_path / "store", identity)
    with store.lock():
        old = store.commit({"step": 0}, expected_parent=None)
    script = '''
import os,sys
from training.prism.ppo.store import CommitStore
s=CommitStore(sys.argv[1], 'a'*64)
with s.lock():
    s.commit({'step':1}, expected_parent=s.head(), fault=lambda e: os._exit(37) if e==sys.argv[2] else None)
'''
    result = subprocess.run([sys.executable, "-B", "-c", script, str(store.root), event], timeout=30)
    assert result.returncode == 37
    with store.lock():
        head, state = store.load()
        assert state["step"] == (1 if event == "head_published" else 0)
        assert (head == old) == (event != "head_published")
        store.commit({"step": 2}, expected_parent=head)
    assert store.load()[1] == {"step": 2}


def test_store_rejects_second_writer_stale_parent_and_corruption(tmp_path):
    s = CommitStore(tmp_path, "a" * 64)
    with s.lock():
        with pytest.raises(RuntimeError):
            with CommitStore(tmp_path, "a" * 64).lock():
                pass
        head = s.commit({"model": torch.ones(2)}, expected_parent=None)
        with pytest.raises(ValueError, match="stale"):
            s.commit({}, expected_parent=None)
    record = read_json(tmp_path / "commits" / f"{head}.json")
    (tmp_path / "objects" / (record["payload"] + ".pt")).write_bytes(b"broken")
    with pytest.raises(ValueError, match="hash"):
        s.load()
    with pytest.raises(ValueError, match="identity"):
        CommitStore(tmp_path, "b" * 64).load()


def test_store_budget_and_orphans(tmp_path):
    s = CommitStore(tmp_path, "a" * 64, max_bytes=100)
    with s.lock(), pytest.raises(ValueError, match="storage budget"):
        s.commit({"large": "x" * 1000}, expected_parent=None)
    assert s.head() is None


@pytest.fixture
def run_factory(tmp_path):
    weights = tmp_path / "parent.json"
    export_weights(PrismModel(), weights, CATALOG)
    spec = run_config(sha256_file(weights))
    def create(name="run", alter=None):
        current = copy.deepcopy(spec)
        if alter: alter(current)
        return Run.create(tmp_path / name, current, weights)
    return create


def synthetic_submit(run, monkeypatch, tmp_path, job="synthetic-job", *, count=3):
    behavior = Behavior.from_payload(run.store.get_payload(run.state["snapshot"]), runtime=run.runtime)
    shard = game(behavior, job=job, count=count)
    # This test replaces ONLY the external Rust auditor. It is not a rules test.
    monkeypatch.setattr("training.prism.ppo.coordinator.audit_game", lambda *a, **kw: shard)
    replay = tmp_path / f"{job}-synthetic-metadata.json"
    write_json(replay, {"seed": 0, "player_count": 2})
    attempt = run.start_attempt(job)
    run.submit(job, attempt, executable="not-executed", replay=replay, sidecar="not-executed")
    return attempt


def finish(run):
    while run.status()["phase"] == "UPDATING":
        run.step()


def test_two_cycles_pause_restore_and_no_double_consumption(run_factory, monkeypatch, tmp_path):
    run = run_factory()
    before = tensor_identity(run.learner.model.state_dict())
    snapshot = run.begin_cycle(schedule())
    with pytest.raises(ValueError, match="incomplete"):
        run.seal()
    synthetic_submit(run, monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="completed job"):
        run.start_attempt("synthetic-job")
    batch1 = run.seal()
    run.step(); run.pause()
    recovered = Run.open(run.root)
    assert recovered.status()["paused"]
    with pytest.raises(ValueError, match="paused"):
        recovered.step()
    recovered.pause(False); finish(recovered)
    assert recovered.status()["consumed"] == [batch1]
    with pytest.raises(ValueError, match="no unconsumed"):
        recovered.step()
    with pytest.raises(ValueError, match="reused job"):
        recovered.begin_cycle(schedule())
    snapshot2 = recovered.begin_cycle(schedule("second-job"))
    assert snapshot2["behavior_id"] != snapshot["behavior_id"]
    synthetic_submit(recovered, monkeypatch, tmp_path, "second-job")
    batch2 = recovered.seal(); finish(recovered)
    assert recovered.status()["consumed"] == [batch1, batch2]
    assert recovered.status()["global_step"] == 8  # 3 rows, minibatch2, 2 passes, 2 cycles
    assert tensor_identity(recovered.learner.model.state_dict()) != before
    assert all(not name.startswith("style") or torch.equal(value, run.state["model"][name])
               for name, value in recovered.learner.model.state_dict().items())
    recovered.export(tmp_path / "export")
    assert len(read_json(tmp_path / "export" / "weights.json")["state_dict"]) == 32
    with pytest.raises(ValueError, match="cycle"):
        recovered.begin_cycle(schedule("third"))


@pytest.mark.parametrize("event", ["backward_done", "optimizer_done", "payload_written", "commit_written", "head_published"])
def test_optimizer_resume_identical_to_uninterrupted(run_factory, monkeypatch, tmp_path, event):
    base = run_factory("base")
    base.begin_cycle(schedule()); synthetic_submit(base, monkeypatch, tmp_path); base.seal()
    clone_path = tmp_path / "interrupted"
    shutil.copytree(base.root, clone_path)
    finish(base)
    interrupted = Run.open(clone_path)
    def crash(point):
        if point == event: raise RuntimeError("injected crash")
    with pytest.raises(RuntimeError, match="injected"):
        interrupted.step(fault=crash)
    resumed = Run.open(clone_path)
    finish(resumed)
    assert resumed.status()["global_step"] == base.status()["global_step"]
    assert resumed.status()["consumed"] == base.status()["consumed"]
    assert tensor_identity(resumed.learner.model.state_dict()) == tensor_identity(base.learner.model.state_dict())
    a, b = resumed.learner.optimizer.state_dict(), base.learner.optimizer.state_dict()
    assert a["param_groups"] == b["param_groups"]
    for key, slot in a["state"].items():
        for name, value in slot.items():
            assert torch.equal(value, b["state"][key][name])
    assert torch.equal(resumed.state["rng"]["torch"], base.state["rng"]["torch"])
    expected_extra = 0 if event == "head_published" else 1
    assert resumed.state["update_attempts"] == base.state["update_attempts"] + expected_extra


def test_config_identity_change_rejected_on_resume(run_factory):
    run = run_factory()
    changed = read_json(run.root / "config.json")
    changed["ppo"]["lr"] *= 2
    write_json(run.root / "config.json", changed)
    with pytest.raises(ValueError, match="identity"):
        Run.open(run.root)


def test_attempt_recovery_and_stale_attempt_rejected(run_factory):
    run = run_factory(); run.begin_cycle(schedule())
    first = run.start_attempt("synthetic-job")
    second = Run.open(run.root).start_attempt("synthetic-job")
    assert second == first + 1
    with pytest.raises(ValueError, match="stale"):
        run.submit("synthetic-job", first, executable="unused", replay="unused", sidecar="unused")


def test_truncation_audit_failure_stops_run(run_factory, monkeypatch, tmp_path):
    run = run_factory(); run.begin_cycle(schedule())
    attempt = run.start_attempt("synthetic-job")
    path = tmp_path / "truncated.json"
    write_json(path, {"seed": 0, "player_count": 2})
    behavior = Behavior.from_payload(run.store.get_payload(run.state["snapshot"]), runtime=run.runtime)
    shard = game(behavior) | {"terminal": False}
    monkeypatch.setattr("training.prism.ppo.coordinator.audit_game", lambda *a, **k: shard)
    with pytest.raises(ValueError, match="terminal"):
        run.submit("synthetic-job", attempt, executable="unused", replay=path, sidecar="unused")
    assert Run.open(run.root).status()["phase"] == "FAILED"
    with pytest.raises(ValueError): run.seal()
    assert run.status()["global_step"] == 0


def test_optimizer_budget_is_hard_no_extra_update(run_factory, monkeypatch, tmp_path):
    run = run_factory(alter=lambda s: s["budget"].update(max_optimizer_steps=1))
    run.begin_cycle(schedule()); synthetic_submit(run, monkeypatch, tmp_path); run.seal(); run.step()
    identity = tensor_identity(run.learner.model.state_dict())
    with pytest.raises(ValueError, match="budget"):
        run.step()
    assert run.status()["global_step"] == 1
    assert tensor_identity(run.learner.model.state_dict()) == identity


def test_unfrozen_style_campaign_rejected(run_factory):
    with pytest.raises(ValueError, match="reward-extractor"):
        run_factory(alter=lambda s: s["ppo"].update(style_beta=0.2, style_value_weight=0.5))


def test_lr_restore_mismatch_rejected(run_factory):
    run = run_factory()
    with run.store.lock():
        run.state["optimizer"]["param_groups"][0]["lr"] = 0.25
        run.store.commit(run.state, expected_parent=run.parent)
    with pytest.raises(ValueError, match="LR"):
        Run.open(run.root)

def test_attempt_boolean_rejected(run_factory):
    run = run_factory(); run.begin_cycle(schedule()); run.start_attempt("synthetic-job")
    with pytest.raises(ValueError, match="attempt"):
        run.submit("synthetic-job", True, executable="unused", replay="unused", sidecar="unused")


def test_store_first_write_and_rejected_reservation_do_not_poison_cache(tmp_path):
    from training.prism.ppo.store import json_bytes
    small = {'x': 'a'}
    budget = 1 + 2 * len(json_bytes(small))
    store = CommitStore(tmp_path, 'a'*64, max_bytes=budget)
    with store.lock():
        with pytest.raises(ValueError, match='storage budget'):
            store.put_json({'too_large': 'x'*1000})
        assert store._used_bytes == 1
        first = store.put_json(small)
        assert store._used_bytes == 1 + len(json_bytes(small))
        assert store.put_json(small) == first
        assert store._used_bytes == 1 + len(json_bytes(small))
        store.put_json({'x': 'b'})
        assert store._used_bytes == budget
        with pytest.raises(ValueError, match='storage budget'): store.put_json({'x': 'c'})
        assert store._used_bytes == budget
        assert sum(p.stat().st_size for p in tmp_path.rglob('*') if p.is_file()) == budget


def test_store_head_replacement_counts_net_bytes(tmp_path):
    store = CommitStore(tmp_path, 'a'*64, max_bytes=1024**2)
    with store.lock():
        head = store.commit({'step': 0}, expected_parent=None)
        store.commit({'step': 1}, expected_parent=head)
    assert store._used_bytes == sum(p.stat().st_size for p in tmp_path.rglob('*') if p.is_file())
