"""Supplemental resource authority for an unchanged, interrupted M54 campaign.

The immutable training contract/source/model/RNG/schedules are not edited.
Old unknown supervisor reservations stay charged. This separate authorization
only grants bounded extra aggregate user CPU; original wall/memory/storage
limits still apply. Save atomic Job Object accounting snapshots every 5 seconds.
"""
from __future__ import annotations

import argparse
import copy
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from training.prism.io import canonical_hash, read_json, sha256_file, write_json

FORMAT = "prism-ppo-resource-supplement-v1"


def settle_interruption(session, observed_at):
    """All owned processes must have been observed absent by the caller.

    Charge the last persisted actual CPU plus the upper bound of unobserved
    work (wall * machine logical CPUs). With no usable snapshot, charge the
    entire reservation, not zero. Never revise a settled charge downward.
    """
    if session["status"] != "RUNNING":
        return session
    result = copy.deepcopy(session)
    reservation = session["cpu_reservation"]
    snapshot = session.get("snapshot")
    if snapshot is None or observed_at < snapshot["observed_at"]:
        charge = reservation
        method = "full_unaccounted_reservation"
    else:
        charge = min(reservation, snapshot["user_cpu_seconds"] +
                     (observed_at - snapshot["observed_at"]) * session["logical_cpus"])
        method = "persisted_actual_plus_wall_times_machine_cpus_upper_bound"
    result.update(status="INTERRUPTED", user_cpu_seconds=charge,
                  charge_type=method, processes_observed_absent_at=observed_at)
    return result


def remaining_cpu(sessions, limit):
    spent = sum(s.get("user_cpu_seconds", s["cpu_reservation"]) for s in sessions)
    return max(0.0, limit - spent)


def monitor(tree, session, persist, *, deadline, storage_root, max_storage_bytes,
            clock=time.time, sleep=time.sleep, directory_size=None, interval=5.0):
    """Monitor only this tree; snapshot precedes every deadline/storage check."""
    if directory_size is None:
        from training.prism.ppo.processes import directory_bytes
        directory_size = directory_bytes
    reason = None
    next_snapshot = 0.0
    while tree.process.poll() is None:
        now = clock()
        if now >= next_snapshot:
            session["snapshot"] = tree.accounting() | {"observed_at": now}
            persist()
            next_snapshot = now + interval
            if directory_size(storage_root) > max_storage_bytes:
                reason = "storage_deadline"
        if now >= deadline:
            reason = "wall_deadline"
        if reason:
            tree.api.TerminateJobObject(tree.handle, 124)
            break
        sleep(0.1)
    code = tree.process.wait(timeout=10)
    now = clock()
    resources = tree.accounting() | {"returncode": code, "stop_reason": reason,
                                    "finished_at": now, "wall_seconds": now - session["started_at"]}
    session.update(resources, status="FINISHED")
    persist()
    return resources


def validate_authorization(auth, campaign, old_sessions_path):
    from training.prism.ppo.coordinator import source_identity
    required = {"format", "authorization_id", "campaign", "contract_file_sha256",
                "run_identity", "source_sha256", "old_sessions_sha256", "additional_cpu_seconds",
                "original_cpu_seconds", "authorized_at", "authorized_by", "scope", "invariants"}
    if set(auth) != required or auth["format"] != FORMAT:
        raise ValueError("supplemental resource authorization schema")
    if auth["authorized_by"] != "user-explicit-approval" or auth["scope"] != "complete-original-2048-games-only":
        raise ValueError("explicit limited user authority required")
    if type(auth["additional_cpu_seconds"]) is not int or not 1 <= auth["additional_cpu_seconds"] <= 24000:
        raise ValueError("bounded additional CPU required")
    if Path(auth["campaign"]).resolve() != campaign:
        raise ValueError("resource campaign identity drift")
    if sha256_file(campaign / "contract.json") != auth["contract_file_sha256"]:
        raise ValueError("immutable training contract drift")
    if source_identity() != auth["source_sha256"]:
        raise ValueError("immutable training source drift")
    if sha256_file(old_sessions_path) != auth["old_sessions_sha256"]:
        raise ValueError("original cost ledger drift")
    old_sessions = read_json(old_sessions_path)
    if any(row["status"] == "RUNNING" for row in old_sessions):
        raise ValueError("original supervisor interruption must be reconciled first")
    original_cost = sum(s.get("user_cpu_seconds", s["cpu_reservation"]) for s in old_sessions)
    if original_cost != auth["original_cpu_seconds"]:
        raise ValueError("original CPU charge mismatch")
    return original_cost


