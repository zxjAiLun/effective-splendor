"""Bind an already installed host and verify native/Python inference parity."""
import argparse
import json
import math
from pathlib import Path
import platform
import subprocess
import sys
import uuid

from .common import digest, package_identity, write


def provision(root, project, engine, metrics, parent, initial, fixtures, host_id):
    root = Path(root).resolve()
    project = Path(project).resolve()
    for name in ("campaigns", "transfers", "imports", "preflight"):
        (root / name).mkdir(parents=True, exist_ok=True)
    inputs = {"engine": engine, "metrics": metrics, "parent": parent, "initial": initial, "fixtures": fixtures}
    assets = {name: {"path": str(Path(p).resolve()), "sha256": digest(p)} for name, p in inputs.items()}
    host = {"format": "prism-portable-host-v1", "host_id": host_id, "root": str(root),
            "project": str(project), "python": sys.executable, "code_identity": package_identity(),
            "platform": {"system": platform.system(), "machine": platform.machine(), "node": platform.node()},
            "assets": assets}
    output = root / "preflight" / uuid.uuid4().hex
    output.mkdir()
    raw = output / "inputs.jsonl"
    rows = [json.loads(line) for line in Path(fixtures).read_text().splitlines()]
    raw.write_text("".join(json.dumps(row.get("input", row)) + "\n" for row in rows), encoding="utf-8")
    rust = output / "rust.jsonl"
    argv = [str(Path(engine).resolve()), "prism-predict", "--weights", str(Path(parent).resolve()),
            "--input", str(raw), "--output", str(rust)]
    p = subprocess.run(argv, capture_output=True, text=True, timeout=120)
    if p.returncode:
        raise RuntimeError("native prediction failed: " + p.stderr)
    from .engine.parity import predict_jsonl
    from .engine.ppo.runtime import configure
    from .engine.io import read_json
    catalog = read_json(parent)["catalog_fingerprint"]
    python_out = output / "python.jsonl"
    predict_jsonl(parent, raw, python_out, expected_catalog_fingerprint=catalog)
    expected = [json.loads(line) for line in rust.read_text().splitlines()]
    actual = [json.loads(line) for line in python_out.read_text().splitlines()]
    errors = []
    def compare(a, b):
        if isinstance(a, (float, int)) and not isinstance(a, bool):
            if not math.isclose(a, b, rel_tol=1e-4, abs_tol=1e-4):
                raise ValueError("Rust/Python inference parity drift")
            errors.append(abs(a - b))
        elif isinstance(a, dict):
            if set(a) != set(b):
                raise ValueError("prediction schema mismatch")
            for k in a:
                compare(a[k], b[k])
        elif isinstance(a, list):
            if len(a) != len(b):
                raise ValueError("prediction dimension mismatch")
            for x, y in zip(a, b):
                compare(x, y)
        elif a != b:
            raise ValueError("prediction mode/action mismatch")
    if len(expected) != len(actual) or not actual:
        raise ValueError("prediction row count mismatch")
    for a, b in zip(expected, actual):
        compare(a, b)
    runtime = configure("cpu", 2)
    receipt = {"status": "PASS", "boundary_inputs": len(rows), "max_abs_error": max(errors),
               "atol": 1e-4, "rtol": 1e-4, "runtime": runtime, "assets": assets,
               "code_identity": host["code_identity"], "native_command": argv,
               "output": str(output), "new_games": 0}
    write(output / "host.json", host)
    write(output / "receipt.json", receipt)
    write(root / "host.json", host)
    write(root / "preflight.json", receipt)
    return host, receipt


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("root", "project", "engine", "metrics", "parent", "initial", "fixtures", "host-id"):
        p.add_argument("--" + key, required=True)
    a = p.parse_args()
    _, receipt = provision(a.root, a.project, a.engine, a.metrics, a.parent, a.initial, a.fixtures, a.host_id)
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    main()
