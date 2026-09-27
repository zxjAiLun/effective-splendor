#!/usr/bin/env python3
"""Separate post-run S4 v029 audit, deriving scores from raw reports/replays.

No runner imports: schedule, score mapping, pair aggregation and quantiles are
reimplemented. The referee's verify-replay is executed for all smoke/pilot
replays. This is an author's independent computation, NOT an independent code
reviewer or promotion gate. Existing outputs are never overwritten.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "benchmarks/s4-heuristic-v029-pilot-v1.config.json"
RESULT = ROOT / "benchmarks/s4-heuristic-v029-pilot-v1.result.json"
OUT = ROOT / "local-artifacts/s4-heuristic-v029-pilot"
REFERENCE_SHA = "76c154ff0ac32d9c9a1f51c38787b88548743276495ee346a262d9d51affb876"
OPPONENTS = ["heuristic-v028", "heuristic-v01", "s3-rollout"]


def need(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def score(winners: list[int], seat: int) -> int:
    need(isinstance(winners, list) and winners in ([0], [1], [0, 1]), "invalid winners")
    return 5000 if len(winners) == 2 else 10000 if winners[0] == seat else 0


def paired_summary(rows: list[dict], opponent: str) -> dict:
    subset = [r for r in rows if r["opponent"] == opponent]
    need(len(subset) == 256, "need exactly 256 games per opponent")
    mapping = {(r["seed"], r["rotation"]): r for r in subset}
    need(set(mapping) == {(seed, seat) for seed in range(9259000, 9259128) for seat in range(2)}, "missing/duplicate seed-seat pairs")
    means = [(mapping[(s, 0)]["score_bps"] + mapping[(s, 1)]["score_bps"]) / 2.0 for s in range(9259000, 9259128)]
    rng = random.Random(92592026)
    estimates = []
    for _ in range(10000):
        total = 0.0
        for _ in range(128):
            total += means[rng.randrange(128)]
        estimates.append(total / 128.0)
    estimates.sort()
    quantiles = []
    for p in (.025, .975):
        rank = 9999 * p
        lo = int(rank)
        alpha = rank - lo
        quantiles.append(estimates[lo] * (1.0 - alpha) + estimates[lo + 1] * alpha)
    wins = sum(r["score_bps"] == 10000 for r in subset)
    ties = sum(r["score_bps"] == 5000 for r in subset)
    verdict = "EXPLORATORY_STRONGER" if quantiles[0] > 5000 else "EXPLORATORY_WEAKER" if quantiles[1] < 5000 else "UNRESOLVED"
    return {"opponent": opponent, "matches": 256, "wins": wins, "ties": ties,
            "losses": 256 - wins - ties, "center_bps": sum(means) / 128,
            "ci_95_bps": quantiles, "exploratory_verdict": verdict,
            "mean_plies": sum(r["completed_plies"] for r in subset) / 256,
            "total_match_wall_seconds": round(sum(r["match_wall_seconds"] for r in subset), 6)}


def validate_schedule(rows: list[dict], smoke: bool = False) -> None:
    seeds = [9258999] if smoke else range(9259000, 9259128)
    opponents = OPPONENTS[:1] if smoke else OPPONENTS
    expected = {(o, s, r) for o in opponents for s in seeds for r in (0, 1)}
    actual = [(r["opponent"], r["seed"], r["rotation"]) for r in rows]
    need(len(actual) == len(expected) and set(actual) == expected, "incomplete or duplicate schedule")
    need(len({r["game_id"] for r in rows}) == len(rows), "duplicate game ID")


def audit(output: Path) -> dict:
    need(not output.exists(), "audit output exists (create-only)")
    config, result, frozen = load(CONFIG), load(RESULT), load(OUT / "freeze.json")
    manifest, smoke = load(OUT / "manifest.json"), load(OUT / "smoke-complete.json")
    candidate = OUT / "splendor-candidate.exe"
    reference = ROOT / config["reference_program"]
    need(sha(candidate) == frozen["candidate_binary_sha256"] == result["candidate_binary_sha256"], "candidate hash drift")
    need(sha(reference) == REFERENCE_SHA == frozen["reference_binary_sha256"] == result["reference_binary_sha256"], "reference hash drift")
    need(sha(CONFIG) == frozen["config_sha256"] == result["config_sha256"], "config hash mismatch")
    need(sha(OUT / "manifest.json") == result["manifest_sha256"], "manifest hash mismatch")
    need(sha(OUT / "freeze.json") == result["freeze_sha256"], "result freeze mismatch")
    for file, digest in frozen["sources"].items():
        need(sha(ROOT / file) == digest, f"frozen source drift {file}")
    need((config["seed_start"], config["seed_count"], config["smoke_seed"], config["rotations"]) == (9259000, 128, 9258999, [0, 1]), "schedule config drift")
    need(config["bootstrap"] == {"resamples": 10000, "seed": 92592026, "ci_percent": 95}, "bootstrap drift")
    need([o["id"] for o in config["opponents"]] == OPPONENTS, "opponent roster drift")
    need(config["candidate"]["agent_version"] == "0.2.9", "wrong candidate version")
    need(not (OUT / "smoke-failure.json").exists() and not (OUT / "pilot-failure.json").exists(), "failure marker present")
    for common in (manifest, smoke):
        need(common["config_sha256"] == sha(CONFIG) and common["binary_sha256"] == sha(candidate), "manifest identity drift")
        need(common["reference_sha256"] == REFERENCE_SHA and common["freeze_sha256"] == sha(OUT / "freeze.json"), "manifest reference/freeze drift")
    validate_schedule(manifest["rows"])
    validate_schedule(smoke["rows"], smoke=True)
    for mode, data in (("smoke", smoke), ("pilot", manifest)):
        journal = [json.loads(line) for line in (OUT / f"{mode}-rows.jsonl").read_text(encoding="utf-8").splitlines()]
        need(journal == data["rows"], f"{mode} journal/manifest mismatch")
        need(load(OUT / f"{mode}-start.json")["freeze_sha256"] == sha(OUT / "freeze.json"), "attempt freeze mismatch")
    recomputed = []
    count = 0
    for subdir, data in (("smoke", smoke), ("games", manifest)):
        expected_paths = set()
        for row in data["rows"]:
            opponent = next(o for o in config["opponents"] if o["id"] == row["opponent"])
            seed, seat = row["seed"], row["rotation"]
            need(row["candidate_seat"] == seat, "candidate seat mismatch")
            game_id = f"s4v029-{opponent['id']}-{seed}-r{seat}"
            need(row["game_id"] == game_id, "row game ID mismatch")
            directory = OUT / subdir / opponent["id"] / f"seed-{seed}" / f"r{seat}"
            cfg_file, rep_file, rpl_file = [directory / f for f in ("match-config.json", "arena-report.json", "match-replay.json")]
            expected_paths.add(cfg_file.resolve())
            for file, key in ((cfg_file, "config_sha256"), (rep_file, "report_sha256"), (rpl_file, "replay_sha256")):
                need(sha(file) == row[key], f"file hash mismatch: {file}")
            cfg, rep, rpl = load(cfg_file), load(rep_file), load(rpl_file)
            programs = [candidate, reference] if seat == 0 else [reference, candidate]
            specs = [config["candidate"], opponent] if seat == 0 else [opponent, config["candidate"]]
            need(cfg["game_id"] == rep["game_id"] == game_id, "game ID mismatch")
            need(cfg["seed"] == rpl["seed"] == seed, "seed mismatch")
            need(len(cfg["agents"]) == 2 and [a["seat"] for a in rep["agents"]] == [0, 1], "bad seats")
            for index, (program, spec) in enumerate(zip(programs, specs)):
                need(Path(cfg["agents"][index]["program"]).resolve() == program.resolve(), "program substitution")
                need(cfg["agents"][index]["args"] == spec["args"], "args/tie-seed drift")
                need((rep["agents"][index]["agent_name"], rep["agents"][index]["agent_version"]) == (spec["agent_name"], spec["agent_version"]), "reported identity mismatch")
            for key in ("handshake_timeout_ms", "move_timeout_ms", "shutdown_grace_ms"):
                need(cfg[key] == config[key], "timeout drift")
            process, verification = load(directory / "process.json"), load(directory / "verification.json")
            need(process["exit_code"] == verification["exit_code"] == 0 and not process["stderr"].strip() and not verification["stderr"].strip(), "recorded process/verify failure")
            need(rep["outcome"]["status"] == "completed" and rep["player_count"] == rpl["player_count"] == 2, "not a completed 2p game")
            outcome = rep["outcome"]
            need(outcome["result"] == rpl["result"], "report/replay outcomes differ")
            need(outcome["completed_plies"] == len(rpl["steps"]) == row["completed_plies"], "ply mismatch")
            need(outcome["replay_final_hash"] == rpl["final_state_hash"] == row["replay_final_hash"], "final hash mismatch")
            winners = outcome["result"]["winners"]
            points = score(winners, seat)
            need(points == row["score_bps"] and winners == row["winners"], "win mapping mismatch")
            check = subprocess.run([str(reference), "verify-replay", "--input", str(rpl_file)],
                                   capture_output=True, text=True, timeout=30)
            need(check.returncode == 0 and not check.stderr.strip(), f"extra verify failed: {rpl_file}")
            count += 1
            if subdir == "games":
                recomputed.append({**row, "score_bps": points, "completed_plies": len(rpl["steps"])})
        actual_paths = {p.resolve() for p in (OUT / subdir).rglob("match-config.json")}
        need(actual_paths == expected_paths, "unplanned attempt or missing game directory")
    summaries = [paired_summary(recomputed, opponent) for opponent in OPPONENTS]
    need(summaries == result["pairings"], "independent paired statistics differ")
    need(result["completed_and_verified_matches"] == 768 and result["aborts"] == 0 and result["matched_game_seeds"] == 128, "incomplete result")
    need(result["status"] == "EXPLORATORY_PILOT_ONLY", "inflated result status")
    need(sha(candidate) == frozen["candidate_binary_sha256"] and sha(reference) == REFERENCE_SHA, "binary drift during audit")
    evidence = {"format": "s4-v029-independent-computation-audit-v1", "status": "PASS",
                "scope": "author-run independent computation; not independent reviewer or promotion",
                "pilot_matches": 768, "smoke_matches": 2, "replays_reverified_exit0": count,
                "config_sha256": sha(CONFIG), "result_sha256": sha(RESULT),
                "freeze_sha256": sha(OUT / "freeze.json"), "manifest_sha256": sha(OUT / "manifest.json"),
                "candidate_sha256": sha(candidate), "reference_sha256": sha(reference),
                "audit_script_sha256": sha(Path(__file__)), "pairings_recomputed": summaries}
    with output.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(evidence, handle, indent=2)
        handle.write("\n")
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUT / "audit.json")
    args = parser.parse_args()
    evidence = audit(args.output)
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
