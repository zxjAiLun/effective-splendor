#!/usr/bin/env python3
"""Unified Speed & Throughput Benchmark across Local CPU, Local CUDA, and Cloud2 CPU.

Benchmarks all 7 target models:
1. aran-v0 (Neural Dueling Q)
2. aran-v0.1 (Neural Dueling Q + Grad Accum)
3. aran-v0.2 (Neural Dueling Q + Co-ev Iteration 2)
4. heuristic (v0.1 Baseline)
5. v0.2.8 (Heuristic v0.2.8 Single-Noble)
6. v0.2.9 (Heuristic v0.2.9 No-Bomb-Reserve)
7. S3 (Rollout-enhanced D=4, P=120)
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path

def get_platform_info():
    info = {
        "system": platform.system(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
    }
    try:
        import torch
        info["torch_version"] = torch.__version__
        info["cuda_available"] = torch.cuda.is_available()
        if torch.cuda.is_available():
            info["cuda_device_name"] = torch.cuda.get_device_name(0)
    except ImportError:
        info["torch_version"] = "none"
        info["cuda_available"] = False
    return info

def run_pytorch_benchmark(repo_root: Path, device_str: str, batch_sizes=(1, 16, 64), num_iters=200):
    try:
        import torch
    except ImportError:
        return {"error": "torch not installed"}
    
    device = torch.device(device_str)
    if device_str.startswith("cuda") and not torch.cuda.is_available():
        return {"error": "cuda not available"}

    sys.path.insert(0, str(repo_root / "training" / "m17_gpu"))
    try:
        from m50_train_semantic_entity_q import SemanticCardEntityDuelingQNet
    except Exception as e:
        return {"error": f"import failed: {e}"}

    models = {
        "aran-v0": repo_root / "local-artifacts" / "aran-v0" / "best_model.pt",
        "aran-v0.1": repo_root / "local-artifacts" / "aran-v01" / "best_model.pt",
        "aran-v02": repo_root / "local-artifacts" / "aran-v02" / "best_model.pt",
    }

    results = {}
    for name, pt_path in models.items():
        if not pt_path.exists():
            continue
        net = SemanticCardEntityDuelingQNet().to(device).eval()
        net.load_state_dict(torch.load(pt_path, map_location=device, weights_only=False))

        net_results = {}
        for B in batch_sizes:
            obs = torch.randn(B, 368, device=device)
            act = torch.randn(B * 32, 48, device=device)
            p_idx = torch.repeat_interleave(torch.arange(B, device=device), 32)
            lengths = [32] * B

            # Warmup
            for _ in range(20):
                with torch.no_grad():
                    _ = net(obs, act, p_idx, lengths)
            if device.type == "cuda":
                torch.cuda.synchronize()

            # Timing
            t0 = time.perf_counter()
            for _ in range(num_iters):
                with torch.no_grad():
                    _ = net(obs, act, p_idx, lengths)
            if device.type == "cuda":
                torch.cuda.synchronize()
            total_sec = time.perf_counter() - t0

            total_decisions = num_iters * B
            dec_per_sec = total_decisions / total_sec
            ms_per_dec = (total_sec / total_decisions) * 1000

            net_results[f"b_{B}"] = {
                "batch_size": B,
                "ms_per_decision": round(ms_per_dec, 3),
                "decisions_per_sec": round(dec_per_sec, 1),
                "total_sec": round(total_sec, 3),
            }
        results[name] = net_results
    return results

def run_match_benchmark(repo_root: Path, exe_main: Path, exe_v028: Path, exe_v029: Path, seeds: list[int]):
    """Runs 2-player matches for each model against baseline Heuristic."""
    models_config = {
        "heuristic": {
            "program": str(exe_main),
            "args": ["agent-heuristic", "--seed", "20260812"],
        },
        "v0.2.8": {
            "program": str(exe_v028),
            "args": ["agent-heuristic-v02", "--seed", "20260926"],
        },
        "v0.2.9": {
            "program": str(exe_v029),
            "args": ["agent-heuristic-v02", "--seed", "20260926"],
        },
        "aran-v0": {
            "program": str(exe_main),
            "args": [
                "agent-m50-policy",
                "--weights", str(repo_root / "local-artifacts" / "aran-v0" / "aran_v0_weights.json"),
                "--mode", "greedy",
            ],
        },
        "aran-v0.1": {
            "program": str(exe_main),
            "args": [
                "agent-m50-policy",
                "--weights", str(repo_root / "local-artifacts" / "aran-v01" / "aran_v01_weights.json"),
                "--mode", "greedy",
            ],
        },
        "aran-v0.2": {
            "program": str(exe_main),
            "args": [
                "agent-m50-policy",
                "--weights", str(repo_root / "local-artifacts" / "aran-v02" / "aran_v02_weights.json"),
                "--mode", "greedy",
            ],
        },
        "S3": {
            "program": str(exe_main),
            "args": ["agent-s3-rollout"],
        },
    }

    # Reference opponent: Heuristic v0.1
    opp_config = {
        "program": str(exe_main),
        "args": ["agent-heuristic", "--seed", "999999"],
    }

    results = {}
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        for model_name, cand_cfg in models_config.items():
            total_plies = 0
            total_duration_sec = 0.0
            game_durations = []
            completed_games = 0

            for seed in seeds:
                for cand_seat in [0, 1]:
                    game_id = f"bench-{model_name}-{seed}-r{cand_seat}"
                    agents = [cand_cfg, opp_config] if cand_seat == 0 else [opp_config, cand_cfg]
                    match_cfg = {
                        "game_id": game_id,
                        "seed": seed,
                        "agents": agents,
                        "handshake_timeout_ms": 10000,
                        "move_timeout_ms": 60000,
                        "shutdown_grace_ms": 2000,
                    }
                    cfg_p = tdp / "match_cfg.json"
                    rep_p = tdp / "match_rep.json"
                    rpl_p = tdp / "match_rpl.json"
                    if cfg_p.exists(): cfg_p.unlink()
                    if rep_p.exists(): rep_p.unlink()
                    if rpl_p.exists(): rpl_p.unlink()

                    cfg_p.write_text(json.dumps(match_cfg, indent=2))
                    t0 = time.perf_counter()
                    res = subprocess.run(
                        [
                            str(exe_main), "run-match",
                            "--config", str(cfg_p),
                            "--report-out", str(rep_p),
                            "--replay-out", str(rpl_p),
                        ],
                        capture_output=True,
                        text=True,
                    )
                    t1 = time.perf_counter()
                    duration = t1 - t0

                    if res.returncode == 0 and rep_p.exists():
                        rep = json.loads(rep_p.read_text())
                        plies = rep["outcome"]["completed_plies"]
                        total_plies += plies
                        total_duration_sec += duration
                        game_durations.append(duration)
                        completed_games += 1
                    else:
                        print(f"FAILED match {game_id}: rc={res.returncode}, err={res.stderr}")

            if completed_games > 0:
                mean_sec_per_game = total_duration_sec / completed_games
                mean_plies_per_game = total_plies / completed_games
                ms_per_ply = (total_duration_sec / total_plies) * 1000 if total_plies > 0 else 0
                plies_per_sec = total_plies / total_duration_sec if total_duration_sec > 0 else 0
                games_per_sec = completed_games / total_duration_sec if total_duration_sec > 0 else 0

                results[model_name] = {
                    "completed_games": completed_games,
                    "total_plies": total_plies,
                    "total_wall_sec": round(total_duration_sec, 3),
                    "mean_ms_per_game": round(mean_sec_per_game * 1000, 1),
                    "mean_plies_per_game": round(mean_plies_per_game, 1),
                    "ms_per_ply": round(ms_per_ply, 2),
                    "plies_per_sec": round(plies_per_sec, 1),
                    "games_per_sec": round(games_per_sec, 2),
                }
    return results

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--exe-main", type=Path, default=None)
    parser.add_argument("--exe-v028", type=Path, default=None)
    parser.add_argument("--exe-v029", type=Path, default=None)
    parser.add_argument("--skip-torch", action="store_true")
    parser.add_argument("--device", choices=["cpu", "cuda", "both"], default="both")
    parser.add_argument("--seeds-count", type=int, default=5)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    repo = args.repo_root.resolve()
    is_windows = platform.system() == "Windows"
    ext = ".exe" if is_windows else ""

    exe_main = args.exe_main or (repo / "target" / "release" / f"splendor{ext}")
    exe_v028 = args.exe_v028 or (
        (repo / "local-artifacts" / "s4-heuristic-v028-pilot" / f"splendor-candidate{ext}") if is_windows
        else (repo / "target" / "release" / "splendor-v028")
    )
    exe_v029 = args.exe_v029 or (
        (repo / "local-artifacts" / "s4-heuristic-v029-pilot" / f"splendor-candidate{ext}") if is_windows
        else exe_main
    )

    seeds = [9_311_000 + i for i in range(args.seeds_count)]

    report = {
        "platform": get_platform_info(),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    if not args.skip_torch:
        devices_to_test = []
        if args.device in ["cpu", "both"]:
            devices_to_test.append("cpu")
        if args.device in ["cuda", "both"]:
            import torch
            if torch.cuda.is_available():
                devices_to_test.append("cuda")

        torch_bench = {}
        for dev in devices_to_test:
            print(f"Running PyTorch benchmark on {dev}...")
            torch_bench[dev] = run_pytorch_benchmark(repo, dev)
        report["pytorch_inference"] = torch_bench

    print("Running match arena playout benchmark...")
    match_bench = run_match_benchmark(repo, exe_main, exe_v028, exe_v029, seeds)
    report["match_playout"] = match_bench

    output_str = json.dumps(report, indent=2)
    print("\n=== BENCHMARK REPORT ===")
    print(output_str)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_str)
        print(f"\nSaved report to {args.output}")

if __name__ == "__main__":
    main()
