"""M41A P2 exhaustive corpus driver (authorized 2026-09-04, basis
209ecd5): generate the 304-game teacher corpus over the FROZEN splits.

Frozen by the P0-exit review:
  train           9_000_000..9_000_191 (192 games)
  validation      9_000_192..9_000_239 (48 games)
  power-cal       9_000_240..9_000_303 (64 games)  — SEALED (trainer
                   may not read until F/U final checkpoints are sealed)
  formal reserve  9_000_304..9_000_815 — NOT generated in P2

Per game: selected seat = global ordinal mod 2; the 25/50/75% acting-
decision states; EVERY legal action branched (run-branches with the
MANDATORY run contract); D2/D2 continuation; absolute ply cap 150.

The canonical run-contract.json is written first and every run-branches
call passes it; an existing corpus root with a different contract SHA
stops the driver.

NO F/U training, NO formal scoring, NO formal-reserve branches.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO / "training/m17_gpu"))
os.environ["PYTHONPATH"] = str(REPO / "training/m17_gpu")

SPLN = REPO / "target" / "release" / "splendor.exe"
CATALOG = REPO / "apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"
D2 = REPO / "local-artifacts/m25-recovery-exp-d2-v2/checkpoint.pt"
M17 = REPO / "training/m17_gpu"

DESIGN_SHA = "c05d3fb162c73a7d7127b910f5a10c97f347e0b9"
EXECUTOR_COMMIT = "209ecd5a91cc433d3514e9e9c929ec40aae1e4c2"

SPLITS = {
    "train": (9_000_000, 192),
    "validation": (9_000_192, 48),
    "power-calibration": (9_000_240, 64),
}
PLY_CAP = 150
TAU = 1.0


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def build_run_contract(binary_sha: str) -> dict[str, Any]:
    return {
        "format": "effective-splendor-m41a-run-contract",
        "version": 1,
        "design_sha": DESIGN_SHA,
        "executor_commit": EXECUTOR_COMMIT,
        "rust_binary_sha256": binary_sha,
        "model_id": "M25-D2-v2",
        "checkpoint_file_sha256": sha256_file(D2),
        "checkpoint_semantic_sha256": None,  # filled from the live server ready file
        "catalog_hash": None,  # filled from the live server ready file
        "m41a_server_sha256": sha256_file(M17 / "splendor_gpu/m41a_server.py"),
        "m41a_proxy_agent_sha256": sha256_file(M17 / "m41a_proxy_agent.py"),
        "inference_mode": "resident_server_v1",
        "continuation": "M25-D2-v2 / M25-D2-v2",
        "device": "cuda",
        "ply_cap": PLY_CAP,
        "state_rule": "25/50/75 quantiles of the selected seat's acting decisions",
        "selected_seat_rule": "global ordinal mod 2",
        "tau": TAU,
        "splits": {
            name: {"seed_start": start, "games": count}
            for name, (start, count) in SPLITS.items()
        },
        "formal_reserve": {
            "seed_start": 9_000_304,
            "games_max": 512,
            "generated_in_p2": False,
        },
        "branch_manifest_format": "effective-splendor-m41a-branch-state-manifest",
        "branch_manifest_version": 2,
    }


def agent_proxy(url: str, ready: Path, sha: str) -> dict[str, Any]:
    return {
        "program": sys.executable,
        "args": [str(M17 / "m41a_proxy_agent.py"),
                 "--server-url", url, "--server-ready", str(ready),
                 "--checkpoint-sha256", sha],
    }


def start_server(ready: Path) -> subprocess.Popen:
    sha = sha256_file(D2)
    if ready.exists():
        ready.unlink()
    proc = subprocess.Popen(
        [sys.executable, "-m", "splendor_gpu.m41a_server",
         "--checkpoint-sha256", sha, "--catalog", str(CATALOG),
         "--device", "cuda", "--ready-file", str(ready)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=REPO,
    )
    deadline = time.time() + 180
    while not ready.is_file():
        if proc.poll() is not None:
            raise RuntimeError("server died: " + proc.stderr.read()[:300])
        if time.time() > deadline:
            raise RuntimeError("server startup timeout")
        time.sleep(0.2)
    return proc


def select_states(replay: dict, ordinal: int) -> list[int]:
    seat = ordinal % 2
    steps = replay["steps"]
    plies = [s["ply"] for s in steps if s["actor"] == seat]
    n = len(plies)
    idxs = sorted({min(n - 1, int(round(q * (n - 1)))) for q in (0.25, 0.5, 0.75)})
    return [plies[i] for i in idxs][:3]


def main() -> None:
    parser = argparse.ArgumentParser(description="M41A P2 corpus driver")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    root: Path = args.root
    root.mkdir(parents=True, exist_ok=True)

    binary_sha = sha256_file(SPLN)
    contract_path = root / "run-contract.json"
    contract_sha: str | None = None

    # --- Run contract: create once / verify on resume ---
    if contract_path.is_file():
        existing = json.loads(contract_path.read_text(encoding="utf-8"))
        # identity of everything EXCEPT the server-derived fields must
        # already match; the server-derived fields are filled below and
        # then the full contract SHA is the binding identity.
        for field in ("design_sha", "executor_commit", "rust_binary_sha256",
                      "checkpoint_file_sha256", "m41a_server_sha256",
                      "m41a_proxy_agent_sha256", "ply_cap", "tau"):
            if existing.get(field) != build_run_contract(binary_sha)[field]:
                raise RuntimeError(
                    f"existing run-contract differs on {field}; stale corpus "
                    "root must be cleared deliberately"
                )
    started = time.perf_counter()

    # --- Source generation (all splits) ---
    source_dirs: dict[str, list[Path]] = {}
    for split, (seed_start, count) in SPLITS.items():
        dirs = []
        for i in range(count):
            ordinal = seed_start - 9_000_000 + i
            gdir = root / split / f"game-{ordinal:04d}"
            report = gdir / "arena-report.json"
            if not report.is_file():
                cfg = gdir / "source-config.json"
                agents = [
                    {"program": sys.executable,
                     "args": ["-m", "splendor_gpu.m35a_agent",
                              "--model-id", "M25-D2-v2",
                              "--catalog", str(CATALOG), "--device", args.device]},
                ] * 2
                write_json(cfg, {
                    "game_id": f"m41a-source-{ordinal:04d}",
                    "seed": seed_start + i,
                    "handshake_timeout_ms": 10_000, "move_timeout_ms": 60_000,
                    "shutdown_grace_ms": 2_000, "agents": agents,
                })
                out = subprocess.run(
                    [str(SPLN), "run-rollout", "--max-plies", str(PLY_CAP),
                     "--config", str(cfg), "--report-out", str(report),
                     "--replay-out", str(gdir / "replay.json"),
                     "--prefix-out", str(gdir / "rollout-prefix.json")],
                    capture_output=True, text=True, timeout=3600, check=False,
                )
                if out.returncode != 0:
                    raise RuntimeError(f"source {ordinal} rc={out.returncode}: {out.stderr[:300]}")
            dirs.append(gdir)
        source_dirs[split] = dirs
    print(json.dumps({"phase": "sources-complete"}), flush=True)

    # --- Resident server + contract finalization ---
    ready = root / "server-ready.json"
    server = start_server(ready)
    try:
        doc = json.loads(ready.read_text(encoding="utf-8"))
        url = f"{doc['host']}:{doc['port']}"
        contract = build_run_contract(binary_sha)
        contract["checkpoint_semantic_sha256"] = doc["checkpoint_semantic_sha256"]
        contract["catalog_hash"] = doc["catalog_hash"]
        if contract_path.is_file():
            existing = json.loads(contract_path.read_text(encoding="utf-8"))
            if existing != contract:
                raise RuntimeError("existing run-contract differs from the rebuilt one")
            contract_sha = sha256_file(contract_path)
        else:
            write_json(contract_path, contract)
            contract_sha = sha256_file(contract_path)

        config = root / "branch-config.json"
        write_json(config, {
            "game_id": "m41a-p2-branches", "seed": 0,
            "handshake_timeout_ms": 10_000, "move_timeout_ms": 60_000,
            "shutdown_grace_ms": 2_000,
            "agents": [agent_proxy(url, ready, sha256_file(D2))] * 2,
        })

        # --- Exhaustive branching per split ---
        for split, dirs in source_dirs.items():
            for gdir in dirs:
                ordinal = int(gdir.name.split("-")[1])
                replay = json.loads((gdir / "replay.json").read_text(encoding="utf-8"))
                for ply in select_states(replay, ordinal):
                    sdir = gdir / f"branch-ply{ply:04d}"
                    if sdir.exists() and not (sdir / "state-manifest.json").is_file():
                        # Interrupted before the manifest was written (at
                        # most a probe exists — it carries only identity
                        # fields recomputed by the next run). Discard and
                        # restart the state fresh.
                        import shutil

                        shutil.rmtree(sdir)
                    # --resume only for an already-started state (a state
                    # dir with a manifest); fresh states run WITHOUT it.
                    cmd = [
                        str(SPLN), "run-branches",
                        "--source-replay", str(gdir / "replay.json"),
                        "--branch-ply", str(ply),
                        "--config", str(config),
                        "--ply-cap", str(PLY_CAP),
                        "--out-dir", str(sdir),
                        "--run-contract", str(contract_path),
                    ]
                    if (sdir / "state-manifest.json").is_file():
                        cmd.append("--resume")
                    out = subprocess.run(cmd, capture_output=True, text=True,
                                         timeout=3600, check=False)
                    if out.returncode != 0:
                        raise RuntimeError(
                            f"run-branches {ordinal}@{ply} rc={out.returncode}: {out.stderr[:300]}"
                        )
                print(json.dumps({"phase": "branching", "split": split,
                                  "game": ordinal, "status": "ok"}), flush=True)
    finally:
        server.terminate()
        server.wait(timeout=15)

    # --- Split-level manifests + power-calibration SEALED proof ---
    elapsed = time.perf_counter() - started
    summaries = {}
    for split, dirs in source_dirs.items():
        games = 0
        states = 0
        branches = 0
        truncated = 0
        manifest_hashes = []
        for gdir in dirs:
            replay = json.loads((gdir / "replay.json").read_text(encoding="utf-8"))
            ordinal = int(gdir.name.split("-")[1])
            games += 1
            for ply in select_states(replay, ordinal):
                sdir = gdir / f"branch-ply{ply:04d}"
                m = json.loads((sdir / "state-manifest.json").read_text(encoding="utf-8"))
                if m.get("run_contract_sha256") != contract_sha:
                    raise RuntimeError(f"{sdir}: manifest contract SHA mismatch")
                states += 1
                branches += len(m["actions"])
                truncated += sum(1 for a in m["actions"] if a["truncated"])
                manifest_hashes.append(sha256_file(sdir / "state-manifest.json"))
        split_manifest = {
            "format": "effective-splendor-m41a-split-manifest",
            "version": 1,
            "split": split,
            "games": games,
            "states": states,
            "branches": branches,
            "truncated_branches": truncated,
            "run_contract_sha256": contract_sha,
            "state_manifest_sha256": hashlib.sha256(
                json.dumps(manifest_hashes, separators=(",", ":")).encode()
            ).hexdigest(),
            "sealed": split == "power-calibration",
        }
        sp = root / split / "split-manifest.json"
        if sp.exists():
            sp.unlink()
        write_json(sp, split_manifest)
        summaries[split] = split_manifest

    # power-calibration sealed proof: a marker file whose existence IS the
    # seal; the trainer's allowlist checks it and refuses if present.
    seal = root / "power-calibration" / "SEALED.json"
    if not seal.exists():
        write_json(seal, {
            "format": "effective-splendor-m41a-power-calibration-seal",
            "version": 1,
            "sealed_at_split_manifest_sha256": summaries["power-calibration"]["state_manifest_sha256"],
            "note": "power-calibration labels must not be read by the trainer "
                    "until F and U final checkpoints are sealed (design §8/§9.6)",
        })

    print(json.dumps({
        "status": "p2-corpus-complete",
        "run_contract_sha256": contract_sha,
        "splits": {s: {k: v for k, v in m.items() if k != "state_manifest_sha256"}
                   for s, m in summaries.items()},
        "elapsed_seconds": round(elapsed, 1),
    }, indent=2), flush=True)


if __name__ == "__main__":
    main()
