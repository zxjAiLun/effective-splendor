#!/usr/bin/env python3
"""One fixed M50 reserve-target candidate: data parity and no-retry paired arena."""
from __future__ import annotations

import argparse
import concurrent.futures as futures
import hashlib
import json
import random
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import m50_eval_parallel as arena

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "benchmarks/m50-aran-reserve-target-binding-v1.config.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def check_data(config: dict) -> dict:
    import numpy as np

    spec = config["dataset"]
    old_dir, new_dir = ROOT / spec["reference_dir"], ROOT / spec["out_dir"]
    assert sha256(old_dir / "manifest.json") == spec["reference_manifest_sha256"]
    old = json.loads((old_dir / "manifest.json").read_text(encoding="utf-8"))
    new = json.loads((new_dir / "manifest.json").read_text(encoding="utf-8"))
    assert (new["observation_width"], new["action_width"], new["action_representation"]) == (
        368, 72, "semantic-reserve-target-v1"
    )
    assert new["total_replays_parsed"] == old["total_replays_parsed"] == spec["expected_replays"]
    assert (new["val_modulus"], new["val_remainder"]) == (old["val_modulus"], old["val_remainder"]) == (5, 0)
    result = {"status": "PASS", "old_manifest_sha256": sha256(old_dir / "manifest.json"),
              "new_manifest_sha256": sha256(new_dir / "manifest.json"), "splits": {}}
    for split in ("train", "val"):
        expected = spec[f"expected_{split}_decisions"]
        assert new["splits"][split]["step_count"] == old["splits"][split]["step_count"] == expected
        hashes = {}
        for name in ("obs.f32", "action_offsets.u64", "chosen_action.u32", "values.f32"):
            old_sha, new_sha = sha256(old_dir / split / name), sha256(new_dir / split / name)
            assert old_sha == new_sha, f"non-action data drift: {split}/{name}"
            hashes[name] = new_sha
        before = np.memmap(old_dir / split / "actions.f32", dtype="<f4", mode="r").reshape(-1, 56)
        after = np.memmap(new_dir / split / "actions.f32", dtype="<f4", mode="r").reshape(-1, 72)
        assert len(before) == len(after) == new["splits"][split]["total_actions"]
        reserve_rows = 0
        for start in range(0, len(before), 100000):
            a, b = before[start:start + 100000], after[start:start + 100000]
            assert np.array_equal(a, b[:, :56]), f"semantic prefix drift in {split} at {start}"
            assert np.isfinite(b).all()
            reserved = a[:, 3] > 0.5
            assert np.count_nonzero(b[~reserved, 56:]) == 0
            assert np.all(b[reserved, 56] == 1) and np.all(b[reserved, 71] == 0)
            reserve_rows += int(reserved.sum())
        hashes["actions.f32"] = sha256(new_dir / split / "actions.f32")
        result["splits"][split] = {"decisions": expected, "actions": len(after),
                                    "reserve_market_actions": reserve_rows, "hashes": hashes,
                                    "prefix_exact": True, "non_action_files_exact": True}
    paths = sorted({p for rel in spec["source_dirs"] for p in (ROOT / rel).rglob("*replay.json")})
    assert len(paths) == spec["expected_replays"], f"unexpected replay count: {len(paths)}"
    replay_hashes = [{"path": str(p.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(p)} for p in paths]
    out = ROOT / config["artifact_root"] / "provenance"
    write_json(out / "source-replays.json", replay_hashes)
    result["source_replays_manifest_sha256"] = sha256(out / "source-replays.json")
    write_json(out / "data-check.json", result)
    return result


def checked_arena_run(argv: list[str], **kwargs):
    """Raise on the first failure, bypassing the legacy runner's retry loop."""
    directory = Path(argv[argv.index("--config") + 1]).parent
    started = time.perf_counter()
    try:
        result = subprocess.run(argv, **kwargs)
    except Exception as error:
        write_json(directory / "execution-error.json", {"argv": argv, "error": repr(error)})
        raise
    (directory / "arena.stdout.log").write_text(result.stdout or "", encoding="utf-8")
    (directory / "arena.stderr.log").write_text(result.stderr or "", encoding="utf-8")
    write_json(directory / "execution.json", {"argv": argv, "returncode": result.returncode,
                                               "seconds": time.perf_counter() - started})
    if result.returncode:
        raise RuntimeError(f"arena exit {result.returncode}: {directory}")
    return result


def run_one(task: tuple) -> dict:
    seed, seat = task[:2]
    directory = task[7] / f"seed-{seed}" / f"r{seat}"
    if directory.exists():
        raise FileExistsError(f"refusing to overwrite or rerun {directory}")
    row = arena.run_one_match(task)
    report_path, replay_path = directory / "arena-report.json", directory / "match-replay.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["outcome"]["status"] == "completed", "non-completed outcome"
    assert report["game_id"] == row["game_id"] and report["player_count"] == 2
    verify = subprocess.run([str(arena.CANDIDATE_EXE), "verify-replay", "--input", str(replay_path)],
                            capture_output=True, text=True, timeout=120)
    write_json(directory / "verification.json", {"returncode": verify.returncode,
                                                 "stdout": verify.stdout, "stderr": verify.stderr})
    if verify.returncode:
        raise RuntimeError(f"replay verification failed: {directory}")
    row.update(replay_sha256=sha256(replay_path), report_sha256=sha256(report_path),
               match_config_sha256=sha256(directory / "match-config.json"), replay_verified=True)
    return row


def summarize(rows: list[dict], seed_count: int, elapsed: float) -> dict:
    wins, ties, losses = (sum(row["won"] == score for row in rows) for score in (1, 0.5, 0))
    blocks = [(rows[2 * i]["won"] + rows[2 * i + 1]["won"]) / 2 for i in range(seed_count)]
    rng = random.Random(92552026)
    samples = sorted(sum(rng.choice(blocks) for _ in blocks) / len(blocks) for _ in range(10000))
    return {
        "status": "VALID", "total_games": len(rows), "wins": wins, "ties": ties, "losses": losses,
        "score_rate": (wins + 0.5 * ties) / len(rows), "pure_win_rate": wins / len(rows),
        "ci95_paired": [arena.percentile(samples, 0.025), arena.percentile(samples, 0.975)],
        "score_rate_by_seat": [sum(r["won"] for r in rows if r["candidate_seat"] == seat) / seed_count for seat in (0, 1)],
        "mean_candidate_score": sum(r["cand_score"] for r in rows) / len(rows),
        "mean_opponent_score": sum(r["opp_score"] for r in rows) / len(rows),
        "mean_plies": sum(r["plies"] for r in rows) / len(rows), "wall_seconds": elapsed,
        "replay_verified_games": sum(r["replay_verified"] for r in rows),
    }


def collect_metrics(spec: dict, out: Path, summary: dict) -> dict:
    raw = {}
    for label in ("all", "r0", "r1"):
        output = out / f"metrics-{label}.json"
        argv = [str(ROOT / spec["metrics_exe"]), str(out / f"manifest-{label}.json"), str(output)]
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=120)
        write_json(out / f"metrics-{label}.execution.json", {"argv": argv, "returncode": proc.returncode,
                                                           "stdout": proc.stdout, "stderr": proc.stderr})
        if proc.returncode:
            raise RuntimeError(f"metrics failed for {label}: {proc.stderr}")
        raw[label] = json.loads(output.read_text(encoding="utf-8"))
        expected = summary["total_games"] if label == "all" else summary["seed_count"]
        assert raw[label]["total_games"] == expected

    def player(first: dict, second: dict) -> dict:
        n0, n1 = raw["r0"]["total_games"], raw["r1"]["total_games"]
        total = n0 + n1
        merged = {key: first[key] + second[key] for key in ("wins", "ties", "losses", "games_with_nobles")}
        for key in ("mean_prestige", "mean_nobles", "mean_permanent_bonuses", "mean_reserves_acquired",
                    "mean_reserves_bought", "mean_reserves_stranded"):
            merged[key] = (first[key] * n0 + second[key] * n1) / total
        for key in ("mean_cards_by_vp", "mean_bonuses_by_color"):
            merged[key] = {name: (first[key].get(name, 0) * n0 + second[key].get(name, 0) * n1) / total
                           for name in sorted(set(first[key]) | set(second[key]))}
        counts = {name: first["action_distribution"].get(name, 0) + second["action_distribution"].get(name, 0)
                  for name in sorted(set(first["action_distribution"]) | set(second["action_distribution"]))}
        merged["action_distribution"] = counts
        merged["action_percentages"] = {name: value / sum(counts.values()) * 100 for name, value in counts.items()}
        merged["total_games"] = total
        merged["score_rate"] = (merged["wins"] + 0.5 * merged["ties"]) / total
        merged["pure_win_rate"] = merged["wins"] / total
        prestige = merged["mean_prestige"] * total
        merged["vp_per_turn"] = prestige / (raw["r0"]["mean_turns"] * n0 + raw["r1"]["mean_turns"] * n1)
        merged["vp_per_ply"] = prestige / (raw["r0"]["total_plies"] + raw["r1"]["total_plies"])
        acquired = merged["mean_reserves_acquired"]
        merged["reserve_redemption_rate"] = merged["mean_reserves_bought"] / acquired if acquired else None
        return merged

    candidate = player(raw["r0"]["seat_p0_first"], raw["r1"]["seat_p1_second"])
    opponent = player(raw["r0"]["seat_p1_second"], raw["r1"]["seat_p0_first"])
    assert [candidate[key] for key in ("wins", "ties", "losses")] == [summary[key] for key in ("wins", "ties", "losses")]
    assert abs(candidate["mean_prestige"] - summary["mean_candidate_score"]) < 1e-9
    combined = {"format": raw["all"]["format"], "candidate": candidate, "opponent": opponent,
                "convention": "candidate=r0/p0+r1/p1; VP/turn and VP/ply are ratios of totals; choose_noble counts as an actor action",
                "metrics_sha256": {label: sha256(out / f"metrics-{label}.json") for label in raw}}
    write_json(out / "unified-summary.json", combined)
    return combined


