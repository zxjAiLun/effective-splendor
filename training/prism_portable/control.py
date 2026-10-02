"""Host-side control CLI, invoked locally or through SSH without a shell argv."""
import argparse
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
import uuid

from .common import component, lock, package_identity, read, write
from .processes import cgroup_accounting, systemctl, unit_properties
from .protocol import assert_owner, bind, create, import_handoff, prepare_handoff


def host_config(path):
    host = read(path)
    host["_path"] = str(Path(path).resolve())
    if host["code_identity"] != package_identity():
        raise ValueError("host portable source identity changed")
    if host["platform"] != {"system": platform.system(), "machine": platform.machine(), "node": platform.node()}:
        raise ValueError("host configuration was copied to a different machine")
    return host


def campaign_path(host, campaign):
    root = Path(host["root"]).resolve() / "campaigns"
    path = Path(campaign).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError("campaign is outside this host's owned directory")
    return path


def owned_alive(row, root):
    import psutil
    if "pid" not in row:
        return False
    try:
        p = psutil.Process(row["pid"])
        if p.status() == psutil.STATUS_ZOMBIE:
            return False
        argv = p.cmdline()
        if row["launch_token"] not in argv or str(root) not in argv or "training.prism_portable.worker" not in argv:
            # A reused PID is evidence the previous worker ended. Treat it as
            # unowned: status/start can proceed, while stop/kill never touch it.
            return False
        return True
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        return False


def status(host, root):
    root = campaign_path(host, root)
    path = root / "control/status.json"
    row = read(path) if path.exists() else {"status": "NOT_STARTED"}
    row["alive"] = owned_alive(row, root) if "pid" in row else False
    row["ownership"] = read(root / "ownership.json")
    for name in ("progress", "heartbeat", "cancel-fixture-ready"):
        p = root / ("control/" + name + ".json")
        if p.exists():
            row[name] = read(p)
    return row


def start(host, root, cycles):
    root = campaign_path(host, root)
    if type(cycles) is not int or cycles <= 0:
        raise ValueError("positive bounded cycles required")
    with lock(Path(host["root"]) / "operations"):
        owner = read(root / "ownership.json")
        assert_owner(root, host["host_id"], owner["nonce"])
        bind(read(root / "blueprint.json"), host)
        previous = status(host, root)
        if previous["alive"] or previous["status"] == "STARTING":
            raise ValueError("owned campaign already running/starting")
        control = root / "control"
        control.mkdir(exist_ok=True)
        for name in ("force-stop.json", "boundary-stop.json", "boundary-ack.json"):
            p = control / name
            if p.exists():
                p.unlink()
        token = uuid.uuid4().hex
        argv = [host["python"], "-B", "-u", "-m", "training.prism_portable.worker",
                "--campaign", str(root), "--host", host["_path"], "--nonce", owner["nonce"],
                "--launch-token", token, "--cycles", str(cycles)]
        row = {"status": "STARTING", "launch_token": token, "nonce": owner["nonce"], "argv": argv}
        write(control / "status.json", row)
        env = os.environ.copy()
        env.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="2", MKL_NUM_THREADS="2")
        if os.name == "nt":
            with open(control / "supervisor.stdout.log", "ab") as out, open(control / "supervisor.stderr.log", "ab") as err:
                p = subprocess.Popen(argv, cwd=host["project"], env=env, stdin=subprocess.DEVNULL,
                                     stdout=out, stderr=err, creationflags=0x08000000 | 0x00000200)
            row["pid"] = p.pid
        else:
            unit = "prism-ppo-supervisor-" + token + ".service"
            slice_name = "prism-ppo-" + token + ".slice"
            limits = read(root / "blueprint.json")["template"]["limits"]
            command = ["systemd-run", "--user", "--quiet", "--unit=" + unit, "--slice=" + slice_name,
                       "--working-directory=" + host["project"],
                       "--property=Type=exec", "--property=KillMode=control-group",
                       "--property=MemoryAccounting=yes", "--property=CPUAccounting=yes",
                       "--property=MemoryMax=" + str(limits["memory_bytes"]), "--property=TasksMax=512",
                       "--property=RuntimeMaxSec=7200",
                       "--property=StandardOutput=append:" + str(control / "supervisor.stdout.log"),
                       "--property=StandardError=append:" + str(control / "supervisor.stderr.log"),
                       "--setenv=PRISM_PPO_SLICE=" + slice_name,
                       "--setenv=OPENBLAS_NUM_THREADS=1", "--setenv=OMP_NUM_THREADS=2",
                       "--setenv=MKL_NUM_THREADS=2", *argv]
            subprocess.run(command, capture_output=True, text=True, check=True, timeout=20)
            systemctl("set-property", "--runtime", slice_name, "MemoryMax=" + str(limits["memory_bytes"]),
                      "TasksMax=512", "CPUAccounting=yes", "MemoryAccounting=yes", "CPUQuota=200%")
            props = systemctl("show", unit, "--property=MainPID", "--value").stdout.strip()
            row.update(pid=int(props), unit=unit, slice=slice_name)
        # Do not overwrite a RUNNING status already published by the new supervisor.
        if read(control / "status.json")["status"] == "STARTING":
            write(control / "status.json", row)
        write(control / (token + ".launch.json"), row)
        return row


