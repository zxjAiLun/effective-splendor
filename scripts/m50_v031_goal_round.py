#!/usr/bin/env python3
"""Fixed v031 development pool and a single independent Aran qualification."""
from __future__ import annotations

import argparse
import concurrent.futures as futures
import json
import time
from pathlib import Path

import m50_reserve_target_binding_round as metrics
from m50_v031_teacher_round import logged_command

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "benchmarks/m50-aran-v031-goal-v1.config.json"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def goal():
    cfg = read(CONFIG)
    base = ROOT / cfg["artifact_root"]
    assert metrics.sha256(CONFIG) == read(base / "provenance/frozen-goal.json")["sha256"]
    for value in cfg["executables"].values():
        assert metrics.sha256(ROOT / value["path"]) == value["sha256"]
    return cfg, base


def identity(base, candidate):
    assert candidate in ("parent", "a", "b", "c")
    model = read(base / candidate / "identity.json")
    assert metrics.sha256(ROOT / model["weights"]) == model["weights_sha256"]
    assert metrics.sha256(ROOT / model["candidate_exe"]) == model["candidate_exe_sha256"]
    return model


def match_one(cfg, model, out, phase, seed, seat):
    directory = out / f"seed-{seed}" / f"r{seat}"
    directory.mkdir(parents=True, exist_ok=False)
    learner = {"program": str(ROOT / model["candidate_exe"]), "args": ["agent-m50-policy", "--weights", str(ROOT / model["weights"]), "--mode", "greedy"]}
    teacher = {"program": str(ROOT / cfg["executables"]["teacher"]["path"]), "args": cfg["teacher_args"]}
    game_id = f"{cfg['round_id']}-{model['candidate']}-{phase}-{seed}-r{seat}"
    match_cfg = {"game_id": game_id, "seed": seed, "agents": [learner, teacher] if seat == 0 else [teacher, learner],
                 "handshake_timeout_ms": 10000, "move_timeout_ms": 60000, "shutdown_grace_ms": 2000}
    metrics.write_json(directory / "match-config.json", match_cfg)
    engine = str(ROOT / cfg["executables"]["arena"]["path"])
    logged_command(directory, "arena", [engine, "run-match", "--config", str(directory / "match-config.json"),
                                      "--report-out", str(directory / "arena-report.json"), "--replay-out", str(directory / "match-replay.json")], 300)
    report = read(directory / "arena-report.json")
    assert report["game_id"] == game_id and report["outcome"]["status"] == "completed"
    logged_command(directory, "verify", [engine, "verify-replay", "--input", str(directory / "match-replay.json")], 120)
    result = report["outcome"]["result"]
    winners = result["winners"]
    assert winners in ([0], [1], [0, 1])
    point = 1.0 if winners == [seat] else 0.5 if len(winners) == 2 else 0.0
    return {"game_id": game_id, "seed": seed, "candidate_seat": seat, "won": point, "score_bps": int(point * 10000),
            "cand_score": result["scores"][seat], "opp_score": result["scores"][1 - seat],
            "plies": report["outcome"]["completed_plies"], "replay_verified": True,
            "match_config_sha256": metrics.sha256(directory / "match-config.json"),
            "report_sha256": metrics.sha256(directory / "arena-report.json"),
            "replay_sha256": metrics.sha256(directory / "match-replay.json")}


