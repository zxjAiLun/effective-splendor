#!/usr/bin/env python3
"""Prospective, create-only S4 v0.2.8 pilot: freeze -> smoke -> pilot.

All opponents AND referee/verify use the immutable v025 executable. Only the
candidate uses the newly built/pinned v028 executable. No resume, retries,
filtering, optional stopping, League writes, or human data. Python -O safe.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = "benchmarks/s4-heuristic-v028-pilot-v1.config.json"
SEED_START, SEED_COUNT, SMOKE_SEED = 9_258_000, 128, 9_257_999
REGISTRY_ENTRY = (SMOKE_SEED, SEED_START + SEED_COUNT - 1, "s4-v028-pilot-smoke-and-matches")
REFERENCE_SHA = "898dba3662ee20acee0616db9164a3f89cb1143834819ff98a0a093deb35e937"
FROZEN_SOURCES = (
    "crates/splendor-agent/src/heuristic_v02.rs",
    "scripts/s4_heuristic_v028_pilot.py",
    "scripts/s4_heuristic_v028_audit.py",
    "scripts/tests/test_s4_v028_pilot.py",
)
EXPECTED_CONFIG = {
    "format": "effective-splendor-s4-heuristic-v028-pilot-config", "version": 1,
    "status": "prospective-exploratory-pilot",
    "design_doc": "docs/s4-heuristic-v02-design.md#s48-v028-stateless-valuation-calibration-single-noble-activation--quadratic-vp-efficiency",
    "seed_start": SEED_START, "seed_count": SEED_COUNT, "smoke_seed": SMOKE_SEED,
    "rotations": [0, 1],
    "candidate": {"id": "heuristic-v028", "args": ["agent-heuristic-v02", "--seed", "20260926"],
                  "agent_name": "splendor-cli-heuristic-v02", "agent_version": "0.2.8"},
    "reference_program": "local-artifacts/s4-heuristic-v025-pilot/splendor-candidate.exe",
    "reference_sha256": REFERENCE_SHA,
    "opponents": [
        {"id": "heuristic-v025", "args": ["agent-heuristic-v02", "--seed", "20260926"],
         "agent_name": "splendor-cli-heuristic-v02", "agent_version": "0.2.5"},
        {"id": "heuristic-v01", "args": ["agent-heuristic", "--seed", "20260812"],
         "agent_name": "splendor-cli-heuristic", "agent_version": "0.1.0"},
        {"id": "s3-rollout", "args": ["agent-s3-rollout"],
         "agent_name": "effective-splendor-s3-rollout-v1", "agent_version": "1"},
    ],
    "handshake_timeout_ms": 10_000, "move_timeout_ms": 60_000, "shutdown_grace_ms": 2_000,
    "bootstrap": {"resamples": 10_000, "seed": 92_582_026, "ci_percent": 95},
    "inference": "128 paired-seed blocks per opponent; stateless valuation calibration with single noble activation and quadratic VP efficiency; exploratory only; no promotion or default change",
    "artifacts": "local-artifacts/s4-heuristic-v028-pilot",
}


def require(cond: bool, message: str) -> None:
    if not cond:
        raise RuntimeError(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_new(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def check_contract(config: dict) -> None:
    require(config == EXPECTED_CONFIG, "v028 frozen contract mismatch (including identities, schedule, paths, and bootstrap)")


def check_registry(ranges: list[tuple[int, int, str]]) -> None:
    require(ranges.count(REGISTRY_ENTRY) == 1, "expected exactly one v028 reserved range")
    for a, b in itertools.combinations(ranges, 2):
        require(max(a[0], b[0]) > min(a[1], b[1]), f"overlapping registry entries: {a}, {b}")
    for entry in ranges:
        if entry == REGISTRY_ENTRY:
            continue
        require(max(SMOKE_SEED, entry[0]) > min(SEED_START + SEED_COUNT - 1, entry[1]),
                f"pilot overlaps prior range: {entry}")


def fresh_seeds(root: Path) -> dict:
    sys.path.insert(0, str(ROOT / "scripts"))
    import s0_seed_registry
    check_registry(s0_seed_registry.REGISTRY)
    count = 0
    for parent, dirs, names in os.walk(root / "local-artifacts"):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", ".uv-cache", "site-packages", "__pycache__")]
        if "match-config.json" not in names:
            continue
        path = Path(parent) / "match-config.json"
        config = read_json(path)
        count += 1
        seed = config.get("seed")
        require(isinstance(seed, int), f"missing/noninteger seed in {path}")
        require(not SMOKE_SEED <= seed < SEED_START + SEED_COUNT, f"seed already used in {path}")
    for path in (root / "benchmarks").glob("*.config.json"):
        if path.name == Path(DEFAULT_CONFIG).name:
            continue
        c = read_json(path)
        seeds = c.get("game_seeds", [])
        if isinstance(seeds, list):
            require(not any(isinstance(s, int) and SMOKE_SEED <= s < SEED_START + SEED_COUNT for s in seeds), f"tracked seeds collide: {path}")
        if isinstance(c.get("seed_start"), int) and isinstance(c.get("seed_count"), int):
            require(max(SMOKE_SEED, c["seed_start"]) > min(SEED_START + SEED_COUNT - 1, c["seed_start"] + c["seed_count"] - 1), f"tracked range collides: {path}")
        require(c.get("smoke_seed") is None or not SMOKE_SEED <= c["smoke_seed"] < SEED_START + SEED_COUNT, f"tracked smoke collides: {path}")
    return {"status": "PASS", "match_configs_scanned": count, "reserved_range": REGISTRY_ENTRY}


def freeze(config_path: Path, config: dict, out: Path) -> None:
    require(not out.exists(), "freeze output exists; no overwrite/resume")
    reference = ROOT / config["reference_program"]
    require(sha256(reference) == REFERENCE_SHA, "frozen v025 reference drift")
    seed_check = fresh_seeds(ROOT)
    source_hashes = {p: sha256(ROOT / p) for p in FROZEN_SOURCES}
    source_exe = ROOT / "target/release/splendor.exe"
    candidate_hash = sha256(source_exe)
    require(candidate_hash != REFERENCE_SHA, "candidate is still the v025 binary")
    out.mkdir(parents=True)
    candidate = out / "splendor-candidate.exe"
    with candidate.open("xb") as handle:
        handle.write(source_exe.read_bytes())
    require(sha256(candidate) == candidate_hash == sha256(source_exe), "candidate changed during pinning")
    write_new(out / "freeze.json", {
        "format": "s4-v028-freeze-v1", "config_sha256": sha256(config_path),
        "candidate_binary_sha256": candidate_hash, "reference_binary_sha256": REFERENCE_SHA,
        "candidate_source": "target/release/splendor.exe", "sources": source_hashes,
        "head_at_freeze": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "seed_preflight": seed_check,
    })
    print(f"FROZEN: candidate={candidate_hash}; reference={REFERENCE_SHA}; {seed_check}", flush=True)


def verify_freeze(config_path: Path, config: dict, out: Path) -> dict:
    frozen = read_json(out / "freeze.json")
    require(frozen["config_sha256"] == sha256(config_path), "config drift after freeze")
    require(frozen["candidate_binary_sha256"] == sha256(out / "splendor-candidate.exe"), "candidate drift")
    require(frozen["reference_binary_sha256"] == REFERENCE_SHA == sha256(ROOT / config["reference_program"]), "reference drift")
    require(set(frozen["sources"]) == set(FROZEN_SOURCES), "freeze source coverage mismatch")
    for path, expected in frozen["sources"].items():
        require(sha256(ROOT / path) == expected, f"source/runner drift after freeze: {path}")
    return frozen


def validate_winners(winners: list[int], seat: int) -> int:
    require(isinstance(winners, list) and winners in ([0], [1], [0, 1]), f"invalid two-player winners: {winners}")
    return 5_000 if winners == [0, 1] else 10_000 if winners == [seat] else 0


def validate_artifacts(report: dict, replay: dict, game_id: str, seed: int, specs: list[dict]) -> None:
    require(report["game_id"] == game_id, "report game ID mismatch")
    require(report["outcome"]["status"] == "completed", "incomplete/aborted game")
    require(report["player_count"] == replay["player_count"] == 2 and replay["seed"] == seed, "wrong seed/player count")
    require([a["seat"] for a in report["agents"]] == [0, 1], "bad seat mapping")
    for actual, spec in zip(report["agents"], specs):
        require((actual["agent_name"], actual["agent_version"]) == (spec["agent_name"], spec["agent_version"]), "agent identity mismatch")
    outcome = report["outcome"]
    require(outcome["result"] == replay["result"], "report/replay result disagreement")
    require(outcome["completed_plies"] == len(replay["steps"]), "ply count mismatch")
    require(outcome["replay_final_hash"] == replay["final_state_hash"], "final-state hash mismatch")
    validate_winners(outcome["result"]["winners"], 0)


def execute_game(config: dict, opponent: dict, seed: int, seat: int, subdir: str,
                 out: Path, frozen: dict) -> dict:
    candidate = out / "splendor-candidate.exe"
    reference = ROOT / config["reference_program"]
    require(sha256(candidate) == frozen["candidate_binary_sha256"] and sha256(reference) == REFERENCE_SHA, "executable drift before match")
    directory = out / subdir / opponent["id"] / f"seed-{seed}" / f"r{seat}"
    directory.mkdir(parents=True, exist_ok=False)
    game_id = f"s4v028-{opponent['id']}-{seed}-r{seat}"
    commands = [{"program": str(candidate), "args": config["candidate"]["args"]},
                {"program": str(reference), "args": opponent["args"]}]
    specs = [config["candidate"], opponent]
    if seat:
        commands.reverse()
        specs.reverse()
    match_config = {"game_id": game_id, "seed": seed, "agents": commands,
                    **{k: config[k] for k in ("handshake_timeout_ms", "move_timeout_ms", "shutdown_grace_ms")}}
    cfg, report_path, replay_path = [directory / name for name in ("match-config.json", "arena-report.json", "match-replay.json")]
    write_new(cfg, match_config)
    started = time.monotonic()
    proc = subprocess.run([str(reference), "run-match", "--config", str(cfg), "--report-out", str(report_path), "--replay-out", str(replay_path)],
                          capture_output=True, text=True, timeout=300)
    wall = time.monotonic() - started
    write_new(directory / "process.json", {"exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr})
    require(proc.returncode == 0 and not proc.stderr.strip(), f"{game_id}: run-match failed exit={proc.returncode}; {proc.stderr[:400]}")
    report, replay = read_json(report_path), read_json(replay_path)
    validate_artifacts(report, replay, game_id, seed, specs)
    verification = subprocess.run([str(reference), "verify-replay", "--input", str(replay_path)], capture_output=True, text=True, timeout=30)
    write_new(directory / "verification.json", {"exit_code": verification.returncode, "stdout": verification.stdout, "stderr": verification.stderr})
    require(verification.returncode == 0 and not verification.stderr.strip(), f"{game_id}: verify-replay failed")
    winners = report["outcome"]["result"]["winners"]
    return {"game_id": game_id, "opponent": opponent["id"], "seed": seed, "rotation": seat,
            "candidate_seat": seat, "score_bps": validate_winners(winners, seat), "winners": winners,
            "completed_plies": report["outcome"]["completed_plies"], "replay_final_hash": replay["final_state_hash"],
            "match_wall_seconds": round(wall, 6), "config_sha256": sha256(cfg),
            "report_sha256": sha256(report_path), "replay_sha256": sha256(replay_path)}


def percentile(samples: list[float], fraction: float) -> float:
    position = (len(samples) - 1) * fraction
    low = int(position)
    return samples[low] * (1 - (position - low)) + samples[min(low + 1, len(samples) - 1)] * (position - low)


def summarize(rows: list[dict], opponent: str, config: dict) -> dict:
    matches = [r for r in rows if r["opponent"] == opponent]
    expected = {(s, seat) for s in range(config["seed_start"], config["seed_start"] + config["seed_count"]) for seat in (0, 1)}
    require(len(matches) == len(expected) and {(r["seed"], r["rotation"]) for r in matches} == expected, "missing/duplicate paired block")
    lookup = {(r["seed"], r["rotation"]): r for r in matches}
    blocks = [(lookup[(s, 0)]["score_bps"] + lookup[(s, 1)]["score_bps"]) / 2 for s in range(config["seed_start"], config["seed_start"] + config["seed_count"])]
    rng = random.Random(config["bootstrap"]["seed"])
    samples = sorted(sum(blocks[rng.randrange(len(blocks))] for _ in blocks) / len(blocks) for _ in range(config["bootstrap"]["resamples"]))
    ci = [percentile(samples, .025), percentile(samples, .975)]
    wins = sum(r["score_bps"] == 10_000 for r in matches)
    ties = sum(r["score_bps"] == 5_000 for r in matches)
    return {"opponent": opponent, "matches": len(matches), "wins": wins, "ties": ties,
            "losses": len(matches) - wins - ties, "center_bps": sum(blocks) / len(blocks), "ci_95_bps": ci,
            "exploratory_verdict": "EXPLORATORY_STRONGER" if ci[0] > 5_000 else "EXPLORATORY_WEAKER" if ci[1] < 5_000 else "UNRESOLVED",
            "mean_plies": sum(r["completed_plies"] for r in matches) / len(matches),
            "total_match_wall_seconds": round(sum(r["match_wall_seconds"] for r in matches), 6)}


def check_smoke(smoke: dict, config_path: Path, frozen: dict, out: Path) -> None:
    require(smoke["config_sha256"] == sha256(config_path) and smoke["binary_sha256"] == frozen["candidate_binary_sha256"], "smoke identity drift")
    require(smoke["freeze_sha256"] == sha256(out / "freeze.json"), "smoke freeze drift")
    rows = smoke["rows"]
    require(len(rows) == 2 and {(r["opponent"], r["seed"], r["rotation"]) for r in rows} == {("heuristic-v025", SMOKE_SEED, 0), ("heuristic-v025", SMOKE_SEED, 1)}, "smoke must contain exactly the two planned games")
    for row in rows:
        directory = out / "smoke" / row["opponent"] / f"seed-{row['seed']}" / f"r{row['rotation']}"
        for filename, key in [("match-config.json", "config_sha256"), ("arena-report.json", "report_sha256"), ("match-replay.json", "replay_sha256")]:
            require(sha256(directory / filename) == row[key], f"smoke {filename} drift")


def run(config_path: Path, mode: str) -> None:
    config = read_json(config_path)
    check_contract(config)
    out = ROOT / config["artifacts"]
    if mode == "freeze":
        freeze(config_path, config, out)
        return
    frozen = verify_freeze(config_path, config, out)
    result_path = config_path.with_name(config_path.name.replace(".config.json", ".result.json"))
    require(not (out / f"{mode}-failure.json").exists(), "prior failure: no retry authorized")
    if mode == "smoke":
        fresh_seeds(ROOT)
    else:
        require(not result_path.exists(), "result already exists")
        check_smoke(read_json(out / "smoke-complete.json"), config_path, frozen, out)
    write_new(out / f"{mode}-start.json", {"freeze_sha256": sha256(out / "freeze.json"), "mode": mode})
    opponents = config["opponents"][:1] if mode == "smoke" else config["opponents"]
    seeds = [SMOKE_SEED] if mode == "smoke" else range(SEED_START, SEED_START + SEED_COUNT)
    rows = []
    try:
        with (out / f"{mode}-rows.jsonl").open("x", encoding="utf-8", newline="\n") as journal:
            for opponent in opponents:
                for seed in seeds:
                    for seat in config["rotations"]:
                        row = execute_game(config, opponent, seed, seat, "smoke" if mode == "smoke" else "games", out, frozen)
                        rows.append(row)
                        journal.write(json.dumps(row) + "\n")
                        journal.flush()
                        print(f"{len(rows)} {row['game_id']} verified score={row['score_bps']}", flush=True)
        verify_freeze(config_path, config, out)
        common = {"config_sha256": sha256(config_path), "binary_sha256": frozen["candidate_binary_sha256"],
                  "reference_sha256": REFERENCE_SHA, "freeze_sha256": sha256(out / "freeze.json"), "rows": rows}
        if mode == "smoke":
            require(len(rows) == 2, "smoke incomplete")
            write_new(out / "smoke-complete.json", common)
            return
        require(len(rows) == 768, "pilot not complete")
        summaries = [summarize(rows, o["id"], config) for o in config["opponents"]]
        manifest = out / "manifest.json"
        write_new(manifest, common)
        result = {"format": "effective-splendor-s4-heuristic-v028-pilot-result", "version": 1,
                  "status": "EXPLORATORY_PILOT_ONLY", "contract": str(config_path.relative_to(ROOT)).replace("\\", "/"),
                  "config_sha256": sha256(config_path), "candidate_binary_sha256": frozen["candidate_binary_sha256"],
                  "reference_binary_sha256": REFERENCE_SHA, "freeze_sha256": sha256(out / "freeze.json"),
                  "manifest": str(manifest.relative_to(ROOT)).replace("\\", "/"), "manifest_sha256": sha256(manifest),
                  "matched_game_seeds": SEED_COUNT, "completed_and_verified_matches": len(rows), "aborts": 0,
                  "pairings": summaries,
                  "limitations": "128 seed blocks per opponent; stateless valuation calibration with single noble activation and quadratic VP efficiency; marginal exploratory CIs, not a promotion or equivalence test; game-wall is not per-decision latency"}
        write_new(result_path, result)
        print(json.dumps({"pairings": summaries}), flush=True)
    except BaseException as exc:
        write_new(out / f"{mode}-failure.json", {"status": "STOP", "completed_rows": len(rows), "error": repr(exc), "no_retry": True})
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--mode", required=True, choices=("freeze", "smoke", "pilot"))
    args = parser.parse_args()
    path = Path(args.config)
    run(path if path.is_absolute() else ROOT / path, args.mode)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"STOP: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
        sys.exit(1)
