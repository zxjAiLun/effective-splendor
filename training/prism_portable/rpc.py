"""JSON/argv SSH relay. Executable as a file; never evaluates shell source."""
import json
from pathlib import Path
import subprocess
import sys


def main():
    line = sys.stdin.buffer.readline(1024 * 1024 + 1)
    if len(line) > 1024 * 1024:
        raise ValueError("oversized control request")
    request = json.loads(line)
    if set(request) != {"argv"} or not isinstance(request["argv"], list) or not all(
            isinstance(x, str) for x in request["argv"]):
        raise ValueError("control request must be a string argv array")
    root = Path(__file__).resolve().parents[2]
    p = subprocess.run([sys.executable, "-B", "-m", "training.prism_portable.control", *request["argv"]],
                       cwd=root, capture_output=True, text=True, timeout=120)
    print(json.dumps({"exit_code": p.returncode, "stdout": p.stdout, "stderr": p.stderr}), flush=True)


if __name__ == "__main__":
    main()
