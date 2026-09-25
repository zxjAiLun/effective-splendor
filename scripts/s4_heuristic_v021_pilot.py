#!/usr/bin/env python3
"""Config-driven S4 heuristic pilot runner (used for the v0.2.1 development
round). Fail-closed: an invalid/incomplete game stops the run rather than being
filtered or retried. Never writes to the League or the human-game database.

The candidate always runs from the freshly built release binary. An opponent
may pin its own `program` (e.g. the frozen v0.2.0 binary) so a head-to-head
isolates a single behavioral change; its `program_sha256` is enforced.

Usage: s4_heuristic_v021_pilot.py --config <path> --mode {smoke,pilot}
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
SOURCE_EXE = ROOT / "target/release/splendor.exe"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_new(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def require(cond: bool, msg: str) -> None:
    if not cond:
        raise RuntimeError(msg)


def game_seeds(config: dict) -> list[int]:
    return list(range(config["seed_start"], config["seed_start"] + config["seed_count"]))


def check_contract(config: dict) -> None:
    require(config["seed_count"] == 32, "expected 32 seed blocks")
    require(config["smoke_seed"] == config["seed_start"] - 1, "smoke seed must precede the block")
    require(config["rotations"] == [0, 1], "both seat rotations required")
    require(config["candidate"]["agent_version"] == "0.2.1", "candidate must be v0.2.1")
    require(len(config["opponents"]) >= 1, "need at least one opponent")
    require(config["bootstrap"]["ci_percent"] == 95, "95% CI expected")


def verify_fresh_seeds(config: dict, out: Path) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    import s0_seed_registry as registry
    wanted = set(range(config["smoke_seed"], config["seed_start"] + config["seed_count"]))
    for start, end, label in registry.REGISTRY:
        if any(start <= seed <= end for seed in wanted):
            raise RuntimeError(f"pilot seeds collide with registry: {label}")
    found = []
    for parent, _, names in os.walk(ROOT / "local-artifacts"):
        path = Path(parent)
        if path == out or out in path.parents:
            continue
        if "match-config.json" in names:
            try:
                seed = read_json(path / "match-config.json").get("seed")
            except (ValueError, OSError):
                continue
            if seed in wanted:
                found.append(str((path / "match-config.json").relative_to(ROOT)))
    if found:
        raise RuntimeError(f"pilot seeds already in local Arena configs: {found[:5]}")
    print("seed registry + existing local match configs: DISJOINT", flush=True)


def pin_candidate(out: Path) -> tuple[Path, str]:
    if not SOURCE_EXE.is_file():
        raise RuntimeError("missing release binary; build it before launch")
    out.mkdir(parents=True, exist_ok=True)
    pinned = out / "splendor-candidate.exe"
    if not pinned.exists():
        shutil.copyfile(SOURCE_EXE, pinned)
    elif sha256(SOURCE_EXE) != sha256(pinned) and not (out / "smoke-complete.json").exists():
        raise RuntimeError("source binary changed during preflight")
    digest = sha256(pinned)
    marker = out / "binary-identity.json"
    if marker.exists():
        require(read_json(marker)["sha256"] == digest, "pinned candidate binary drift")
    else:
        write_new(marker, {"sha256": digest, "source": "target/release/splendor.exe"})
    return pinned, digest


def opponent_program(config: dict, opponent: dict, candidate_exe: Path) -> Path:
    program = opponent.get("program")
    if program is None:
        return candidate_exe
    path = ROOT / program
    if not path.is_file():
        raise RuntimeError(f"opponent program missing: {program}")
    expected = opponent.get("program_sha256")
    if expected and sha256(path) != expected:
        raise RuntimeError(f"opponent program hash mismatch: {program}")
    return path


def run_one(config: dict, opponent: dict, seed: int, rotation: int, subdir: str,
            candidate_exe: Path, candidate_hash: str, out: Path) -> dict:
    if sha256(candidate_exe) != candidate_hash:
        raise RuntimeError("pinned candidate changed before match")
    opp_exe = opponent_program(config, opponent, candidate_exe)
    match_dir = out / subdir / opponent["id"] / f"seed-{seed}" / f"r{rotation}"
    if match_dir.exists():
        raise RuntimeError(f"create-only match directory already exists: {match_dir}")
    match_dir.mkdir(parents=True)
    candidate = config["candidate"]
    cand_prog = {"program": str(candidate_exe), "args": candidate["args"], "_spec": candidate}
    opp_prog = {"program": str(opp_exe), "args": opponent["args"], "_spec": opponent}
    slots = [cand_prog, opp_prog] if rotation == 0 else [opp_prog, cand_prog]
    game_id = f"s4v021-{opponent['id']}-{seed}-r{rotation}"
    match_config = {
        "game_id": game_id,
        "seed": seed,
        "handshake_timeout_ms": config["handshake_timeout_ms"],
        "move_timeout_ms": config["move_timeout_ms"],
        "shutdown_grace_ms": config["shutdown_grace_ms"],
        "agents": [{"program": s["program"], "args": s["args"]} for s in slots],
    }
    cfg = match_dir / "match-config.json"
    report = match_dir / "arena-report.json"
    replay = match_dir / "match-replay.json"
    write_new(cfg, match_config)
    started = time.monotonic()
    proc = subprocess.run(
        [str(candidate_exe), "run-match", "--config", str(cfg), "--report-out",
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
    for seat, slot in enumerate(slots):
        actual = rep["agents"][seat]
        spec = slot["_spec"]
        if (actual["agent_name"], actual["agent_version"]) != (
            spec["agent_name"], spec["agent_version"]
        ):
            raise RuntimeError(f"{game_id}: agent identity mismatch at seat {seat}: {actual}")
    check = subprocess.run([str(candidate_exe), "verify-replay", "--input", str(replay)],
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


def percentile(samples: list[float], p: float) -> float:
    rank = (len(samples) - 1) * p
    low = int(rank)
    frac = rank - low
    return samples[low] * (1.0 - frac) + samples[min(low + 1, len(samples) - 1)] * frac


def summarize(rows: list[dict], opponent_id: str, config: dict) -> dict:
    matches = [r for r in rows if r["opponent"] == opponent_id]
    blocks = []
    for seed in game_seeds(config):
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
    return {"opponent": opponent_id, "matches": len(matches), "wins": wins, "ties": ties,
            "losses": len(matches) - wins - ties, "center_bps": sum(blocks) / len(blocks),
            "ci_95_bps": ci, "exploratory_verdict": verdict,
            "mean_plies": sum(r["completed_plies"] for r in matches) / len(matches),
            "total_match_wall_seconds": round(sum(r["match_wall_seconds"] for r in matches), 3)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--mode", required=True, choices=("smoke", "pilot"))
    args = parser.parse_args()
    config_path = ROOT / args.config if not Path(args.config).is_absolute() else Path(args.config)
    config = read_json(config_path)
    check_contract(config)
    out = ROOT / config["artifacts"]
    result_path = config_path.with_name(config_path.name.replace(".config.json", ".result.json"))
    if args.mode == "smoke":
        verify_fresh_seeds(config, out)
    elif not (out / "smoke-complete.json").is_file():
        raise RuntimeError("pilot requires the complete smoke")
    candidate_exe, digest = pin_candidate(out)
    smoke = args.mode == "smoke"
    if not smoke:
        prior = read_json(out / "smoke-complete.json")
        if prior["config_sha256"] != sha256(config_path) or prior["binary_sha256"] != digest:
            raise RuntimeError("smoke identity differs from pilot")
        if {row["rotation"] for row in prior["rows"]} != {0, 1}:
            raise RuntimeError("smoke must include both verified seat rotations")
    opponents = config["opponents"][:1] if smoke else config["opponents"]
    seeds = [config["smoke_seed"]] if smoke else game_seeds(config)
    rows = []
    for opponent in opponents:
        for seed in seeds:
            for rotation in config["rotations"]:
                row = run_one(config, opponent, seed, rotation, "smoke" if smoke else "games",
                              candidate_exe, digest, out)
                rows.append(row)
                print(f"{row['game_id']} seat{row['candidate_seat']} "
                      f"{row['score_bps']}/10000 verified {row['match_wall_seconds']}s", flush=True)
    if smoke:
        write_new(out / "smoke-complete.json",
                  {"config_sha256": sha256(config_path), "binary_sha256": digest, "rows": rows})
        return
    manifest = out / "manifest.json"
    write_new(manifest, {"config_sha256": sha256(config_path), "binary_sha256": digest, "rows": rows})
    summaries = [summarize(rows, o["id"], config) for o in opponents]
    result = {
        "format": "effective-splendor-s4-heuristic-v021-pilot-result",
        "version": 1, "status": "EXPLORATORY_PILOT_ONLY",
        "contract": str(config_path.relative_to(ROOT)).replace("\\", "/"),
        "config_sha256": sha256(config_path), "candidate_binary_sha256": digest,
        "manifest": str(manifest.relative_to(ROOT)).replace("\\", "/"),
        "manifest_sha256": sha256(manifest),
        "matched_game_seeds": config["seed_count"],
        "completed_and_verified_matches": len(rows), "aborts": 0,
        "pairings": summaries,
        "limitations": "95% paired-block CIs on 32 fresh seeds per opponent; no promotion, no default change; the v0.2.0 opponent runs from its frozen binary so that head-to-head isolates the phase-aware change; game-wall is not per-decision latency",
    }
    write_new(result_path, result)
    print(json.dumps({"pairings": summaries}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"STOP: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
