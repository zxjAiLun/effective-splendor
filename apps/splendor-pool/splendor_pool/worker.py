"""Single-table autonomous Splendor match worker with Elo settlement."""

from __future__ import annotations

import contextlib
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .config import Config
from .elo import compute_elo_update
from .models import ModelSpec
from .stats import accumulate_model_stats, extract_match_stats
from .store import Store


@contextlib.contextmanager
def exclusive_worker(lock_path: Path) -> Iterator[None]:
    """OS-level non-blocking lock to prevent multiple worker instances."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        import fcntl

        with lock_path.open("a+b") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("Another splendor-pool worker is already running on this data_dir") from exc
            handle.seek(0)
            handle.truncate()
            handle.write(f"{os.getpid()}\n".encode())
            handle.flush()
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    else:
        # Basic Windows file lock
        try:
            lock_file = lock_path.open("x")
            lock_file.write(f"{os.getpid()}\n")
            lock_file.flush()
        except FileExistsError as exc:
            raise RuntimeError("Another splendor-pool worker is already running on this data_dir") from exc
        try:
            yield
        finally:
            lock_file.close()
            lock_path.unlink(missing_ok=True)


def execute_match(
    config: Config,
    store: Store,
    p0: ModelSpec,
    p1: ModelSpec,
    seed: int,
) -> bool:
    """Run one match between p0 and p1, extract stats, calculate Elo and persist."""
    match_id = store.create_match(p0.id, p1.id, seed)
    store.start_match(match_id)

    agent0_cfg = p0.to_agent_config(config.engine_exe, seed=seed).to_dict()
    agent1_cfg = p1.to_agent_config(config.engine_exe, seed=seed + 1).to_dict()

    match_config = {
        "game_id": f"pool-match-{match_id:06d}-s{seed}",
        "seed": seed,
        "agents": [agent0_cfg, agent1_cfg],
        "handshake_timeout_ms": 10000,
        "move_timeout_ms": 60000,
        "shutdown_grace_ms": 2000,
    }

    with tempfile.TemporaryDirectory() as temp_dir:
        td = Path(temp_dir)
        cfg_file = td / "match-config.json"
        rep_file = td / "arena-report.json"
        rpl_file = td / "match-replay.json"

        cfg_file.write_text(json.dumps(match_config, indent=2), encoding="utf-8")

        start_time = time.perf_counter()
        proc = subprocess.run(
            [
                config.engine_exe,
                "run-match",
                "--config",
                str(cfg_file),
                "--report-out",
                str(rep_file),
                "--replay-out",
                str(rpl_file),
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        elapsed = time.perf_counter() - start_time

        if proc.returncode != 0:
            err_msg = f"Process exit {proc.returncode}: {proc.stderr[:400]}"
            store.fail_match(match_id, err_msg)
            print(f"[Match #{match_id}] FAILED: {err_msg}", file=sys.stderr)
            return False

        if not rep_file.exists() or not rpl_file.exists():
            err_msg = "Engine failed to output report or replay file"
            store.fail_match(match_id, err_msg)
            print(f"[Match #{match_id}] FAILED: {err_msg}", file=sys.stderr)
            return False

        try:
            rep_data = json.loads(rep_file.read_text(encoding="utf-8"))
            rpl_data = json.loads(rpl_file.read_text(encoding="utf-8"))
        except Exception as exc:
            store.fail_match(match_id, f"JSON parse error: {exc}")
            return False

    # Extract tactical stats
    stat0, stat1 = extract_match_stats(rep_data, rpl_data)

    # Calculate Elo
    elo_res = compute_elo_update(
        rating_a=p0.elo,
        rating_b=p1.elo,
        score_a=stat0.won,
        k_factor=config.elo_k,
    )

    # Accumulate model statistics
    p0_stats_acc = accumulate_model_stats(p0.stats, stat0, p1.name, stat1.score)
    p1_stats_acc = accumulate_model_stats(p1.stats, stat1, p0.name, stat0.score)

    # Determine winner id
    if stat0.won == 1.0:
        winner_id = p0.id
    elif stat1.won == 1.0:
        winner_id = p1.id
    else:
        winner_id = None

    # Persistent storage for replay
    match_dir = store.root / "matches" / f"{match_id:06d}"
    match_dir.mkdir(parents=True, exist_ok=True)
    saved_rep_path = match_dir / "report.json"
    saved_rpl_path = match_dir / "replay.json"

    saved_rep_path.write_text(json.dumps(rep_data, indent=2), encoding="utf-8")
    if config.retain_replays:
        saved_rpl_path.write_text(json.dumps(rpl_data, indent=2), encoding="utf-8")

    # Persist in DB
    store.complete_match(
        match_id=match_id,
        winner_id=winner_id,
        p0_score=stat0.score,
        p1_score=stat1.score,
        completed_plies=stat0.plies,
        replay_path=str(saved_rpl_path) if config.retain_replays else "",
        report_path=str(saved_rep_path),
        elo_result=elo_res,
        p0_new_stats_json=json.dumps(p0_stats_acc, ensure_ascii=False),
        p1_new_stats_json=json.dumps(p1_stats_acc, ensure_ascii=False),
    )

    w_str = p0.name if stat0.won == 1.0 else p1.name if stat1.won == 1.0 else "Draw"
    delta0_str = f"+{elo_res.delta_a:.1f}" if elo_res.delta_a >= 0 else f"{elo_res.delta_a:.1f}"
    delta1_str = f"+{elo_res.delta_b:.1f}" if elo_res.delta_b >= 0 else f"{elo_res.delta_b:.1f}"
    print(
        f"[Match #{match_id:04d} | {elapsed*1000:5.0f}ms] "
        f"{p0.name} ({stat0.score}pt, Elo {p0.elo:.1f} -> {elo_res.elo_after_a:.1f} [{delta0_str}]) vs "
        f"{p1.name} ({stat1.score}pt, Elo {p1.elo:.1f} -> {elo_res.elo_after_b:.1f} [{delta1_str}]) | "
        f"Winner: {w_str} ({stat0.plies} plies)",
        flush=True,
    )
    return True


def run_worker(
    config: Config,
    once: bool = False,
    max_games: int = 0,
) -> int:
    """Main worker loop running matches until stopped or reaching max_games."""
    store = Store(config)
    store.initialize()

    lock_path = store.root / "worker.lock"
    completed_games = 0

    with exclusive_worker(lock_path):
        print(f"Splendor Pool Worker online. Data: {store.root}", flush=True)
        print(f"Engine: {config.engine_exe}", flush=True)

        while True:
            if store.is_paused():
                if once or (max_games and completed_games >= max_games):
                    return completed_games
                time.sleep(config.poll_seconds)
                continue

            pair = store.sample_matchup()
            if pair is None:
                print("Not enough enabled models (minimum 2 required). Waiting...", flush=True)
                if once:
                    return completed_games
                time.sleep(config.poll_seconds)
                continue

            p0, p1 = pair
            seed = random.randint(1_000_000, 999_999_999)

            success = execute_match(config, store, p0, p1, seed)
            if success:
                completed_games += 1

            if once:
                break
            if max_games and completed_games >= max_games:
                break

    return completed_games
