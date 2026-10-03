"""Read-only M60 post-training audit: final checkpoint validation and 68-input boundary parity.

Writes checkpoint-validation.json and final-parity.json inside the cloud project.
Opens the committed run read-only; starts no games and applies no optimizer updates.
"""
import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
import time

import torch


def require(condition, message):
    if not condition:
        raise SystemExit("FAIL: " + message)


def sha256_file(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def compare_values(a, b, errors):
    if isinstance(a, (int, float)) and not isinstance(a, bool):
        if not math.isclose(a, b, rel_tol=1e-4, abs_tol=1e-4):
            raise ValueError("boundary parity drift")
        errors.append(abs(a - b))
    elif isinstance(a, dict):
        if set(a) != set(b):
            raise ValueError("prediction schema mismatch")
        for key in a:
            compare_values(a[key], b[key], errors)
    elif isinstance(a, list):
        if len(a) != len(b):
            raise ValueError("prediction dimension mismatch")
        for x, y in zip(a, b):
            compare_values(x, y, errors)
    elif a != b:
        raise ValueError("prediction mode/action mismatch")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    args = parser.parse_args()
    project = Path(args.project).resolve()
    sys.path.insert(0, str(project))
    from training.prism_portable.common import read, write
    from training.prism_portable.engine.export import load_weights
    from training.prism_portable.engine.parity import predict_jsonl
    from training.prism_portable.engine.ppo.coordinator import Run
    from training.prism_portable.engine.ppo.model import PPOModel

    host = read(project / "host.json")
    run = Run.open(project / "campaigns/m60-alpha-bigcard-g0/run")
    state = run.state
    require(state["phase"] == "COMMITTED", "final phase not COMMITTED")
    require(state["cycle"] == 4, "unexpected cycle count")
    require(state["global_step"] == 216, "unexpected optimizer count")
    require(state["attempts"] == 1024, "unexpected attempt count")
    require(state["decisions"] == 27360, "unexpected learning decision count")
    require(len(state["consumed"]) == 4 and len(set(state["consumed"])) == 4, "unexpected consumed batches")
    require(len(state["all_jobs"]) == 1024 and len(set(state["all_jobs"])) == 1024, "unexpected job count")
    slots = len(state["optimizer"]["state"])
    require(slots == 36, "unexpected AdamW slot count")

    export_path = project / "campaigns/m60-alpha-bigcard-g0/cycle-4-export/weights.json"
    require(export_path.exists(), "final c4 export missing")
    final_weights_sha256 = sha256_file(export_path)
    catalog = run.config["catalog_fingerprint"]
    exported = load_weights(export_path, expected_catalog_fingerprint=catalog)
    exported_sd = exported.state_dict()
    checkpoint_sd = state["model"]
    require(len(exported_sd) == 32, "unexpected exported tensor count")
    exact = 0
    for key, tensor in exported_sd.items():
        full_key = "policy." + key
        require(full_key in checkpoint_sd, "checkpoint missing exported tensor: " + full_key)
        require(torch.equal(tensor.detach().cpu(), checkpoint_sd[full_key].detach().cpu()),
                "export/checkpoint tensor drift: " + full_key)
        exact += 1
    parent = load_weights(host["assets"]["parent"]["path"], expected_catalog_fingerprint=catalog)
    parent_sd = parent.state_dict()
    different = any(not torch.equal(parent_sd[k].detach().cpu(), checkpoint_sd["policy." + k].detach().cpu())
                    for k in exported_sd)
    receipt = {"status": "PASS", "phase": state["phase"], "cycle": state["cycle"],
               "global_step": state["global_step"], "attempts": state["attempts"],
               "decisions": state["decisions"], "jobs": len(state["all_jobs"]),
               "consumed_batches": len(state["consumed"]), "optimizer_slots": slots,
               "exact_export_tensors": exact, "different_from_parent": different,
               "final_weights_sha256": final_weights_sha256,
               "commit": run.parent, "run_identity": run.identity,
               "rss_bytes": int(next(line.split()[1] for line in
                                      Path("/proc/self/status").read_text().splitlines()
                                      if line.startswith("VmRSS"))) * 1024,
               "scope": "final committed checkpoint and exported 32 policy/value tensors; no new matches or optimizer updates",
               "new_games": 0, "new_optimizer_updates": 0, "observed_at": time.time()}
    write(project / "checkpoint-validation.json", receipt)
    print(json.dumps(receipt, indent=1))

    fixtures = host["assets"]["fixtures"]["path"]
    work = project / "audit-m60"
    work.mkdir(exist_ok=True)
    raw = work / "inputs.jsonl"
    rows = [json.loads(line) for line in Path(fixtures).read_text().splitlines()]
    raw.write_text("".join(json.dumps(row.get("input", row)) + "\n" for row in rows), encoding="utf-8")
    rust = work / "final-rust.jsonl"
    argv = [host["assets"]["engine"]["path"], "prism-predict", "--weights", str(export_path),
            "--input", str(raw), "--output", str(rust)]
    p = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    require(p.returncode == 0, "native final prediction failed: " + p.stderr[-500:])
    python_out = work / "final-python.jsonl"
    predict_jsonl(export_path, raw, python_out, expected_catalog_fingerprint=catalog)
    expected_rows = [json.loads(line) for line in rust.read_text().splitlines()]
    actual_rows = [json.loads(line) for line in python_out.read_text().splitlines()]
    require(len(expected_rows) == len(actual_rows) == len(rows) and bool(actual_rows),
            "final parity row count mismatch")
    errors = []
    for a, b in zip(expected_rows, actual_rows):
        compare_values(a, b, errors)
    parity = {"status": "PASS", "boundary_inputs": len(rows), "max_abs_error": max(errors),
              "atol": 1e-4, "rtol": 1e-4, "weights_sha256": final_weights_sha256,
              "native_command": argv, "new_games": 0, "observed_at": time.time()}
    write(project / "final-parity.json", parity)
    print(json.dumps(parity, indent=1))


if __name__ == "__main__":
    main()
