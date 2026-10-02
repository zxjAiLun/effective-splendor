"""Keep an owned systemd cgroup alive until its final accounting is collected."""
import argparse
import os
from pathlib import Path
import subprocess
import time

from .common import write


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--record", required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument("--stdout", required=True)
    parser.add_argument("--stderr", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        raise ValueError("empty owned command")
    with open(args.stdout, "ab", buffering=0) as out, open(args.stderr, "ab", buffering=0) as err:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=out, stderr=err)
        write(args.record, {"pid": process.pid, "keeper_pid": os.getpid(), "argv": command,
                            "started_at": time.time(), "status": "RUNNING"})
        code = process.wait()
        write(args.record, {"pid": process.pid, "keeper_pid": os.getpid(), "argv": command,
                            "returncode": code, "finished_at": time.time(), "status": "FINISHED"})
        deadline = time.monotonic() + 60
        while not Path(args.release).exists() and time.monotonic() < deadline:
            time.sleep(0.05)
    raise SystemExit(0 if code == 0 else 1)


if __name__ == "__main__":
    main()
