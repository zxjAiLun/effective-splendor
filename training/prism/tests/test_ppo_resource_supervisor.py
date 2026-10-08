"""Bounded supplementary accounting tests; no games, updates or new seeds."""
import copy
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import prism_ppo_resource_supervisor as supervisor


def test_interrupted_reservation_is_not_zeroed_or_mutated():
    original = {"status": "RUNNING", "cpu_reservation": 24000, "logical_cpus": 20}
    settled = supervisor.settle_interruption(original, 100)
    assert original["status"] == "RUNNING"
    assert settled["user_cpu_seconds"] == 24000
    assert supervisor.remaining_cpu([settled], 24000) == 0
    assert supervisor.settle_interruption(settled, 200) == settled


def test_interrupted_snapshot_charges_actual_and_gap_upper_bound():
    original = {"status": "RUNNING", "cpu_reservation": 1000, "logical_cpus": 20,
                "snapshot": {"observed_at": 100, "user_cpu_seconds": 80}}
    result = supervisor.settle_interruption(original, 105)
    assert result["user_cpu_seconds"] == 180
    assert supervisor.remaining_cpu([result], 1000) == 820
    assert supervisor.settle_interruption(original, 200)["user_cpu_seconds"] == 1000
    assert supervisor.settle_interruption(original, 99)["user_cpu_seconds"] == 1000
    assert original["status"] == "RUNNING"


class FakeTree:
    def __init__(self, clock):
        self.clock = clock
        self.process = self
        self.api = self
        self.handle = "owned-tree"
        self.terminated = False

    def poll(self):
        return 0 if self.clock[0] >= 11 else None

    def wait(self, timeout):
        return 124 if self.terminated else 0

    def accounting(self):
        return {"user_cpu_seconds": self.clock[0] * 2, "kernel_cpu_seconds": 0,
                "total_processes": 3, "active_processes": int(self.poll() is None)}

    def TerminateJobObject(self, handle, code):
        assert handle == "owned-tree" and code == 124
        self.terminated = True
        return True


@pytest.mark.parametrize("mode,reason", [("normal", None), ("wall", "wall_deadline"), ("storage", "storage_deadline")])
def test_monitor_persists_snapshots_and_enforces_limits(mode, reason):
    clock = [0.0]
    tree = FakeTree(clock)
    session = {"started_at": 0.0, "status": "RUNNING"}
    snapshots = []
    def tick(_):
        clock[0] += 1
    result = supervisor.monitor(tree, session, lambda: snapshots.append(copy.deepcopy(session)),
                                deadline=2 if mode == "wall" else 100,
                                storage_root="fixture", max_storage_bytes=10,
                                clock=lambda: clock[0], sleep=tick,
                                directory_size=lambda _: 11 if mode == "storage" else 0)
    assert result["stop_reason"] == reason
    assert result["returncode"] == (124 if reason else 0)
    assert snapshots[0]["snapshot"]["user_cpu_seconds"] == 0
    assert snapshots[-1]["status"] == "FINISHED"
    if mode == "normal":
        assert [s["snapshot"]["observed_at"] for s in snapshots[:-1]] == [0, 5, 10]
        assert session["user_cpu_seconds"] == 22


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object actual accounting")
def test_actual_short_process_job_accounting_is_persisted(tmp_path):
    from training.prism.io import write_json, read_json
    from training.prism.ppo.processes import ProcessTree
    import time
    state_path = tmp_path / "resources.json"
    session = {"started_at": time.time(), "status": "RUNNING"}
    with ProcessTree(cpu_seconds=10, memory_bytes=256 * 1024**2) as tree:
        tree.start([sys.executable, "-B", "-c", "import time; time.sleep(.3)"], cwd=".",
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        result = supervisor.monitor(tree, session, lambda: write_json(state_path, session),
                                    deadline=time.time() + 10, storage_root=tmp_path,
                                    max_storage_bytes=1024**2, interval=.1)
    assert result["returncode"] == 0 and result["stop_reason"] is None
    saved = read_json(state_path)
    assert saved["status"] == "FINISHED" and saved["snapshot"]["observed_at"] >= session["started_at"]
    assert saved["user_cpu_seconds"] >= saved["snapshot"]["user_cpu_seconds"] >= 0


def test_changed_contract_or_cost_ledger_is_rejected(tmp_path, monkeypatch):
    from training.prism.io import sha256_file, write_json
    from training.prism.ppo import coordinator
    monkeypatch.setattr(coordinator, "source_identity", lambda: "a" * 64)
    campaign = tmp_path.resolve()
    contract = campaign / "contract.json"
    write_json(contract, {"unchanged": True})
    ledger = campaign / "supervisor-sessions.json"
    write_json(ledger, [{"status": "INTERRUPTED", "cpu_reservation": 24000, "user_cpu_seconds": 24000}])
    auth = {"format": supervisor.FORMAT, "authorization_id": "synthetic", "campaign": str(campaign),
            "contract_file_sha256": sha256_file(contract), "run_identity": "b" * 64,
            "source_sha256": "a" * 64, "old_sessions_sha256": sha256_file(ledger),
            "additional_cpu_seconds": 24000, "original_cpu_seconds": 24000,
            "authorized_at": 1, "authorized_by": "user-explicit-approval",
            "scope": "complete-original-2048-games-only", "invariants": {}}
    assert supervisor.validate_authorization(auth, campaign, ledger) == 24000
    changed = dict(auth, additional_cpu_seconds=24001)
    with pytest.raises(ValueError, match="bounded additional"):
        supervisor.validate_authorization(changed, campaign, ledger)
    write_json(ledger, [])
    with pytest.raises(ValueError, match="cost ledger drift"):
        supervisor.validate_authorization(auth, campaign, ledger)
