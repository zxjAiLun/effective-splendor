"""CLI interface for Splendor Pool: python -m splendor_pool --config <toml> <cmd>."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import Config
from .dashboard import show_dashboard
from .models import (
    create_custom_spec,
    create_heuristic_spec,
    create_m50_policy_spec,
)
from .store import Store
from .web import serve_web
from .worker import run_worker


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Autonomous 1v1 Splendor Match Pool with Elo settlement"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.toml"),
        help="Path to pool configuration profile (default: config.toml)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # init
    subparsers.add_parser("init", help="Initialize database ledger and settings")

    # status & dashboard
    subparsers.add_parser("status", help="Print static terminal dashboard once")
    dash = subparsers.add_parser("dashboard", help="Live auto-refreshing terminal dashboard")
    dash.add_argument("--interval", type=float, default=2.0, help="Refresh interval in seconds")

    # worker
    worker_p = subparsers.add_parser("worker", help="Run autonomous single-table match worker")
    worker_p.add_argument("--once", action="store_true", help="Play exactly one match and exit")
    worker_p.add_argument("--max-games", type=int, default=0, help="Stop after N matches (0 = unlimited)")

    # serve (Web UI + REST API)
    subparsers.add_parser("serve", help="Start web dashboard and REST API HTTP server")

    # pause
    pause_p = subparsers.add_parser("pause", help="Toggle pool matchmaking pause")
    pause_p.add_argument("state", choices=("on", "off"), help="Pause state: 'on' to pause, 'off' to resume")

    # model management
    model_p = subparsers.add_parser("model", help="Manage pool candidate models")
    model_sub = model_p.add_subparsers(dest="model_command", required=True)

    model_sub.add_parser("list", help="List enrolled models and their status")

    add_h = model_sub.add_parser("add-heuristic", help="Enroll a heuristic agent")
    add_h.add_argument("--name", required=True, help="Display name of the model")
    add_h.add_argument("--subcommand", default="agent-heuristic-v02", help="Subcommand (agent-heuristic, agent-heuristic-v02)")
    add_h.add_argument("--weight", type=float, default=1.0, help="Sampling weight (default: 1.0)")
    add_h.add_argument("--program", help="Optional path to custom splendor executable")

    add_m = model_sub.add_parser("add-m50", help="Enroll an Aran / M50 Neural Policy agent")
    add_m.add_argument("--name", required=True, help="Display name of the model")
    add_m.add_argument("--weights", required=True, help="Path to weights.json")
    add_m.add_argument("--mode", default="greedy", choices=("greedy", "sampling"), help="Inference mode")
    add_m.add_argument("--weight", type=float, default=1.0, help="Sampling weight (default: 1.0)")
    add_m.add_argument("--program", help="Optional path to custom splendor executable")

    add_c = model_sub.add_parser("add-custom", help="Enroll a custom CLI agent")
    add_c.add_argument("--name", required=True, help="Display name of the model")
    add_c.add_argument("--args", nargs="+", required=True, help="Command-line arguments for agent")
    add_c.add_argument("--weight", type=float, default=1.0, help="Sampling weight")
    add_c.add_argument("--program", help="Optional path to custom executable")

    upd_m = model_sub.add_parser("update", help="Update model matchmaking weight or status")
    upd_m.add_argument("id", type=int, help="Model ID")
    upd_m.add_argument("--name", help="Rename model")
    upd_m.add_argument("--weight", type=float, help="Set new sampling weight")
    upd_toggle = upd_m.add_mutually_exclusive_group()
    upd_toggle.add_argument("--enable", action="store_true", help="Enable model for matchmaking")
    upd_toggle.add_argument("--disable", action="store_true", help="Disable model from matchmaking")

    # match inspection
    match_p = subparsers.add_parser("match", help="Query match history")
    match_sub = match_p.add_subparsers(dest="match_command", required=True)
    match_list = match_sub.add_parser("list", help="List recent matches")
    match_list.add_argument("--limit", type=int, default=20, help="Maximum number of matches")

    args = parser.parse_args()

    config = Config.load(args.config)
    store = Store(config)
    store.initialize()

    cmd = args.command

    if cmd == "init":
        print(f"Initialized Splendor Pool at {store.root} (DB: {store.db_path})")

    elif cmd == "status":
        show_dashboard(store, live_mode=False)

    elif cmd == "dashboard":
        show_dashboard(store, live_mode=True, interval=args.interval)

    elif cmd == "worker":
        games = run_worker(config, once=args.once, max_games=args.max_games)
        print(f"Worker completed {games} games.")

    elif cmd == "serve":
        serve_web(config)

    elif cmd == "pause":
        paused = args.state == "on"
        store.pause(paused)
        print(f"Matchmaking is now {'PAUSED' if paused else 'RESUMED'}.")

    elif cmd == "model":
        m_cmd = args.model_command
        if m_cmd == "list":
            models = store.list_models()
            print(f"{'ID':4} | {'Name':<18} | {'Type':<12} | {'Elo':>7} | {'Weight':>6} | {'Status':>6}")
            print("-" * 65)
            for m in models:
                st = "ENABLED" if m.enabled else "DISABLED"
                print(f"{m.id:<4} | {m.name:<18} | {m.model_type:<12} | {m.elo:7.1f} | {m.weight:6.2f} | {st:>6}")
        elif m_cmd == "add-heuristic":
            spec = create_heuristic_spec(
                name=args.name,
                subcommand=args.subcommand,
                program=args.program,
                weight=args.weight,
            )
            mid = store.add_model(spec)
            print(f"Enrolled heuristic model '{args.name}' (ID: {mid}, Elo: {spec.elo:.1f})")
        elif m_cmd == "add-m50":
            spec = create_m50_policy_spec(
                name=args.name,
                weights_path=args.weights,
                mode=args.mode,
                program=args.program,
                weight=args.weight,
            )
            mid = store.add_model(spec)
            print(f"Enrolled m50 model '{args.name}' (ID: {mid}, Elo: {spec.elo:.1f})")
        elif m_cmd == "add-custom":
            spec = create_custom_spec(
                name=args.name,
                args=args.args,
                program=args.program,
                weight=args.weight,
            )
            mid = store.add_model(spec)
            print(f"Enrolled custom model '{args.name}' (ID: {mid}, Elo: {spec.elo:.1f})")
        elif m_cmd == "update":
            enabled = True if args.enable else False if args.disable else None
            store.update_model(args.id, weight=args.weight, enabled=enabled, name=args.name)
            print(f"Updated model {args.id}.")

    elif cmd == "match":
        if args.match_command == "list":
            matches = store.list_recent_matches(limit=args.limit)
            print(f"{'ID':5} | {'Seat 0':<15} | {'Score':^9} | {'Seat 1':<15} | {'Winner':<12} | {'Plies':>5}")
            print("-" * 75)
            for m in matches:
                sc = f"{m['p0_score']}:{m['p1_score']}"
                w = m["winner_name"] or "Draw"
                print(f"#{m['id']:<4} | {m['p0_name']:<15} | {sc:^9} | {m['p1_name']:<15} | {w:<12} | {m['completed_plies']:>5}")


if __name__ == "__main__":
    main()