def evaluate(candidate, phase):
    cfg, base = goal()
    model = identity(base, candidate)
    if phase == "smoke":
        start, count = cfg["smoke_seeds"][candidate], 1
    elif phase == "development":
        smoke = read(base / candidate / "smoke/summary.json")
        assert smoke["status"] == "VALID" and smoke["weights_sha256"] == model["weights_sha256"]
        start, count = cfg["development"]["seed_start"], cfg["development"]["seed_count"]
    elif phase == "interaction":
        assert candidate == champion(cfg, base)["candidate"]
        start, count = cfg["interaction"]["seed_start"], cfg["interaction"]["seed_count"]
    elif phase == "qualification":
        sealed = read(base / "qualification-seal.json")
        assert sealed["candidate"] == candidate and sealed["weights_sha256"] == model["weights_sha256"]
        start, count = sealed["seed_start"], cfg["qualification"]["seed_count"]
    else:
        raise ValueError(phase)
    out = base / phase if phase in ("interaction", "qualification") else base / candidate / phase
    out.mkdir(exist_ok=False)
    tasks = [(seed, seat) for seed in range(start, start + count) for seat in (0, 1)]
    metrics.write_json(out / "planned.json", {"candidate": model, "phase": phase, "seeds": list(range(start, start + count))})
    remaining = iter(tasks)
    rows, errors = [], []
    t0 = time.perf_counter()
    with (out / "completion.jsonl").open("x", encoding="utf-8") as journal, futures.ThreadPoolExecutor(max_workers=cfg["workers"]) as pool:
        pending = {}
        while pending or not errors:
            if not errors:
                while len(pending) < cfg["workers"]:
                    task = next(remaining, None)
                    if task is None:
                        break
                    pending[pool.submit(match_one, cfg, model, out, phase, *task)] = task
            if not pending:
                break
            done, _ = futures.wait(pending, return_when=futures.FIRST_COMPLETED)
            for future in done:
                seed, seat = pending.pop(future)
                try:
                    row = future.result()
                    rows.append(row)
                    record = {"status": "completed", **row}
                except Exception as error:
                    record = {"status": "error", "seed": seed, "candidate_seat": seat, "error": repr(error)}
                    errors.append(record)
                journal.write(json.dumps(record) + "\n")
                journal.flush()
            if len(rows) % 32 == 0 or len(rows) == len(tasks):
                print(f"{candidate}/{phase}: {len(rows)}/{len(tasks)} valid, errors={len(errors)}", flush=True)
    rows.sort(key=lambda r: (r["seed"], r["candidate_seat"]))
    metrics.write_json(out / "rows.json", rows)
    if errors:
        metrics.write_json(out / "errors.json", errors)
        raise RuntimeError("stage failed; no automatic retry or replacement seed")
    assert [(r["seed"], r["candidate_seat"]) for r in rows] == tasks
    summary = metrics.summarize(rows, count, time.perf_counter() - t0)
    summary.update(candidate=candidate, phase=phase, seed_start=start, seed_count=count,
                   weights_sha256=model["weights_sha256"], candidate_exe_sha256=model["candidate_exe_sha256"],
                   arena_sha256=cfg["executables"]["arena"]["sha256"], teacher_sha256=cfg["executables"]["teacher"]["sha256"],
                   goal_config_sha256=metrics.sha256(CONFIG))
    for label, chosen in [("all", rows), ("r0", [r for r in rows if r["candidate_seat"] == 0]), ("r1", [r for r in rows if r["candidate_seat"] == 1])]:
        metrics.write_json(out / f"manifest-{label}.json", {"rows": [{"seed": r["seed"], "candidate_seat": r["candidate_seat"],
            "replay_path": f"seed-{r['seed']}/r{r['candidate_seat']}/match-replay.json", "replay_sha256": r["replay_sha256"],
            "report_sha256": r["report_sha256"], "match_config_sha256": r["match_config_sha256"]} for r in chosen]})
    if phase != "interaction":
        summary["unified_metrics"] = metrics.collect_metrics({"metrics_exe": cfg["executables"]["metrics"]["path"]}, out, summary)
    if phase == "qualification":
        summary["goal_met"] = summary["score_rate"] >= .5 and summary["ci95_paired"][0] >= .47
    metrics.write_json(out / "summary.json", summary)
    if phase == "development":
        selected = champion(cfg, base)
        (base / "champion.json").write_text(json.dumps(selected, indent=2), encoding="utf-8")
    return summary


def champion(cfg=None, base=None):
    if cfg is None:
        cfg, base = goal()
    best = None
    for name in ("parent", "a", "b", "c"):
        path = base / name / "development/summary.json"
        if not path.exists():
            continue
        summary = read(path)
        assert summary["status"] == "VALID" and summary["total_games"] == 512
        if best is None or summary["score_rate"] > best["development_score_rate"]:
            best = {**identity(base, name), "development_score_rate": summary["score_rate"], "development_summary_sha256": metrics.sha256(path)}
    if best is None:
        raise RuntimeError("no validated development result")
    return best


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("smoke", "development", "interaction", "qualification", "champion"))
    parser.add_argument("--candidate", choices=("parent", "a", "b", "c"), default="parent")
    args = parser.parse_args()
    result = champion() if args.operation == "champion" else evaluate(args.candidate, args.operation)
    print(json.dumps(result, indent=2, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