def evaluate(config: dict, phase: str) -> dict:
    assert config["status"] == "FROZEN", "freeze config before arena"
    spec = config["evaluation"]
    root = ROOT / config["artifact_root"]
    if phase != "smoke":
        previous = "smoke" if phase == "screen" else "screen"
        prev = json.loads((root / previous / "summary.json").read_text(encoding="utf-8"))
        assert prev["status"] == "VALID" and prev["total_games"] == spec[previous]["games"]
        if phase == "confirmation":
            assert prev["score_rate"] > 0.5, "screen failed; confirmation prohibited"
    for key in ("candidate_exe", "opponent_exe", "metrics_exe"):
        assert sha256(ROOT / spec[key]) == spec[f"{key}_sha256"], f"frozen {key} changed"
    for path_key, hash_key in (("pretrained", "pretrained_sha256"), ("parent_published_weights", "parent_published_sha256")):
        assert sha256(ROOT / config["training"][path_key]) == config["training"][hash_key]
    identity = json.loads((root / "provenance/selected-model.json").read_text(encoding="utf-8"))
    assert sha256(ROOT / spec["weights"]) == identity["weights_sha256"]
    assert sha256(DEFAULT_CONFIG) == identity["config_sha256"]
    stage = spec[phase]
    out = root / phase
    out.mkdir(exist_ok=False)
    arena.CANDIDATE_EXE = ROOT / spec["candidate_exe"]
    arena.subprocess = SimpleNamespace(run=checked_arena_run)
    tasks = [(seed, seat, "greedy", 0, 0, ROOT / spec["opponent_exe"], spec["opponent_args"], out,
              f"{config['round_id']}-{phase}", ROOT / spec["weights"])
             for seed in range(stage["seed_start"], stage["seed_start"] + stage["seed_count"])
             for seat in (0, 1)]
    write_json(out / "planned-matches.json", [{"seed": t[0], "candidate_seat": t[1]} for t in tasks])
    rows, errors = [], []
    started = time.perf_counter()
    with (out / "completion.jsonl").open("x", encoding="utf-8") as log, futures.ThreadPoolExecutor(max_workers=spec["workers"]) as pool:
        pending = {}
        # Keep at most workers in flight; never submit the whole remaining stage after an error.
        remaining = iter(tasks)
        for _ in range(min(spec["workers"], len(tasks))):
            task = next(remaining)
            pending[pool.submit(run_one, task)] = task
        while pending:
            done, _ = futures.wait(pending, return_when=futures.FIRST_COMPLETED)
            for future in done:
                task = pending.pop(future)
                try:
                    row = future.result()
                    rows.append(row)
                    record = {"status": "completed", **row}
                except Exception as error:
                    record = {"status": "error", "seed": task[0], "candidate_seat": task[1], "error": repr(error)}
                    errors.append(record)
                log.write(json.dumps(record, ensure_ascii=False) + "\n")
                log.flush()
            if not errors:
                while len(pending) < spec["workers"]:
                    task = next(remaining, None)
                    if task is None:
                        break
                    pending[pool.submit(run_one, task)] = task
            if len(rows) % 16 == 0 or not pending:
                print(f"{phase}: {len(rows)}/{len(tasks)} valid, errors={len(errors)}", flush=True)
    rows.sort(key=lambda r: (r["seed"], r["candidate_seat"]))
    write_json(out / "rows.json", rows)
    if errors:
        write_json(out / "summary.json", {"status": "ERROR", "valid_games": len(rows), "errors": errors})
        raise RuntimeError(f"{phase} stopped after execution error; no retries")
    assert [(r["seed"], r["candidate_seat"]) for r in rows] == [(t[0], t[1]) for t in tasks]
    summary = summarize(rows, stage["seed_count"], time.perf_counter() - started)
    summary.update(phase=phase, seed_start=stage["seed_start"], seed_count=stage["seed_count"],
                   candidate_weights_sha256=identity["weights_sha256"], candidate_exe_sha256=spec["candidate_exe_sha256"],
                   opponent_exe_sha256=spec["opponent_exe_sha256"], config_sha256=identity["config_sha256"])
    for label, selected in [("all", rows), ("r0", [r for r in rows if r["candidate_seat"] == 0]),
                            ("r1", [r for r in rows if r["candidate_seat"] == 1])]:
        manifest = {"rows": [{"seed": r["seed"], "candidate_seat": r["candidate_seat"],
                               "replay_path": f"seed-{r['seed']}/r{r['candidate_seat']}/match-replay.json",
                               "replay_sha256": r["replay_sha256"], "report_sha256": r["report_sha256"],
                               "match_config_sha256": r["match_config_sha256"]} for r in selected]}
        write_json(out / f"manifest-{label}.json", manifest)
    summary["unified_metrics"] = collect_metrics(spec, out, summary)
    write_json(out / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("check-data", "smoke", "screen", "confirmation"))
    args = parser.parse_args()
    config = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
    result = check_data(config) if args.operation == "check-data" else evaluate(config, args.operation)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
