#!/usr/bin/env python3
"""Prospective S4 v0.2 exploratory pilot. No League or human-game writes.

Run --mode smoke first, then --mode pilot. Each output is create-only; an
invalid/incomplete game stops the run rather than being filtered or retried.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "benchmarks/s4-heuristic-v02-pilot-v1.config.json"
OUT = ROOT / "local-artifacts/s4-heuristic-v02-pilot"
SOURCE_EXE = ROOT / "target/release/splendor.exe"
PINNED_EXE = OUT / "splendor-s4-v02.exe"
RESULT = ROOT / "benchmarks/s4-heuristic-v02-pilot-v1.result.json"
SEED_START = 9_250_000
SEED_COUNT = 32


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_new(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def check_contract(config: dict) -> None:
    assert config["game_seeds"] == list(range(SEED_START, SEED_START + SEED_COUNT))
    assert config["smoke_seed"] == SEED_START - 1
    assert config["rotations"] == [0, 1]
    assert [o["id"] for o in config["opponents"]] == ["heuristic-v01", "s3-rollout"]
    assert config["candidate"]["args"] == ["agent-heuristic-v02", "--seed", "20260925"]
    assert config["opponents"][0]["args"] == ["agent-heuristic", "--seed", "20260812"]
    assert config["opponents"][1]["args"] == ["agent-s3-rollout"]
    assert config["bootstrap"] == {"resamples": 10000, "seed": 92502026, "ci_percent": 95}
    assert (config["handshake_timeout_ms"], config["move_timeout_ms"],
            config["shutdown_grace_ms"]) == (10000, 60000, 2000)
    assert config["artifacts"] == "local-artifacts/s4-heuristic-v02-pilot"


def verify_fresh_seeds() -> None:
    # The historic registry is not sufficient on its own; check real local
    # Arena match configs too. Never silently choose another segment.
    sys.path.insert(0, str(ROOT / "scripts"))
    import s0_seed_registry as registry
    wanted = set(range(SEED_START - 1, SEED_START + SEED_COUNT))
    for start, end, label in registry.REGISTRY:
        if any(start <= seed <= end for seed in wanted):
            raise RuntimeError(f"pilot seeds collide with registry: {label}")
    found = []
    for parent, _, names in os.walk(ROOT / "local-artifacts"):
        path = Path(parent)
        if path == OUT or OUT in path.parents:
            continue
        if "match-config.json" in names:
            f = path / "match-config.json"
            try:
                seed = read_json(f).get("seed")
            except (ValueError, OSError):
                continue
            if seed in wanted:
                found.append(str(f.relative_to(ROOT)))
    if found:
        raise RuntimeError(f"pilot seeds already in local Arena configs: {found[:5]}")
    print("seed registry + existing local match configs: DISJOINT", flush=True)


def pinned_binary() -> str:
    if not SOURCE_EXE.is_file():
        raise RuntimeError("missing release binary; build it before launch")
    OUT.mkdir(parents=True, exist_ok=True)
    if not PINNED_EXE.exists():
        shutil.copyfile(SOURCE_EXE, PINNED_EXE)
    if sha256(SOURCE_EXE) != sha256(PINNED_EXE):
        # A concurrent release build cannot mutate an already-pinned pilot.
        # In pilot mode SOURCE_EXE may have changed: use the pinned file, but
        # that is only safe if the recorded smoke identity still matches it.
        if not (OUT / "smoke-complete.json").exists():
            raise RuntimeError("source binary changed during preflight")
    digest = sha256(PINNED_EXE)
    marker = OUT / "binary-identity.json"
    if marker.exists():
        if read_json(marker)["sha256"] != digest:
            raise RuntimeError("pinned binary drift")
    else:
        write_new(marker, {"sha256": digest, "source": "target/release/splendor.exe"})
    return digest


def run_one(config: dict, opponent: dict, seed: int, rotation: int, subdir: str,
            expected_binary_hash: str) -> dict:
    if sha256(PINNED_EXE) != expected_binary_hash:
        raise RuntimeError("pinned binary changed before match")
    match_dir = OUT / subdir / opponent["id"] / f"seed-{seed}" / f"r{rotation}"
    if match_dir.exists():
        raise RuntimeError(f"create-only match directory already exists: {match_dir}")
    match_dir.mkdir(parents=True)
    candidate = config["candidate"]
    slots = [candidate, opponent] if rotation == 0 else [opponent, candidate]
    game_id = f"s4-{opponent['id']}-{seed}-r{rotation}"
    match_config = {
        "game_id": game_id,
        "seed": seed,
        "handshake_timeout_ms": config["handshake_timeout_ms"],
        "move_timeout_ms": config["move_timeout_ms"],
        "shutdown_grace_ms": config["shutdown_grace_ms"],
        "agents": [{"program": str(PINNED_EXE), "args": spec["args"]} for spec in slots],
    }
    cfg = match_dir / "match-config.json"
    report = match_dir / "arena-report.json"
    replay = match_dir / "match-replay.json"
    write_new(cfg, match_config)
    started = time.monotonic()
    proc = subprocess.run(
        [str(PINNED_EXE), "run-match", "--config", str(cfg), "--report-out",
         str(report), "--replay-out", str(replay)],
        capture_output=True, text=True, timeout=300,
    )
    elapsed = time.monotonic() - started
    if proc.returncode != 0 or proc.stderr.strip():
        raise RuntimeError(f"{game_id}: run-match exit={proc.returncode}; stderr={proc.stderr[:600]}")
    if not (report.is_file() and replay.is_file()):
        raise RuntimeError(f"{game_id}: report/replay missing")
    rep, rpl = read_json(report), read_json(replay)
    if rep["game_id"] != game_id or rep["outcome"]["status"] != "completed":
        raise RuntimeError(f"{game_id}: wrong game id or incomplete")
    if rep["outcome"]["replay_final_hash"] != rpl["final_state_hash"]:
        raise RuntimeError(f"{game_id}: report/replay final hash mismatch")
    if [a["seat"] for a in rep["agents"]] != [0, 1]:
        raise RuntimeError(f"{game_id}: invalid reported seats")
    for seat, expected in enumerate(slots):
        actual = rep["agents"][seat]
        if (actual["agent_name"], actual["agent_version"]) != (
            expected["agent_name"], expected["agent_version"]
        ):
            raise RuntimeError(f"{game_id}: agent identity mismatch at seat {seat}: {actual}")
    check = subprocess.run([str(PINNED_EXE), "verify-replay", "--input", str(replay)],
                           capture_output=True, text=True, timeout=30)
    if check.returncode != 0:
        raise RuntimeError(f"{game_id}: independent verify-replay failed: {check.stderr[:300]}")
    winners = rep["outcome"]["result"]["winners"]
    candidate_seat = rotation
    score = 10_000 if winners == [candidate_seat] else 5_000 if candidate_seat in winners else 0
    return {"game_id": game_id, "opponent": opponent["id"], "seed": seed,
            "rotation": rotation, "candidate_seat": candidate_seat,
            "score_bps": score, "winners": winners,
            "completed_plies": rep["outcome"]["completed_plies"],
            "replay_final_hash": rpl["final_state_hash"],
            "match_wall_seconds": round(elapsed, 3),
            "config_sha256": sha256(cfg), "report_sha256": sha256(report),
            "replay_sha256": sha256(replay)}


def percentile(sorted_samples: list[float], p: float) -> float:
    rank = (len(sorted_samples) - 1) * p
    low = int(rank)
    weight = rank - low
    return sorted_samples[low] * (1.0 - weight) + sorted_samples[min(low + 1, len(sorted_samples) - 1)] * weight


def summarize(rows: list[dict], opponent_id: str, config: dict) -> dict:
    matches = [r for r in rows if r["opponent"] == opponent_id]
    blocks = []
    for seed in config["game_seeds"]:
        paired = sorted([r for r in matches if r["seed"] == seed], key=lambda r: r["rotation"])
        if len(paired) != 2 or [r["rotation"] for r in paired] != [0, 1]:
            raise RuntimeError(f"invalid block {opponent_id}/{seed}")
        blocks.append((paired[0]["score_bps"] + paired[1]["score_bps"]) / 2)
    rng = random.Random(config["bootstrap"]["seed"])
    trials = sorted(sum(blocks[rng.randrange(len(blocks))] for _ in blocks) / len(blocks)
                    for _ in range(config["bootstrap"]["resamples"]))
    ci = [percentile(trials, .025), percentile(trials, .975)]
    wins = sum(r["score_bps"] == 10000 for r in matches)
    ties = sum(r["score_bps"] == 5000 for r in matches)
    verdict = "EXPLORATORY_STRONGER" if ci[0] > 5000 else (
        "EXPLORATORY_WEAKER" if ci[1] < 5000 else "UNRESOLVED")
    return {"opponent": opponent_id, "matches": len(matches), "wins": wins,
            "ties": ties, "losses": len(matches) - wins - ties,
            "center_bps": sum(blocks) / len(blocks), "ci_95_bps": ci,
            "exploratory_verdict": verdict,
            "mean_plies": sum(r["completed_plies"] for r in matches) / len(matches),
            "total_match_wall_seconds": round(sum(r["match_wall_seconds"] for r in matches), 3)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=("smoke", "pilot"))
    args = parser.parse_args()
    config = read_json(CONFIG_PATH)
    check_contract(config)
    if args.mode == "smoke":
        verify_fresh_seeds()
    elif not (OUT / "smoke-complete.json").is_file():
        raise RuntimeError("pilot requires the complete two-rotation smoke")
    digest = pinned_binary()
    smoke = args.mode == "smoke"
    if not smoke:
        prior = read_json(OUT / "smoke-complete.json")
        if prior["config_sha256"] != sha256(CONFIG_PATH) or prior["binary_sha256"] != digest:
            raise RuntimeError("smoke identity differs from pilot")
        if len(prior["rows"]) != 2 or {row["rotation"] for row in prior["rows"]} != {0, 1}:
            raise RuntimeError("smoke must include both verified seat rotations")
    if smoke:
        opponents = config["opponents"][:1]
        seeds = [config["smoke_seed"]]
    else:
        opponents = config["opponents"]
        seeds = config["game_seeds"]
    rows = []
    for opponent in opponents:
        for seed in seeds:
            for rotation in config["rotations"]:
                row = run_one(config, opponent, seed, rotation, "smoke" if smoke else "games", digest)
                rows.append(row)
                print(f"{row['game_id']} seat{row['candidate_seat']} "
                      f"{row['score_bps']}/10000 verified {row['match_wall_seconds']}s", flush=True)
    if smoke:
        write_new(OUT / "smoke-complete.json", {
            "config_sha256": sha256(CONFIG_PATH), "binary_sha256": digest,
            "rows": rows,
        })
        return
    manifest = OUT / "manifest.json"
    write_new(manifest, {"config_sha256": sha256(CONFIG_PATH), "binary_sha256": digest,
                         "rows": rows})
    summaries = [summarize(rows, o["id"], config) for o in opponents]
    result = {
        "format": "effective-splendor-s4-heuristic-v02-pilot-result",
        "version": 1, "status": "EXPLORATORY_PILOT_ONLY",
        "contract": str(CONFIG_PATH.relative_to(ROOT)).replace("\\", "/"),
        "config_sha256": sha256(CONFIG_PATH), "binary_sha256": digest,
        "manifest": str(manifest.relative_to(ROOT)).replace("\\", "/"),
        "manifest_sha256": sha256(manifest),
        "matched_game_seeds": len(config["game_seeds"]),
        "completed_and_verified_matches": len(rows), "aborts": 0,
        "pairings": summaries,
        "two_opponent_exploratory_signal": all(
            s["exploratory_verdict"] == "EXPLORATORY_STRONGER" for s in summaries),
        "limitations": "95% paired-block CIs on 32 new seeds per opponent; no promotion, no default change; game-wall is not per-decision latency",
    }
    write_new(RESULT, result)
    print(json.dumps({"pairings": summaries, "signal": result["two_opponent_exploratory_signal"]},
                     ensure_ascii=False), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"STOP: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