def supervise(authorization_path, *, state_path, stdout_path, stderr_path):
    from training.prism.ppo.arena import check_assets, validate_spec
    from training.prism.ppo.coordinator import Run
    from training.prism.ppo.processes import ProcessTree
    from training.prism.ppo.store import CommitStore

    auth = read_json(authorization_path)
    campaign = Path(auth["campaign"]).resolve()
    validate_authorization(auth, campaign, campaign / "supervisor-sessions.json")
    spec = validate_spec(read_json(campaign / "contract.json"))
    check_assets(spec)
    state_path = Path(state_path)
    digest = canonical_hash(auth)
    supervisor_lock = CommitStore(campaign / "resource-supervisor", digest)
    with supervisor_lock.lock():
        run = Run.open(campaign / "run")
        if run.identity != auth["run_identity"]:
            raise ValueError("unchanged run identity required")
        if run.state["paused"] or run.state["phase"] == "FAILED":
            raise ValueError("run must not be paused/failed")
        deadline = run.state["started_at"] + spec["run"]["budget"]["max_run_seconds"]
        state = read_json(state_path) if state_path.exists() else {
            "format": "m54-supplemental-resource-state-v1", "authorization_sha256": digest,
            "sessions": [], "original_cpu_charge": auth["original_cpu_seconds"],
            "deadline": deadline}
        if state["authorization_sha256"] != digest or state["deadline"] != deadline:
            raise ValueError("resource state/authorization drift")
        # A live older worker keeps the dispatcher lock. Never reconcile or
        # spawn while another campaign worker is active.
        with CommitStore(campaign / "dispatcher", run.identity).lock():
            if state["sessions"] and state["sessions"][-1]["status"] == "RUNNING":
                state["sessions"][-1] = settle_interruption(state["sessions"][-1], time.time())
                write_json(state_path, state)
        remaining = remaining_cpu(state["sessions"], auth["additional_cpu_seconds"])
        if remaining <= 0 or time.time() >= deadline:
            raise ValueError("supplemental CPU/original wall budget exhausted")
        session = {"status": "RUNNING", "cpu_reservation": remaining,
                   "started_at": time.time(), "logical_cpus": os.cpu_count() or 1,
                   "supervisor_pid": os.getpid()}
        state["sessions"].append(session)
        state.update(pid=os.getpid(), complete=False, error=None)
        persist = lambda: write_json(state_path, state)
        persist()
        argv = [sys.executable, "-B", "-u", "-m", "training.prism.ppo.arena", "--campaign", str(campaign), "--worker"]
        try:
            with Path(stdout_path).open("ab", buffering=0) as out, Path(stderr_path).open("ab", buffering=0) as err:
                with ProcessTree(cpu_seconds=remaining, memory_bytes=spec["limits"]["memory_bytes"], max_processes=6) as tree:
                    child = tree.start(argv, cwd=str(ROOT), stdout=out, stderr=err)
                    session.update(worker_pid=child.pid, argv=argv)
                    persist()
                    resources = monitor(tree, session, persist, deadline=deadline, storage_root=campaign,
                                        max_storage_bytes=spec["run"]["budget"]["max_storage_bytes"])
            if resources["returncode"] != 0 or resources["stop_reason"] is not None:
                raise RuntimeError("supplemental supervised worker stopped; retain and inspect artifacts")
            final = Run.open(campaign / "run")
            if final.state["phase"] != "COMMITTED" or final.state["cycle"] != 8:
                raise ValueError("worker returned without original eight cycles committed")
            state.update(complete=True, finished_at=time.time(), final_commit=final.parent,
                         total_additional_user_cpu=sum(s["user_cpu_seconds"] for s in state["sessions"]))
            persist()
        except BaseException as exc:
            state.update(error=type(exc).__name__ + ": " + str(exc), complete=False)
            persist()
            raise
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--stdout", required=True)
    parser.add_argument("--stderr", required=True)
    args = parser.parse_args()
    supervise(args.authorization, state_path=args.state, stdout_path=args.stdout, stderr_path=args.stderr)


if __name__ == "__main__":
    main()
