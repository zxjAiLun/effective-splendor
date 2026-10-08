"""Bounded, resumable M54 fixed-pool development evaluator (stdlib only; Python 3.11+).

Usage (importing/testing this module never runs games):
  python scripts/prism_ppo_fixed_eval.py --config fixed-eval.json --output eval-run

Schema ``prism-ppo-fixed-eval-v1``:
  {"format":"prism-ppo-fixed-eval-v1",
   "engine":{"program":".../splendor","sha256":"<64 lowercase hex>"},
   "catalog_fingerprint":"<ruleset fingerprint>", "action_seed":54010001,
   "seeds":[...fixed nonnegative u64 seeds...],
   "candidates":{"parent":{"program":".../splendor","sha256":"...",
     "args":["agent-prism-sample","--weights",".../weights.json","--seed","54010001"],
     "files":[{"path":".../weights.json","sha256":"..."}]}},
   "opponents":{"greedy":{"program":".../splendor","sha256":"...",
     "args":["agent-heuristic-v02","--seed","20260926"],"files":[]}},
   "timeouts":{"game_wall_seconds":120,"handshake_timeout_ms":30000,
     "move_timeout_ms":60000,"shutdown_grace_ms":2000}}

Paths are resolved relative to the config file. All executable/assets are SHA-pinned.
Every candidate runs against every opponent for every seed, in both seats. Game IDs
are ``m54-fixed-<opponent>-seed-<seed>-seat-<candidate-seat>`` and intentionally
exclude candidate identity for common random numbers. The engine is invoked directly
(no shell) with ``run-match``. Output is immutable per completed game and resumable;
config/asset drift, partial/failed games, nonterminal matches, or report/replay
mismatch stop the run. Reports are structurally checked; this is not a second rules
replay, PPO behavior audit, Elo/pool update, acceptance gate, or promotion. Results
are development-only. Candidate/opponent descriptors contain literal argv tokens;
files is a list of pinned non-executable assets. The first candidate in JSON order
is the parent used for paired deltas.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import subprocess
import sys
import time

FORMAT = "prism-ppo-fixed-eval-v1"
BOOTSTRAP_SEED = 54019999
BOOTSTRAP_SAMPLES = 10_000
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _bad_constant(value):
    raise ValueError(f"nonfinite JSON value: {value}")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"),
                      object_pairs_hook=_unique_object, parse_constant=_bad_constant)


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def canonical_hash(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    temp = path.with_name(path.name + f".{os.getpid()}.tmp")
    raw = json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False,
                     allow_nan=False).encode("utf-8") + b"\n"
    try:
        with temp.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _validate_name(name, where):
    _require(isinstance(name, str) and NAME_RE.fullmatch(name) is not None,
             f"{where} name must be a safe path component")


def _validate_hash(value, where):
    _require(isinstance(value, str) and SHA_RE.fullmatch(value) is not None,
             f"{where} must be a lowercase SHA-256")


def _resolve(base, path, where):
    _require(isinstance(path, str) and path.strip(), f"{where} path is required")
    result = Path(path)
    if not result.is_absolute():
        result = base / result
    return result.resolve()


def validate_config(config, config_path):
    # Work on a copy so the saved/hash-bound user document remains unchanged.
    config = json.loads(json.dumps(config))
    _require(isinstance(config, dict) and config.get("format") == FORMAT,
             f"config format must be {FORMAT}")
    expected = {"format", "engine", "catalog_fingerprint", "action_seed", "seeds",
                "candidates", "opponents", "timeouts"}
    _require(set(config) == expected, "config has missing or unknown fields")
    base = Path(config_path).resolve().parent
    _require(isinstance(config["engine"], dict)
             and set(config["engine"]) == {"program", "sha256"}, "invalid engine descriptor")
    engine = dict(config["engine"])
    engine["resolved_program"] = str(_resolve(base, engine["program"], "engine program"))
    _validate_hash(engine["sha256"], "engine.sha256")
    _require(isinstance(config["catalog_fingerprint"], str)
             and 1 <= len(config["catalog_fingerprint"]) <= 256, "invalid catalog_fingerprint")
    _require(type(config["action_seed"]) is int and 0 <= config["action_seed"] <= 2**63 - 1,
             "action_seed must be a u63 integer")
    seeds = config["seeds"]
    _require(isinstance(seeds, list) and seeds, "seeds must be a nonempty fixed list")
    _require(all(type(seed) is int and 0 <= seed <= 2**64 - 1 for seed in seeds),
             "each seed must be a u64 integer")
    _require(len(set(seeds)) == len(seeds), "seeds must be unique")
    for key in ("candidates", "opponents"):
        descriptors = config[key]
        _require(isinstance(descriptors, dict) and descriptors,
                 f"{key} must be a nonempty name-to-descriptor map")
        for name, descriptor in descriptors.items():
            _validate_name(name, key)
            _require(isinstance(descriptor, dict)
                     and set(descriptor) == {"program", "sha256", "args", "files"},
                     f"invalid {key}.{name} descriptor")
            _validate_hash(descriptor["sha256"], f"{key}.{name}.sha256")
            program = str(_resolve(base, descriptor["program"], f"{key}.{name}.program"))
            _require(isinstance(descriptor["args"], list)
                     and all(isinstance(arg, str) and "\0" not in arg for arg in descriptor["args"]),
                     f"{key}.{name}.args must be literal strings")
            _require(isinstance(descriptor["files"], list), f"{key}.{name}.files must be a list")
            resolved_files = []
            for asset in descriptor["files"]:
                _require(isinstance(asset, dict) and set(asset) == {"path", "sha256"},
                         f"invalid pinned asset in {key}.{name}")
                _validate_hash(asset["sha256"], f"{key}.{name}.files.sha256")
                resolved_files.append({"path": str(_resolve(base, asset["path"], "asset")),
                                       "sha256": asset["sha256"]})
            descriptor["program_resolved"] = program
            descriptor["files_resolved"] = resolved_files
            if key == "candidates":
                args = descriptor["args"]
                _require(len(args) == 5 and args[0] == "agent-prism-sample"
                         and args[1] == "--weights" and args[3] == "--seed",
                         f"candidate {name} must use agent-prism-sample --weights <path> --seed <action_seed>")
                _require(args[4] == str(config["action_seed"]),
                         f"candidate {name} sampling --seed must equal config action_seed")
                weight_path = str(_resolve(base, args[2], f"candidate {name} weights"))
                _require(any(asset["path"] == weight_path for asset in resolved_files),
                         f"candidate {name} weights must appear in files with a pinned SHA")
                descriptor["args_resolved"] = [args[0], args[1], weight_path, args[3], args[4]]
            else:
                descriptor["args_resolved"] = list(descriptor["args"])
    _require(isinstance(config["timeouts"], dict)
             and set(config["timeouts"]) == {"game_wall_seconds", "handshake_timeout_ms",
                                               "move_timeout_ms", "shutdown_grace_ms"},
             "timeouts must provide wall, handshake, move, and shutdown limits")
    for key, minimum, maximum in (("game_wall_seconds", 1, 86400),
                                  ("handshake_timeout_ms", 1, 86400000),
                                  ("move_timeout_ms", 1, 86400000),
                                  ("shutdown_grace_ms", 1, 86400000)):
        value = config["timeouts"][key]
        _require(type(value) is int and minimum <= value <= maximum, f"invalid timeouts.{key}")
    return {"config": config, "base": str(base), "engine": engine,
            "candidates": config["candidates"], "opponents": config["opponents"]}


def check_assets(validated):
    checks = [(validated["engine"]["resolved_program"], validated["engine"]["sha256"], "engine")]
    for group in ("candidates", "opponents"):
        for name, descriptor in validated[group].items():
            checks.append((descriptor["program_resolved"], descriptor["sha256"], f"{group}.{name}.program"))
            checks.extend((asset["path"], asset["sha256"], f"{group}.{name}.file")
                          for asset in descriptor["files_resolved"])
    for path, expected, label in checks:
        actual = sha256_file(path)
        _require(actual == expected, f"{label} hash mismatch at {path}: expected {expected}, got {actual}")


def _game_id(opponent, seed, candidate_seat):
    value = f"m54-fixed-{opponent}-seed-{seed}-seat-{candidate_seat}"
    _require(len(value.encode("utf-8")) <= 128, "generated game_id exceeds engine limit")
    return value


def _game_key(candidate, opponent, seed, seat):
    return f"{candidate}/{opponent}/seed-{seed}/seat-{seat}"


def _validate_result(result):
    _require(isinstance(result, dict)
             and set(result) >= {"scores", "ranks", "winners", "reason"}, "missing result/ranks")
    scores, ranks, winners = result["scores"], result["ranks"], result["winners"]
    _require(isinstance(scores, list) and len(scores) == 2
             and all(type(score) is int and 0 <= score <= 255 for score in scores), "invalid scores")
    _require(isinstance(ranks, list) and len(ranks) == 2
             and all(type(rank) is int for rank in ranks), "invalid terminal ranks")
    _require(ranks in ([0, 0], [0, 1], [1, 0]), "invalid terminal ranks")
    _require(isinstance(winners, list) and all(type(winner) is int for winner in winners)
             and sorted(winners) == [index for index, rank in enumerate(ranks) if rank == 0],
             "result winners/ranks disagree")
    _require(isinstance(result["reason"], str) and result["reason"], "invalid terminal reason")


def _report_result(report, replay, *, game_id, seed, seat, catalog):
    _require(isinstance(report, dict) and report.get("format") == "effective-splendor-arena-report"
             and report.get("version") == 1, "invalid arena report format/version")
    _require(report.get("game_id") == game_id and report.get("player_count") == 2,
             "report game identity/player count mismatch")
    _require(report.get("ruleset_fingerprint") == catalog, "report catalog fingerprint mismatch")
    outcome = report.get("outcome")
    _require(isinstance(outcome, dict) and outcome.get("status") == "completed",
             "match is not normally completed")
    result = outcome.get("result")
    _validate_result(result)
    _require(type(outcome.get("completed_plies")) is int and outcome["completed_plies"] > 0,
             "completed report is missing valid plies")
    _require(isinstance(replay, dict) and replay.get("format") == "effective-splendor-replay"
             and replay.get("version") == 1, "invalid replay format/version")
    _require(replay.get("player_count") == 2 and replay.get("seed") == seed,
             "replay seed/player count mismatch")
    _require(replay.get("ruleset_fingerprint") == catalog, "replay catalog fingerprint mismatch")
    _require(replay.get("final_state_hash") == outcome.get("replay_final_hash"),
             "report/replay final hash mismatch")
    _require(isinstance(replay.get("steps"), list)
             and len(replay["steps"]) == outcome["completed_plies"], "report/replay ply count mismatch")
    _require(replay.get("result") == result, "report/replay result mismatch")
    scores, ranks, winners = result["scores"], result["ranks"], result["winners"]
    if ranks[seat] == ranks[1 - seat]:
        score, record = 0.5, "draw"
    elif ranks[seat] < ranks[1 - seat]:
        score, record = 1.0, "win"
    else:
        score, record = 0.0, "loss"
    return {"game_id": game_id, "seed": seed, "candidate_seat": seat,
            "scores": scores, "ranks": ranks, "winners": winners,
            "candidate_score": score, "record": record,
            "candidate_points": scores[seat], "opponent_points": scores[1 - seat],
            "plies": outcome["completed_plies"]}


def _atomic_text(path, content):
    path = Path(path)
    temp = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        with temp.open("x", encoding="utf-8", newline="") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def _evaluate_one(validated, output, candidate, opponent, seed, seat, progress):
    game_id = _game_id(opponent, seed, seat)
    key = _game_key(candidate, opponent, seed, seat)
    game_dir = output / "games" / candidate / opponent / f"seed-{seed}-seat-{seat}"
    game_dir.mkdir(parents=True, exist_ok=True)
    config_path = game_dir / "match-config.json"
    report_path = game_dir / "report.json"
    replay_path = game_dir / "replay.json"
    stdout_path, stderr_path = game_dir / "stdout.log", game_dir / "stderr.log"
    record_path = game_dir / "game.json"

    previous = progress["games"].get(key)
    if previous and previous.get("status") == "completed":
        _require(report_path.is_file() and replay_path.is_file(), f"completed game artifacts missing: {key}")
        report, replay = read_json(report_path), read_json(replay_path)
        row = _report_result(report, replay, game_id=game_id, seed=seed, seat=seat,
                             catalog=validated["config"]["catalog_fingerprint"])
        _require(previous.get("report_sha256") == sha256_file(report_path)
                 and previous.get("replay_sha256") == sha256_file(replay_path),
                 f"completed game artifact hash drift: {key}")
        row.update(candidate=candidate, opponent=opponent)
        return row
    _require(previous is None, f"game has a failed/in-progress record and will not be respawned: {key}")
    _require(not report_path.exists() and not replay_path.exists() and not record_path.exists(),
             f"orphan/partial game artifacts; refusing to respawn: {key}")

    candidate_descriptor = validated["candidates"][candidate]
    opponent_descriptor = validated["opponents"][opponent]
    candidate_command = {"program": candidate_descriptor["program_resolved"],
                         "args": candidate_descriptor["args_resolved"]}
    opponent_command = {"program": opponent_descriptor["program_resolved"],
                       "args": opponent_descriptor["args_resolved"]}
    config = {"game_id": game_id, "seed": seed,
              "handshake_timeout_ms": validated["config"]["timeouts"]["handshake_timeout_ms"],
              "move_timeout_ms": validated["config"]["timeouts"]["move_timeout_ms"],
              "shutdown_grace_ms": validated["config"]["timeouts"]["shutdown_grace_ms"],
              "agents": [candidate_command, opponent_command] if seat == 0 else [opponent_command, candidate_command]}
    atomic_json(config_path, config)
    atomic_json(record_path, {"status": "running", "game_id": game_id,
                              "game_config_sha256": canonical_hash(config)})
    check_assets(validated)
    argv = [validated["engine"]["resolved_program"], "run-match", "--config", str(config_path),
            "--report-out", str(report_path), "--replay-out", str(replay_path)]
    started = time.monotonic()
    try:
        completed = subprocess.run(argv, cwd=validated["base"], stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE,
                                   timeout=validated["config"]["timeouts"]["game_wall_seconds"],
                                   check=False, shell=False)
        _atomic_text(stdout_path, completed.stdout.decode("utf-8", errors="replace"))
        _atomic_text(stderr_path, completed.stderr.decode("utf-8", errors="replace"))
        resources = {"returncode": completed.returncode,
                     "wall_seconds": time.monotonic() - started, "argv": argv}
        atomic_json(game_dir / "process-result.json", resources)
        _require(completed.returncode == 0, f"run-match failed for {key}: exit {completed.returncode}")
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout or b""
        stderr = error.stderr or b""
        _atomic_text(stdout_path, stdout.decode("utf-8", errors="replace") if isinstance(stdout, bytes) else stdout)
        _atomic_text(stderr_path, stderr.decode("utf-8", errors="replace") if isinstance(stderr, bytes) else stderr)
        atomic_json(record_path, {"status": "error", "game_id": game_id, "error": "wall-timeout"})
        progress["games"][key] = {"status": "error", "game_id": game_id, "error": "wall-timeout"}
        atomic_json(output / "progress.json", progress)
        raise ValueError(f"game wall timeout for {key}; retained artifacts, no automatic retry") from error
    except BaseException as error:
        if not stdout_path.exists():
            _atomic_text(stdout_path, "")
        if not stderr_path.exists():
            _atomic_text(stderr_path, f"{type(error).__name__}: {error}\n")
        atomic_json(record_path, {"status": "error", "game_id": game_id,
                                  "error": f"{type(error).__name__}: {error}"})
        progress["games"][key] = {"status": "error", "game_id": game_id,
                                  "error": f"{type(error).__name__}: {error}"}
        atomic_json(output / "progress.json", progress)
        raise
    try:
        _require(report_path.is_file() and replay_path.is_file(),
                 f"normal run-match exit did not publish report and replay: {key}")
        report, replay = read_json(report_path), read_json(replay_path)
        row = _report_result(report, replay, game_id=game_id, seed=seed, seat=seat,
                             catalog=validated["config"]["catalog_fingerprint"])
        row.update(candidate=candidate, opponent=opponent)
        atomic_json(record_path, {"status": "completed", "game_id": game_id,
                                  "game_config_sha256": canonical_hash(config),
                                  "report_sha256": sha256_file(report_path),
                                  "replay_sha256": sha256_file(replay_path), "row": row})
        progress["games"][key] = {"status": "completed", "game_id": game_id,
                                  "report_sha256": sha256_file(report_path),
                                  "replay_sha256": sha256_file(replay_path), "row": row}
        atomic_json(output / "progress.json", progress)
        return row
    except BaseException as error:
        atomic_json(record_path, {"status": "error", "game_id": game_id,
                                  "error": f"{type(error).__name__}: {error}"})
        progress["games"][key] = {"status": "error", "game_id": game_id,
                                  "error": f"{type(error).__name__}: {error}"}
        atomic_json(output / "progress.json", progress)
        raise


def _mean(values):
    _require(bool(values), "cannot aggregate an empty sample")
    return math.fsum(values) / len(values)


def _percentile(values, q):
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower = int(position)
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[min(lower + 1, len(ordered) - 1)] * fraction


def _bootstrap_ci(per_seed, seed):
    rng = random.Random(seed)
    n = len(per_seed)
    draws = [_mean([per_seed[rng.randrange(n)] for _ in range(n)])
             for _ in range(BOOTSTRAP_SAMPLES)]
    return [_percentile(draws, 0.025), _percentile(draws, 0.975)]


def _summarize_rows(rows):
    wins = sum(row["record"] == "win" for row in rows)
    draws = sum(row["record"] == "draw" for row in rows)
    losses = sum(row["record"] == "loss" for row in rows)
    return {"games": len(rows), "wins": wins, "draws": draws, "losses": losses,
            "score_rate": _mean([row["candidate_score"] for row in rows]),
            "mean_candidate_score": _mean([row["candidate_points"] for row in rows]),
            "mean_opponent_score": _mean([row["opponent_points"] for row in rows]),
            "mean_plies": _mean([row["plies"] for row in rows])}


def aggregate(validated, rows):
    candidates = list(validated["candidates"])
    opponents = list(validated["opponents"])
    seeds = list(validated["config"]["seeds"])
    by_key = {(row["candidate"], row["opponent"], row["seed"], row["candidate_seat"]): row
              for row in rows}
    expected = len(candidates) * len(opponents) * len(seeds) * 2
    _require(len(rows) == expected and len(by_key) == expected,
             "incomplete or duplicate fixed evaluation grid")
    pairs = {}
    for candidate in candidates:
        pairs[candidate] = {}
        for opponent in opponents:
            matchup_rows = [by_key[(candidate, opponent, seed, seat)]
                            for seed in seeds for seat in (0, 1)]
            per_seed = [_mean([by_key[(candidate, opponent, seed, seat)]["candidate_score"]
                               for seat in (0, 1)]) for seed in seeds]
            per_seat = {str(seat): _summarize_rows(
                [by_key[(candidate, opponent, seed, seat)] for seed in seeds])
                for seat in (0, 1)}
            pairs[candidate][opponent] = {
                **_summarize_rows(matchup_rows),
                "seat": per_seat,
                "per_seed_score_rate": per_seed,
                "score_rate_ci95_by_seed": _bootstrap_ci(per_seed, BOOTSTRAP_SEED),
            }
    parent = candidates[0]
    paired = {}
    for candidate in candidates:
        deltas = []
        for seed in seeds:
            differences = [
                by_key[(candidate, opponent, seed, seat)]["candidate_score"]
                - by_key[(parent, opponent, seed, seat)]["candidate_score"]
                for opponent in opponents for seat in (0, 1)
            ]
            deltas.append(_mean(differences))
        paired[candidate] = {"parent_candidate": parent,
                             "mean_delta_score_rate": _mean(deltas),
                             "ci95_by_seed": _bootstrap_ci(deltas, BOOTSTRAP_SEED)}
    return {"format": "prism-ppo-fixed-eval-result-v1",
            "verdict": "DEVELOPMENT_ONLY_NOT_PROMOTED",
            "config_sha256": validated["config_sha256"],
            "catalog_fingerprint": validated["config"]["catalog_fingerprint"],
            "action_seed": validated["config"]["action_seed"], "seeds": seeds,
            "seed_count": len(seeds),
            "bootstrap": {"method": "paired seed-block percentile",
                          "samples": BOOTSTRAP_SAMPLES, "seed": BOOTSTRAP_SEED},
            "parent_candidate": parent, "candidate_opponent": pairs,
            "candidate_minus_first_parent": paired, "games": expected}


def _load_progress(output, validated):
    config_hash = validated["config_sha256"]
    progress_path = output / "progress.json"
    if output.exists():
        _require(output.is_dir(), "output path must be a directory")
        existing = list(output.iterdir())
        if existing:
            saved_path = output / "config.json"
            _require(saved_path.is_file(), "existing output directory has no saved config")
            _require(canonical_hash(read_json(saved_path)) == config_hash,
                     "config drift: resume requires exact same config")
            _require(progress_path.is_file(), "existing output has no progress state")
            progress = read_json(progress_path)
            _require(progress.get("config_sha256") == config_hash, "progress config drift")
            return progress
    else:
        output.mkdir(parents=True)
    progress = {"format": "prism-ppo-fixed-eval-progress-v1",
                "config_sha256": config_hash, "games": {}}
    atomic_json(output / "config.json", validated["saved_config"])
    atomic_json(progress_path, progress)
    return progress


def _rows_from_progress(progress, validated):
    rows = []
    for candidate in validated["candidates"]:
        for opponent in validated["opponents"]:
            for seed in validated["config"]["seeds"]:
                for seat in (0, 1):
                    key = _game_key(candidate, opponent, seed, seat)
                    record = progress["games"].get(key)
                    _require(record is not None and record.get("status") == "completed",
                             f"fixed evaluation has incomplete game: {key}")
                    row = dict(record["row"])
                    _require(row.get("candidate") == candidate and row.get("opponent") == opponent
                             and row.get("seed") == seed and row.get("candidate_seat") == seat,
                             f"progress row identity mismatch: {key}")
                    rows.append(row)
    _require(len(progress["games"]) == len(rows), "progress contains unexpected game records")
    return rows


def run_eval(config_path, output_path):
    config_path = Path(config_path).resolve()
    config = read_json(config_path)
    validated = validate_config(config, config_path)
    validated["saved_config"] = config
    validated["config_sha256"] = canonical_hash(config)
    check_assets(validated)
    output = Path(output_path).resolve()
    progress = _load_progress(output, validated)
    completion_path = output / "completion.json"
    result_path = output / "result.json"
    if completion_path.exists():
        completion = read_json(completion_path)
        _require(completion.get("config_sha256") == validated["config_sha256"], "completion config drift")
        if result_path.is_file() and completion.get("result_sha256") is not None:
            _require(completion["result_sha256"] == sha256_file(result_path),
                     "completed result changed")
            return read_json(result_path)
        expected = len(validated["candidates"]) * len(validated["opponents"]) * len(config["seeds"]) * 2
        _require(completion.get("completed_games") == expected
                 and completion.get("game_keys") == sorted(progress["games"]),
                 "completion manifest/progress game keys disagree")
        rows = _rows_from_progress(progress, validated)
        result = aggregate(validated, rows)
        atomic_json(result_path, result)
        completion["result_sha256"] = sha256_file(result_path)
        atomic_json(completion_path, completion)
        return result

    total = len(validated["candidates"]) * len(validated["opponents"]) * len(config["seeds"]) * 2
    for candidate in validated["candidates"]:
        for opponent in validated["opponents"]:
            for seed in config["seeds"]:
                for seat in (0, 1):
                    check_assets(validated)
                    _evaluate_one(validated, output, candidate, opponent, seed, seat, progress)
                    print(f"completed {len(progress['games'])}/{total}: {_game_key(candidate, opponent, seed, seat)}",
                          flush=True)
    rows = _rows_from_progress(progress, validated)
    # Seal exact completed jobs before aggregation; a restart never launches games again.
    completion = {"format": "prism-ppo-fixed-eval-completion-v1",
                  "config_sha256": validated["config_sha256"],
                  "completed_games": total, "game_keys": sorted(progress["games"])}
    atomic_json(completion_path, completion)
    result = aggregate(validated, rows)
    atomic_json(result_path, result)
    completion["result_sha256"] = sha256_file(result_path)
    atomic_json(completion_path, completion)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run/resume bounded fixed-seed Prism development evaluation")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = run_eval(args.config, args.output)
    except Exception as error:
        print(f"error: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"status": "complete", "verdict": result["verdict"],
                      "games": result["games"], "output": str(args.output.resolve())}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
