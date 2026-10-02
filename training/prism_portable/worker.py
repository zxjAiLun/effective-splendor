"""Detached bounded supervisor and synchronous numerical worker."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from .common import lock, package_identity, read, write
from .processes import ProcessTree, cgroup_accounting, systemctl


def stop_linux_children(control, nonce):
    for p in (Path(control) / "trees").glob("*.owner.json"):
        row = read(p)
        if row.get("owner_nonce") != nonce or not re.fullmatch(r"prism-ppo-tree-[0-9a-f]{32}\.service", row["unit"]):
            continue
        systemctl("kill", "--kill-whom=all", "--signal=SIGKILL", row["unit"], check=False)
        systemctl("stop", row["unit"], check=False)


def cancel_fixture(root, number):
    """Declared process fixture before a real match; never enabled in calibration."""
    if number != 1 or os.environ.get("PRISM_PPO_CANCEL_FIXTURE") != "1":
        return
    root = Path(root)
    if not read(root / "blueprint.json").get("cancel_fixture", False):
        raise ValueError("cancellation fixture not authorized by blueprint")
    marker = root / "control/cancel-fixture-used.json"
    try:
        with marker.open("x", encoding="utf-8") as stream:
            stream.write('{"used":true}\n')
    except FileExistsError:
        return
    script = ("import subprocess,sys,time;"
              "subprocess.Popen([sys.executable,'-c','import time;time.sleep(300)']);"
              "time.sleep(300)")
    with open(root / "control/fixture.stdout.log", "ab") as out, open(root / "control/fixture.stderr.log", "ab") as err:
        with ProcessTree(cpu_seconds=30, memory_bytes=256 * 1024**2) as tree:
            process = tree.start([sys.executable, "-c", script], cwd=str(Path.cwd()), stdout=out, stderr=err)
            write(root / "control/cancel-fixture-ready.json", {"attempt": number, "pid": process.pid,
                                                              "scope": "synthetic process tree before real matchup"})
            result = tree.wait(wall_seconds=30)
    raise RuntimeError("cancellation fixture was not terminated: " + str(result))


def execute(root, host, nonce, cycles):
    from .protocol import assert_owner, bind
    from .engine.ppo.arena import Campaign
    from .engine.ppo.coordinator import Run
    assert_owner(root, host["host_id"], nonce)
    blueprint = read(root / "blueprint.json")
    if read(root / "contract.json") != bind(blueprint, host):
        raise ValueError("native campaign binding changed")
    campaign = Campaign(root, read(root / "contract.json"))
    _, ledger = campaign._load()
    if ledger["failed"] or campaign.run.state["phase"] == "FAILED":
        raise ValueError("fatal campaign cannot be resumed")
    if campaign.run.state["paused"]:
        campaign.run.pause(False)  # explicit start on the same currently owned campaign
    target = min(len(campaign.spec["cycles"]), campaign.run.state["cycle"] + cycles)
    while campaign.run.state["cycle"] < target:
        assert_owner(root, host["host_id"], nonce)
        start = time.perf_counter()
        campaign.work(stop_after_cycle=True)
        summary = read(root / f"cycle-{campaign.run.state['cycle']}-summary.json")
        summary["portable_cycle_wall_seconds"] = time.perf_counter() - start
        write(root / f"cycle-{campaign.run.state['cycle']}-portable-summary.json", summary)
        status = campaign.run.status()
        write(root / "control/progress.json", {**status, "observed_at": time.time(),
                                              "run_identity": campaign.run.identity})
        request = root / "control/boundary-stop.json"
        if request.exists() and read(request).get("nonce") == nonce:
            campaign.run.pause(True)
            write(root / "control/boundary-ack.json", {"cycle": status["cycle"], "phase": status["phase"],
                                                     "commit": campaign.run.parent, "nonce": nonce})
            return
    # Independent of a stop request, each execute invocation ends at a real boundary.
    final = Run.open(root / "run")
    write(root / "control/progress.json", {**final.status(), "observed_at": time.time(),
                                          "run_identity": final.identity})


def supervise(root, host, nonce, cycles, launch_token):
    from .protocol import assert_owner
    root = Path(root).resolve()
    control = root / "control"
    launch_path = control / (launch_token + ".launch.json")
    deadline = time.monotonic() + 20
    while not launch_path.exists():
        if time.monotonic() > deadline:
            raise RuntimeError("supervisor start was not acknowledged by controller")
        time.sleep(0.05)
    with lock(control):
        owner = assert_owner(root, host["host_id"], nonce)
        blueprint = read(root / "blueprint.json")
        if host["code_identity"] != package_identity():
            raise ValueError("host source package changed")
        ledger = read(root / "resource-ledger.json")
        cpu_limit = blueprint["template"]["limits"]["campaign_cpu_seconds"]
        if ledger["sessions"] and ledger["sessions"][-1]["status"] == "RUNNING":
            old = ledger["sessions"][-1]
            if "snapshot" not in old:
                charge = old["cpu_reservation"]
            else:
                charge = min(old["cpu_reservation"], old["snapshot"]["cpu_seconds"]
                             + max(0, time.time() - old["snapshot"]["observed_at"]) * old["logical_cpus"])
            ledger["cpu_spent"] += charge
            old.update(status="INTERRUPTED", conservative_cpu_charge=charge)
        remaining = cpu_limit - ledger["cpu_spent"]
        wall = ledger["deadline"] - time.time()
        if remaining <= 0 or wall <= 0:
            raise ValueError("original campaign CPU/wall budget exhausted")
        session = {"status": "RUNNING", "started_at": time.time(), "cpu_reservation": remaining,
                   "logical_cpus": os.cpu_count() or 1, "launch_token": launch_token,
                   "owner_generation": owner["generation"], "cycles_requested": cycles}
        ledger["sessions"].append(session)
        write(root / "resource-ledger.json", ledger)
        status = {"status": "RUNNING", "pid": os.getpid(), "launch_token": launch_token,
                  "nonce": nonce, "started_at": session["started_at"], "generation": owner["generation"]}
        write(control / "status.json", status)
        argv = [sys.executable, "-B", "-u", "-m", "training.prism_portable.worker", "--execute",
                "--campaign", str(root), "--host", host["_path"], "--nonce", nonce,
                "--cycles", str(cycles), "--launch-token", launch_token]
        os.environ.update(PRISM_PPO_HOST_ID=host["host_id"], PRISM_PPO_OWNER_NONCE=nonce,
                          PRISM_PPO_CONTROL_DIR=str(control), OPENBLAS_NUM_THREADS="1",
                          OMP_NUM_THREADS="2", MKL_NUM_THREADS="2")
        if blueprint.get("cancel_fixture"):
            os.environ["PRISM_PPO_CANCEL_FIXTURE"] = "1"
        session_start_cpu = cgroup_accounting(os.environ["PRISM_PPO_SLICE"])["cpu_seconds"] if os.name != "nt" else 0
        def snapshot(counters):
            session["snapshot"] = counters | {"observed_at": time.time()}
            write(root / "resource-ledger.json", ledger)
            write(control / "heartbeat.json", session["snapshot"])
        def force_request():
            p = control / "force-stop.json"
            return "operator_terminate" if p.exists() and read(p).get("nonce") == nonce else None
        try:
            with open(control / "stdout.log", "ab", buffering=0) as out, open(control / "stderr.log", "ab", buffering=0) as err:
                with ProcessTree(cpu_seconds=remaining, memory_bytes=blueprint["template"]["limits"]["memory_bytes"],
                                 max_processes=32) as tree:
                    process = tree.start(argv, cwd=host["project"], stdout=out, stderr=err)
                    status["worker_pid"] = process.pid
                    write(control / "status.json", status)
                    accounting = None
                    if os.name != "nt":
                        def accounting():
                            r = cgroup_accounting(os.environ["PRISM_PPO_SLICE"])
                            r["cpu_seconds"] = max(0, r["cpu_seconds"] - session_start_cpu)
                            return r
                    resources = tree.wait(wall_seconds=wall, storage_root=root,
                                          max_storage_bytes=blueprint["template"]["run"]["budget"]["max_storage_bytes"],
                                          stop_checker=force_request, snapshot=snapshot, accounting=accounting)
                    if os.name != "nt":
                        stop_linux_children(control, nonce)
                        resources.update(accounting())
            session.update(resources, status="FINISHED", finished_at=time.time())
            ledger["cpu_spent"] += resources["cpu_seconds"]
            write(root / "resource-ledger.json", ledger)
            if resources["stop_reason"] == "operator_terminate":
                verdict = "STOPPED_OPERATOR"
            elif resources["returncode"] != 0 or resources["stop_reason"] is not None:
                verdict = "FAILED"
            elif (control / "boundary-ack.json").exists():
                verdict = "STOPPED_BOUNDARY"
            else:
                verdict = "STOPPED_COMMITTED"
            status.update(status=verdict, finished_at=time.time(), resources=resources)
            write(control / "status.json", status)
            if verdict == "FAILED":
                raise RuntimeError("owned worker failed; inspect retained logs")
        except BaseException as exc:
            if os.name != "nt":
                stop_linux_children(control, nonce)
            status.update(status="FAILED", error=type(exc).__name__ + ": " + str(exc))
            write(control / "status.json", status)
            raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--nonce", required=True)
    parser.add_argument("--launch-token", required=True)
    parser.add_argument("--cycles", type=int, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.cycles <= 0:
        raise ValueError("positive bounded cycle count required")
    host = read(args.host)
    host["_path"] = str(Path(args.host).resolve())
    if args.execute:
        execute(Path(args.campaign), host, args.nonce, args.cycles)
    else:
        supervise(Path(args.campaign), host, args.nonce, args.cycles, args.launch_token)


if __name__ == "__main__":
    main()
