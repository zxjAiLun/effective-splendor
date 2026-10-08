"""M62 autonomous post-training pipeline driver.

Monitors serial training to completion, then deterministically executes:
1. Training artifact audit (scripts/prism_building_audit_m62.py)
2. Training report and global binding (scripts/prism_building_training_report_m62.py)
3. Evaluation prepare (scripts/prism_building_evaluation_m62.py prepare)
4. Evaluation verify (scripts/prism_building_evaluation_m62.py verify)
5. Evaluation execution (9,280 games via systemd cgroup)
6. Evaluation report and gate outcomes (scripts/prism_building_report_m62.py)
7. Pipeline completion receipt (pipeline-driver-completion.json)

Zero retries; fail-closed on any error; all outputs hash-bound.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def require(cond, msg):
    if not cond:
        raise ValueError("Pipeline driver: " + msg)


def run_cmd(argv, cwd=None):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}] RUN: {' '.join(str(a) for a in argv)}")
    sys.stdout.flush()
    res = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"FAILED (exit {res.returncode}):\nSTDOUT:\n{res.stdout[-2000:]}\nSTDERR:\n{res.stderr[-2000:]}")
        sys.stdout.flush()
        raise RuntimeError(f"Command failed (exit {res.returncode}): {' '.join(str(a) for a in argv)}")
    print(f"OK (exit 0)")
    sys.stdout.flush()
    return res


def wait_for_training(project, receipts_dir, poll_interval=30):
    print(f"Waiting for serial training to finish in {receipts_dir}...")
    sys.stdout.flush()
    final_path = receipts_dir / "serial-final.json"
    last_log = 0
    while True:
        if final_path.exists():
            try:
                data = json.loads(final_path.read_text(encoding="utf-8"))
                if data.get("status") == "TRAINING_COMPLETED_PENDING_INDEPENDENT_AUDIT":
                    print(f"Training completed successfully! Finished at: {data.get('finished_at')}")
                    sys.stdout.flush()
                    return data
                elif "FAILED" in data.get("status", ""):
                    raise RuntimeError(f"Serial training failed: {data.get('status')} error: {data.get('error')}")
            except (json.JSONDecodeError, OSError):
                pass
        now = time.time()
        if now - last_log >= 60:
            last_log = now
            # Log current training status
            status_path = receipts_dir / "serial-status.json"
            if status_path.exists():
                try:
                    st = json.loads(status_path.read_text(encoding="utf-8"))
                    arms = st.get("arms", {})
                    ctrl_st = arms.get("control", {}).get("status", "unknown")
                    beta_st = arms.get("beta", {}).get("status", "unknown")
                    print(f"[{time.strftime('%H:%M:%S UTC', time.gmtime())}] Training in progress: control={ctrl_st}, beta={beta_st}")
                    sys.stdout.flush()
                except Exception:
                    pass
        time.sleep(poll_interval)


def run_pipeline(project):
    project = Path(project).resolve()
    python = sys.executable
    receipts_dir = project / "training-receipts"
    started_at = time.time()
    steps_record = {}

    # Step 0: Wait for serial training
    t_start = time.time()
    training_final = wait_for_training(project, receipts_dir)
    steps_record["training"] = {
        "status": "PASS",
        "finished_at": training_final.get("finished_at"),
        "wall_seconds": time.time() - t_start,
        "arms": {arm: training_final.get("arms", {}).get(arm, {}).get("final_weights_sha256") for arm in ("control", "beta")},
    }

    # Step 1: Training Artifact Audit
    print("\n--- STEP 1: Training Artifact Audit ---")
    t1 = time.time()
    run_cmd([python, "-B", "scripts/prism_building_audit_m62.py", "--project", str(project)], cwd=str(project))
    steps_record["audit"] = {"status": "PASS", "wall_seconds": time.time() - t1}

    # Step 2: Training Report & Binding
    print("\n--- STEP 2: Training Report & Global Audit Binding ---")
    t2 = time.time()
    run_cmd([python, "-B", "scripts/prism_building_training_report_m62.py", "--project", str(project)], cwd=str(project))
    binding_path = project / "training-artifact-audit.json"
    require(binding_path.is_file(), "training-artifact-audit.json not created")
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    require(binding.get("status") == "PASS_TRAINING_ARTIFACT_AUDIT", "training audit binding status != PASS")
    steps_record["training_report"] = {
        "status": "PASS",
        "wall_seconds": time.time() - t2,
        "binding_sha256": sha256_file(binding_path),
    }

    # Step 3: Evaluation Prepare
    print("\n--- STEP 3: Evaluation Prepare ---")
    t3 = time.time()
    config_path = project / "benchmarks/m62-prism-beta-building.config.json"
    config_sha = sha256_file(config_path)
    run_cmd([python, "-B", "scripts/prism_building_evaluation_m62.py", "prepare",
             "--project", str(project), "--config-sha256", config_sha,
             "--audit-receipt", str(binding_path)], cwd=str(project))
    exec_path = project / "evaluation/execution.json"
    require(exec_path.is_file(), "evaluation/execution.json missing after prepare")
    exec_sha = sha256_file(exec_path)
    steps_record["eval_prepare"] = {
        "status": "PASS",
        "wall_seconds": time.time() - t3,
        "execution_sha256": exec_sha,
    }

    # Step 4: Evaluation Verify
    print("\n--- STEP 4: Evaluation Verify ---")
    t4 = time.time()
    run_cmd([python, "-B", "scripts/prism_building_evaluation_m62.py", "verify",
             "--project", str(project), "--execution-sha256", exec_sha], cwd=str(project))
    steps_record["eval_verify"] = {"status": "PASS", "wall_seconds": time.time() - t4}

    # Step 5: Evaluation Execution (systemd cgroup)
    print("\n--- STEP 5: Evaluation Execution (9,280 physical games) ---")
    t5 = time.time()
    unit = f"prism-m62-evaluation-{exec_sha[:8]}"
    eval_cmd = [
        "systemd-run", "--user", "--quiet",
        f"--unit={unit}",
        "--property=MemoryMax=8589934592",
        "--property=CPUQuota=200%",
        "--property=RuntimeMaxSec=28800",
        f"--working-directory={project}",
        python, "-B", "scripts/prism_building_evaluation_m62.py", "run",
        "--project", str(project), "--execution-sha256", exec_sha,
    ]
    run_cmd(eval_cmd, cwd=str(project))
    print(f"Launched systemd unit {unit}.service. Waiting for completion...")
    sys.stdout.flush()

    # Poll systemd unit until dead
    unit_service = f"{unit}.service"
    last_log = 0
    while True:
        status_proc = subprocess.run(["systemctl", "--user", "is-active", unit_service], capture_output=True, text=True)
        active_state = status_proc.stdout.strip()
        now = time.time()
        if now - last_log >= 60:
            last_log = now
            print(f"[{time.strftime('%H:%M:%S UTC', time.gmtime())}] Evaluation running ({unit_service}: {active_state}, {round(now - t5)}s elapsed)")
            sys.stdout.flush()
        if active_state in ("failed", "inactive"):
            break
        time.sleep(15)

    comp_path = project / "evaluation/completion.json"
    require(comp_path.is_file(), "evaluation/completion.json missing")
    comp = json.loads(comp_path.read_text(encoding="utf-8"))
    require(comp.get("status") == "COMPLETED_FIXED_AB_EVALUATION", f"evaluation completion status != COMPLETED: {comp.get('status')}")
    result_path = project / "evaluation/result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    steps_record["eval_run"] = {
        "status": "PASS",
        "wall_seconds": time.time() - t5,
        "physical_games": comp.get("physical_games"),
        "result_sha256": comp.get("result_sha256"),
        "gates": result.get("gates"),
        "arm_verdicts": result.get("arm_verdicts"),
    }

    # Step 6: Evaluation Report
    print("\n--- STEP 6: Evaluation Report & Markdown Generation ---")
    t6 = time.time()
    output_md = project / "docs/prism/m62-prism-beta-building-evaluation.md"
    run_cmd([python, "-B", "scripts/prism_building_report_m62.py",
             "--work", str(project / "evaluation"),
             "--output", str(output_md)], cwd=str(project))
    require(output_md.is_file(), "report Markdown missing")
    steps_record["eval_report"] = {
        "status": "PASS",
        "wall_seconds": time.time() - t6,
        "report_path": str(output_md),
        "report_sha256": sha256_file(output_md),
    }

    # Final summary receipt
    total_wall = time.time() - started_at
    receipt = {
        "format": "m62-pipeline-driver-completion-v1",
        "status": "PASS_FULL_PIPELINE",
        "project": str(project),
        "total_wall_seconds": total_wall,
        "finished_at": time.time(),
        "steps": steps_record,
        "gates": result.get("gates"),
        "arm_verdicts": result.get("arm_verdicts"),
        "final_models": {
            "control": {"weights_sha256": training_final.get("arms", {}).get("control", {}).get("final_weights_sha256")},
            "beta": {"weights_sha256": training_final.get("arms", {}).get("beta", {}).get("final_weights_sha256")},
        },
        "report": {
            "path": str(output_md),
            "sha256": sha256_file(output_md),
        },
    }
    receipt_path = project / "pipeline-driver-completion.json"
    with receipt_path.open("w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2)
        f.write("\n")
    print(f"\n=======================================================")
    print(f"PIPELINE COMPLETE: status=PASS_FULL_PIPELINE wall={round(total_wall, 1)}s")
    print(f"GATES: {json.dumps(result.get('gates'), indent=2)}")
    print(f"REPORT: {output_md}")
    print(f"RECEIPT: {receipt_path}")
    print(f"=======================================================")
    sys.stdout.flush()
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="/home/ubuntu/splendor-ppo-m62", type=Path)
    args = parser.parse_args()
    run_pipeline(args.project)


if __name__ == "__main__":
    main()
