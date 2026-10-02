"""Control bounded Prism PPO on local/SSH hosts and hand off full checkpoints."""
import argparse
import json
from pathlib import Path
import shlex
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from training.prism_portable.common import component, digest, read, write

DEFAULT_PROFILES = ROOT / "local-artifacts/prism/portable-m57/profiles.json"


def invoke(profile, argv):
    args = ["--host", profile["host_file"], *argv]
    if "ssh" in profile:
        remote = shlex.join([profile["python"], "-B", profile["rpc"]])
        p = subprocess.run(["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                            profile["ssh"], remote],
                           input=json.dumps({"argv": args}) + "\n", capture_output=True,
                           text=True, timeout=140)
        if p.returncode:
            raise RuntimeError("SSH control relay failed: " + p.stderr[-1000:])
        response = json.loads(p.stdout)
    else:
        p = subprocess.run([profile["python"], "-B", "-m", "training.prism_portable.control", *args],
                           cwd=profile["project"], capture_output=True, text=True, timeout=120)
        response = {"exit_code": p.returncode, "stdout": p.stdout, "stderr": p.stderr}
    if response["exit_code"]:
        raise RuntimeError("host control failed: " + response["stderr"][-2400:])
    return json.loads(response["stdout"])


def copy_archive(source, destination, path, target):
    if "ssh" in source and "ssh" in destination:
        raise ValueError("use a local controller hop for remote-to-remote transfers")
    if "ssh" in source:
        subprocess.run(["scp", source["ssh"] + ":" + path, target], check=True, timeout=120)
    elif "ssh" in destination:
        subprocess.run(["scp", path, destination["ssh"] + ":" + target], check=True, timeout=120)
    else:
        import shutil
        shutil.copyfile(path, target)


def transfer(profiles, source_name, target_name, campaign, journal_directory):
    source, target = profiles[source_name], profiles[target_name]
    component(target_name)
    stamp = str(time.time_ns())
    archive = source["root"] + "/transfers/handoff-" + stamp + ".tar.gz"
    prepared = invoke(source, ["prepare", "--campaign", campaign, "--destination", target_name,
                               "--archive", archive])
    destination = target["root"] + "/transfers/" + prepared["transfer_id"] + ".tar.gz"
    journal = {"status": "PREPARED", "source": source_name, "destination": target_name,
               "campaign": campaign, "prepared": prepared, "destination_archive": destination}
    path = Path(journal_directory) / (prepared["transfer_id"] + ".json")
    write(path, journal)
    try:
        copy_archive(source, target, archive, destination)
        result = invoke(target, ["import", "--archive", destination, "--sha256", prepared["sha256"]])
        journal.update(status="IMPORTED", receipt=result)
        write(path, journal)
        return result | {"journal": str(path)}
    except BaseException as exc:
        journal.update(status="FAILED_SAFE_SOURCE_RELEASED", error=type(exc).__name__ + ": " + str(exc))
        write(path, journal)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", default=str(DEFAULT_PROFILES))
    parser.add_argument("--host", required=True)
    parser.add_argument("command", choices=("create", "start", "status", "stop", "kill", "transfer", "prepare", "import"))
    parser.add_argument("--campaign")
    parser.add_argument("--line")
    parser.add_argument("--blueprint")
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--mode", choices=("boundary", "force"), default="boundary")
    parser.add_argument("--to")
    parser.add_argument("--archive")
    parser.add_argument("--sha256")
    args = parser.parse_args()
    profiles = read(args.profiles)
    component(args.host)
    if args.command == "transfer":
        result = transfer(profiles, args.host, args.to, args.campaign,
                          ROOT / "local-artifacts/prism/portable-m57/transfers")
    else:
        argv = [args.command]
        for key in ("campaign", "line", "blueprint", "archive", "sha256"):
            value = getattr(args, key)
            if value is not None:
                argv += ["--" + key, value]
        if args.command == "start":
            argv += ["--cycles", str(args.cycles)]
        if args.command == "stop":
            argv += ["--mode", args.mode]
        if args.command == "prepare":
            argv += ["--destination", args.to]
        result = invoke(profiles[args.host], argv)
    print(json.dumps(result, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
