"""Control/process/package tests; no game generation or model-strength claims."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import time

import psutil
import pytest

from training.prism_portable.common import component, digest, lock, read, write
from training.prism_portable.processes import ProcessTree
from training.prism_portable.protocol import unpack_verified


@pytest.mark.parametrize("value", ["../x", "a/b", "", "a;rm", "x y", "a\\b"])
def test_control_identifier_rejects_paths_and_shell(value):
    with pytest.raises(ValueError):
        component(value)


def test_control_lock_excludes_second_writer(tmp_path):
    with lock(tmp_path):
        # A distinct process is needed: POSIX locks may have process semantics.
        code = "from training.prism_portable.common import lock;import sys\nwith lock(sys.argv[1]):pass\n"
        p = subprocess.run([sys.executable, "-c", code, str(tmp_path)], capture_output=True, text=True)
        assert p.returncode != 0
        assert "already has a writer" in p.stderr
    with lock(tmp_path):
        write(tmp_path / "after.json", {"unlocked": True})
    assert read(tmp_path / "after.json")["unlocked"]


@pytest.mark.parametrize("bad_name", ["../outside", "/absolute", "campaign/../../outside", "campaign/a\\b", "C:/outside"])
def test_archive_rejects_unsafe_paths_before_extract(tmp_path, bad_name):
    archive = tmp_path / "bad.tar.gz"
    with tarfile.open(archive, "w:gz") as t:
        data = b"x"
        m = tarfile.TarInfo(bad_name)
        m.size = len(data)
        t.addfile(m, io.BytesIO(data))
    stage = tmp_path / "stage"
    with pytest.raises(ValueError):
        unpack_verified(archive, digest(archive), stage)
    assert not stage.exists()


def test_archive_verifies_inventory_and_all_member_hashes(tmp_path):
    archive = tmp_path / "archive.tar.gz"
    manifest = {"format": "prism-portable-bundle-v1", "files": {"x.json": "0" * 64}}
    with tarfile.open(archive, "w:gz") as t:
        for name, data in [("manifest.json", json.dumps(manifest).encode()), ("campaign/x.json", b"{}")]:
            m = tarfile.TarInfo(name)
            m.size = len(data)
            t.addfile(m, io.BytesIO(data))
    with pytest.raises(ValueError, match="member hash"):
        unpack_verified(archive, digest(archive), tmp_path / "stage")
    with pytest.raises(ValueError, match="archive hash"):
        unpack_verified(archive, "1" * 64, tmp_path / "other")


def test_owned_deadline_kills_descendant_tree(tmp_path):
    pidfile = tmp_path / "child.txt"
    code = ("import subprocess,sys,time,pathlib;"
            "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)']);"
            "pathlib.Path(sys.argv[1]).write_text(str(p.pid));time.sleep(120)")
    with (tmp_path / "stdout").open("wb") as out, (tmp_path / "stderr").open("wb") as err:
        with ProcessTree(cpu_seconds=20, memory_bytes=256 * 1024**2) as tree:
            parent = tree.start([sys.executable, "-c", code, str(pidfile)], cwd=str(Path.cwd()), stdout=out, stderr=err)
            deadline = time.monotonic() + 10
            while not pidfile.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            assert pidfile.exists()
            child = int(pidfile.read_text())
            result = tree.wait(wall_seconds=0.4)
            assert result["stop_reason"] == "wall_deadline"
            assert result["returncode"] != 0
            assert result["peak_memory_bytes"] > 0
    for pid in (parent.pid, child):
        deadline = time.monotonic() + 5
        while psutil.pid_exists(pid) and time.monotonic() < deadline:
            try:
                if psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
                    break
            except psutil.NoSuchProcess:
                break
            time.sleep(0.05)
        assert not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE


def test_storage_limit_catches_fast_process(tmp_path):
    storage = tmp_path / "storage"
    storage.mkdir()
    (storage / "too-large").write_bytes(b"x" * 1024)
    with (tmp_path / "out").open("wb") as out, (tmp_path / "err").open("wb") as err:
        with ProcessTree(cpu_seconds=20, memory_bytes=256 * 1024**2) as tree:
            tree.start([sys.executable, "-c", "pass"], cwd=str(Path.cwd()), stdout=out, stderr=err)
            result = tree.wait(wall_seconds=10, storage_root=storage, max_storage_bytes=100)
    assert result["stop_reason"] == "storage_deadline"


@pytest.mark.parametrize("broken", ("attempts", "physical_decisions", "retries", "completed_jobs"))
def test_transfer_rejects_reset_or_inconsistent_physical_budget(broken):
    from training.prism_portable.protocol import validate_launch_ledger
    ledger = {"format": "prism-ppo-launch-ledger-v1", "failed": False, "physical_decisions": 260,
              "retries": 1, "attempts": {
                  "1": {"status": "INFRA_ABORT", "charged_decisions": 256, "retry_charged": True},
                  "2": {"status": "COMPLETE", "charged_decisions": 4, "job": {"job_id": "j1"}}}}
    state = {"attempts": 2, "all_jobs": ["j1"]}
    spec = {"limits": {"max_physical_decisions": 512, "max_infra_retries": 1}}
    if broken == "completed_jobs":
        state["all_jobs"].append("j2")
    elif broken == "attempts":
        state["attempts"] = 1
    else:
        ledger[broken] = 0
    with pytest.raises(ValueError):
        validate_launch_ledger(ledger, state, spec)


def test_reused_pid_is_not_alive_owned_supervisor(tmp_path):
    import os
    from training.prism_portable.control import owned_alive
    # An actually running, unrelated PID stands in for a recycled old worker PID.
    assert not owned_alive({"pid": os.getpid(), "launch_token": "old-worker-token"}, tmp_path)


def test_kill_reused_pid_preserves_unrelated_real_process(tmp_path):
    import os
    from training.prism_portable.common import write
    from training.prism_portable.control import hard_kill
    campaign = tmp_path / "campaigns" / "previous"
    write(campaign / "ownership.json", {"status": "ACTIVE", "nonce": "former-owner"})
    write(campaign / "control/status.json", {"status": "STOPPED_COMMITTED", "pid": os.getpid(),
                                            "launch_token": "former-worker"})
    result = hard_kill({"root": str(tmp_path)}, campaign)
    assert result["alive"] is False
    assert psutil.pid_exists(os.getpid())
