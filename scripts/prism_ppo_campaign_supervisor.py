"""Snapshotting supervisor for a normal bounded continuation campaign.

No extra resource grant: charge only against contract campaign_cpu_seconds.
Reuses tested 5s Job Object accounting and conservative interrupted-gap charging.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.prism_ppo_continue import verify_initialization
from scripts.prism_ppo_resource_supervisor import monitor, remaining_cpu, settle_interruption
from training.prism.io import canonical_hash, read_json, sha256_file, write_json
from training.prism.ppo.arena import check_assets, validate_spec
from training.prism.ppo.coordinator import Run, source_identity
from training.prism.ppo.processes import ProcessTree
from training.prism.ppo.store import CommitStore


def resource_identity(spec, lineage):
    return canonical_hash({"contract": spec, "lineage": lineage,
        "source_sha256": source_identity(), "supervisor_sha256": sha256_file(__file__),
        "monitor_sha256": sha256_file(ROOT / "scripts/prism_ppo_resource_supervisor.py")})


def prepare_state(state, identity, run_identity, deadline, now):
    """Caller holds resource and dispatcher locks; never reset cost/deadline."""
    if state is None:
        state = {"format": "prism-ppo-campaign-resource-v1", "identity": identity,
                 "run_identity": run_identity, "deadline": deadline, "sessions": [],
                 "complete": False, "error": None}
    if (state.get("identity"), state.get("run_identity"), state.get("deadline")) != (identity, run_identity, deadline):
        raise ValueError("resource contract/run/deadline drift")
    if state["sessions"] and state["sessions"][-1]["status"] == "RUNNING":
        state["sessions"][-1] = settle_interruption(state["sessions"][-1], now)
    return state


def supervise(campaign, lineage_path, *, state_path, stdout_path, stderr_path):
    campaign, state_path = Path(campaign).resolve(), Path(state_path)
    spec = validate_spec(read_json(campaign / "contract.json"))
    lineage = read_json(lineage_path)
    check_assets(spec)
    verify_initialization(campaign, lineage)
    identity = resource_identity(spec, lineage)
    with CommitStore(campaign / "resource-supervisor", identity).lock():
        run = Run.open(campaign / "run")
        deadline = run.state["started_at"] + spec["run"]["budget"]["max_run_seconds"]
        if run.state["paused"] or run.state["phase"] == "FAILED":
            raise ValueError("campaign paused/failed; inspect before resume")
        with CommitStore(campaign / "dispatcher", run.identity).lock():
            state = prepare_state(read_json(state_path) if state_path.exists() else None,
                                  identity, run.identity, deadline, time.time())
            write_json(state_path, state)
        if state["complete"]:
            if run.state["phase"] != "COMMITTED" or run.state["cycle"] != len(spec["cycles"]):
                raise ValueError("completed resource ledger/run drift")
            return state
        remaining = remaining_cpu(state["sessions"], spec["limits"]["campaign_cpu_seconds"])
        if remaining <= 0 or time.time() >= deadline:
            raise ValueError("campaign CPU/wall budget exhausted")
        session = {"status": "RUNNING", "cpu_reservation": remaining,
                   "started_at": time.time(), "logical_cpus": os.cpu_count() or 1,
                   "supervisor_pid": os.getpid()}
        state["sessions"].append(session)
        state.update(pid=os.getpid(), error=None)
        persist = lambda: write_json(state_path, state)
        persist()
        argv = [sys.executable, "-B", "-u", "-m", "training.prism.ppo.arena",
                "--campaign", str(campaign), "--worker"]
        try:
            with Path(stdout_path).open("ab", buffering=0) as out, Path(stderr_path).open("ab", buffering=0) as err:
                with ProcessTree(cpu_seconds=remaining, memory_bytes=spec["limits"]["memory_bytes"], max_processes=6) as tree:
                    child = tree.start(argv, cwd=str(ROOT), stdout=out, stderr=err)
                    session.update(worker_pid=child.pid, argv=argv)
                    persist()
                    resources = monitor(tree, session, persist, deadline=deadline, storage_root=campaign,
                                        max_storage_bytes=spec["run"]["budget"]["max_storage_bytes"])
            if resources["returncode"] != 0 or resources["stop_reason"] is not None:
                raise RuntimeError("bounded worker stopped; retain and inspect artifacts")
            final = Run.open(campaign / "run")
            if final.state["phase"] != "COMMITTED" or final.state["cycle"] != len(spec["cycles"]):
                raise ValueError("worker returned without all cycles committed")
            state.update(complete=True, finished_at=time.time(), final_commit=final.parent,
                         total_user_cpu_seconds=sum(s["user_cpu_seconds"] for s in state["sessions"]))
            persist()
        except BaseException as exc:
            state.update(complete=False, error=type(exc).__name__ + ": " + str(exc))
            persist()
            raise
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--lineage", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--stdout", required=True)
    parser.add_argument("--stderr", required=True)
    args = parser.parse_args()
    supervise(args.campaign, args.lineage, state_path=args.state,
              stdout_path=args.stdout, stderr_path=args.stderr)


if __name__ == "__main__":
    main()