def stop(host, root, mode):
    root = campaign_path(host, root)
    owner = read(root / "ownership.json")
    assert_owner(root, host["host_id"], owner["nonce"])
    row = status(host, root)
    if not row["alive"] and row["status"] != "STARTING":
        return row
    write(root / ("control/" + ("boundary-stop.json" if mode == "boundary" else "force-stop.json")),
          {"nonce": owner["nonce"], "requested_at": time.time(), "mode": mode})
    return {"status": "STOP_REQUESTED", "mode": mode, "campaign": str(root)}


def hard_kill(host, root):
    """Fallback only after command-line identity check; marks conservative recovery."""
    from .worker import stop_linux_children
    root = campaign_path(host, root)
    row = status(host, root)
    if not row["alive"]:
        return row
    if os.name == "nt":
        import psutil
        psutil.Process(row["pid"]).kill()  # closing its Job Object kills all owned children
    else:
        launch = read(root / ("control/" + row["launch_token"] + ".launch.json"))
        if not re.fullmatch(r"prism-ppo-supervisor-[0-9a-f]{32}\.service", launch["unit"]):
            raise ValueError("unowned systemd supervisor")
        stop_linux_children(root / "control", row["ownership"]["nonce"])
        systemctl("kill", "--kill-whom=all", "--signal=SIGKILL", launch["unit"], check=False)
        systemctl("stop", launch["unit"], check=False)
    row.update(status="INTERRUPTED_OPERATOR", killed_at=time.time())
    write(root / "control/status.json", {k: v for k, v in row.items() if k not in ("ownership", "alive")})
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("command", choices=("create", "start", "status", "stop", "kill", "prepare", "import"))
    parser.add_argument("--campaign")
    parser.add_argument("--line")
    parser.add_argument("--blueprint")
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--mode", choices=("boundary", "force"), default="boundary")
    parser.add_argument("--destination")
    parser.add_argument("--archive")
    parser.add_argument("--sha256")
    args = parser.parse_args()
    host = host_config(args.host)
    if args.command == "create":
        root = Path(host["root"]) / "campaigns" / (component(args.line) + "-g0")
        result = {"campaign": str(root), "ownership": create(root, read(args.blueprint), host, args.line)}
    elif args.command == "start":
        result = start(host, args.campaign, args.cycles)
    elif args.command == "status":
        result = status(host, args.campaign)
    elif args.command == "stop":
        result = stop(host, args.campaign, args.mode)
    elif args.command == "kill":
        result = hard_kill(host, args.campaign)
    elif args.command == "prepare":
        result = prepare_handoff(campaign_path(host, args.campaign), host, component(args.destination), args.archive)
    else:
        result = import_handoff(args.archive, args.sha256, host)
    import json
    print(json.dumps(result, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
