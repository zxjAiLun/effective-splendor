"""Terminal dashboard for Splendor Pool (Rich / ASCII fallback)."""

from __future__ import annotations

import os
import sys
import time
from typing import Any

from .store import Store
try:
    from rich.box import ROUNDED
    from rich.console import Console, Group
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    HAS_RICH = True
except ImportError:
    HAS_RICH = False


def render_rich_dashboard(store: Store) -> Any:
    summary = store.get_overview_summary()
    models = store.list_models()
    recent = store.list_recent_matches(limit=8)

    # 1. Header panel
    status_str = "[bold red]PAUSED[/]" if summary["is_paused"] else "[bold green]ACTIVE / RUNNING[/]"
    top_str = f"{summary['top_model']['name']} ({summary['top_model']['elo']:.1f})" if summary.get("top_model") else "N/A"
    
    header_text = (
        f"[bold cyan]✦ Splendor Arena Pool Dashboard ✦[/]\n"
        f"Status: {status_str} | Active Models: [bold]{summary['active_models']}/{summary['total_models']}[/] | "
        f"Completed Matches: [bold yellow]{summary['completed_matches']}[/] | Current #1: [bold magenta]{top_str}[/]"
    )
    header = Panel(header_text, style="blue", box=ROUNDED)

    # 2. Leaderboard Table
    t_lead = Table(title="[bold green]🏆 Elo Leaderboard & Match Summary[/]", box=ROUNDED, header_style="bold cyan")
    t_lead.add_column("Rank", justify="center", width=5)
    t_lead.add_column("Model Name", justify="left")
    t_lead.add_column("Type", justify="center")
    t_lead.add_column("Elo Rating", justify="right", style="bold yellow")
    t_lead.add_column("Games", justify="right")
    t_lead.add_column("W - T - L", justify="center")
    t_lead.add_column("Win Rate", justify="right")
    t_lead.add_column("Seat 0 %", justify="right")
    t_lead.add_column("Seat 1 %", justify="right")
    t_lead.add_column("Avg Score", justify="right")
    t_lead.add_column("Avg Margin", justify="right")
    t_lead.add_column("State", justify="center")

    for i, m in enumerate(models, 1):
        st = m.stats
        total = m.games
        wr = f"{(m.wins + 0.5 * m.ties) / max(total, 1) * 100.0:5.1f}%" if total > 0 else "0.0%"
        s0_wr = f"{st.get('seat0_win_rate_pct', 0.0):5.1f}%" if st.get("seat0_games", 0) > 0 else "-"
        s1_wr = f"{st.get('seat1_win_rate_pct', 0.0):5.1f}%" if st.get("seat1_games", 0) > 0 else "-"
        avg_score = f"{st.get('avg_score', 0.0):4.1f}"
        margin = st.get('avg_margin', 0.0)
        margin_str = f"+{margin:.1f}" if margin > 0 else f"{margin:.1f}"
        status_badge = "[green]ON[/]" if m.enabled else "[dim red]OFF[/]"

        t_lead.add_row(
            str(i),
            m.name,
            m.model_type,
            f"{m.elo:.1f}",
            str(total),
            f"{m.wins}-{m.ties}-{m.losses}",
            wr,
            s0_wr,
            s1_wr,
            avg_score,
            margin_str,
            status_badge,
        )

    # 3. Tactical Stats Table
    t_tact = Table(title="[bold magenta]📊 Tactical Metrics & Engine Statistics (Project Standard)[/]", box=ROUNDED, header_style="bold magenta")
    t_tact.add_column("Model Name", justify="left")
    t_tact.add_column("VP/Turn", justify="right")
    t_tact.add_column("VP/Ply", justify="right")
    t_tact.add_column("Avg Plies", justify="right")
    t_tact.add_column("Avg Cards", justify="right")
    t_tact.add_column("Reserves (Acq / Buy / Strand)", justify="center")
    t_tact.add_column("Redeem %", justify="right")
    t_tact.add_column("Avg Nobles", justify="right")

    for m in models:
        st = m.stats
        if m.games == 0:
            continue
        vp_turn = f"{st.get('avg_vp_turn', 0.0):.3f}"
        vp_ply = f"{st.get('avg_vp_ply', 0.0):.3f}"
        avg_plies = f"{st.get('avg_plies', 0.0):.1f}"
        avg_cards = f"{st.get('avg_cards', 0.0):.2f}"
        res_summary = f"{st.get('avg_reserves_acquired', 0.0):.1f} / {st.get('avg_reserves_bought', 0.0):.1f} / {st.get('avg_reserves_stranded', 0.0):.1f}"
        redeem = f"{st.get('reserves_redemption_rate_pct', 0.0):5.1f}%"
        avg_nobles = f"{st.get('avg_nobles', 0.0):.2f}"

        t_tact.add_row(
            m.name,
            vp_turn,
            vp_ply,
            avg_plies,
            avg_cards,
            res_summary,
            redeem,
            avg_nobles,
        )

    # 4. Head-to-Head Table
    t_h2h = Table(title="[bold cyan]⚔️ Head-to-Head Cross Summary[/]", box=ROUNDED, header_style="bold blue")
    t_h2h.add_column("Candidate vs Opponent", justify="left")
    t_h2h.add_column("Matches", justify="right")
    t_h2h.add_column("W - T - L", justify="center")
    t_h2h.add_column("Win Rate", justify="right")
    t_h2h.add_column("Score Diff", justify="right")

    for m in models:
        h2h = m.stats.get("head_to_head", {})
        for opp_name, rec in h2h.items():
            diff = rec.get("score_diff", 0)
            diff_str = f"+{diff}" if diff > 0 else str(diff)
            t_h2h.add_row(
                f"[bold]{m.name}[/] vs {opp_name}",
                str(rec.get("games", 0)),
                f"{rec.get('wins', 0)}-{rec.get('ties', 0)}-{rec.get('losses', 0)}",
                f"{rec.get('win_rate_pct', 0.0):5.1f}%",
                diff_str,
            )

    # 5. Recent Matches Table
    t_recent = Table(title="[bold yellow]🕒 Recent Matches[/]", box=ROUNDED, header_style="bold yellow")
    t_recent.add_column("ID", justify="center", width=6)
    t_recent.add_column("Seat 0 (First)", justify="left")
    t_recent.add_column("Score", justify="center", width=9)
    t_recent.add_column("Seat 1 (Second)", justify="left")
    t_recent.add_column("Winner", justify="center")
    t_recent.add_column("Elo Delta (P0 / P1)", justify="center")
    t_recent.add_column("Plies", justify="right")
    t_recent.add_column("Time", justify="center")

    for r in recent:
        p0_n = r["p0_name"]
        p1_n = r["p1_name"]
        sc = f"{r['p0_score']} - {r['p1_score']}"
        w_n = r["winner_name"] or ("Draw" if r["status"] == "completed" else r["status"])
        
        d0 = r.get("p0_elo_delta")
        d1 = r.get("p1_elo_delta")
        if d0 is not None and d1 is not None:
            d0_str = f"+{d0:.1f}" if d0 >= 0 else f"{d0:.1f}"
            d1_str = f"+{d1:.1f}" if d1 >= 0 else f"{d1:.1f}"
            elo_delta_str = f"{d0_str} / {d1_str}"
        else:
            elo_delta_str = "-"

        time_str = r.get("completed_at", "")[11:19] if r.get("completed_at") else ""
        t_recent.add_row(
            f"#{r['id']}",
            p0_n,
            sc,
            p1_n,
            f"[bold green]{w_n}[/]" if w_n != "Draw" else "[yellow]Draw[/]",
            elo_delta_str,
            str(r.get("completed_plies", "-")),
            time_str,
        )

    return Group(
        header,
        t_lead,
        t_tact,
        t_h2h,
        t_recent,
    )


def print_ascii_dashboard(store: Store) -> None:
    summary = store.get_overview_summary()
    models = store.list_models()
    recent = store.list_recent_matches(limit=6)

    print("=" * 80)
    print("               SPLENDOR ARENA POOL DASHBOARD")
    print("=" * 80)
    status_str = "PAUSED" if summary["is_paused"] else "RUNNING"
    print(f"Status: {status_str} | Active: {summary['active_models']}/{summary['total_models']} | Completed Matches: {summary['completed_matches']}")
    print("-" * 80)
    print(f"{'Rank':4} | {'Model Name':<16} | {'Type':<10} | {'Elo':>7} | {'Games':>5} | {'W-T-L':^9} | {'Win %':>6} | {'S0 %':>6} | {'S1 %':>6} | {'AvgSc':>5}")
    print("-" * 80)
    for i, m in enumerate(models, 1):
        st = m.stats
        total = m.games
        wr = f"{(m.wins + 0.5 * m.ties) / max(total, 1) * 100.0:5.1f}%" if total > 0 else "0.0%"
        s0_wr = f"{st.get('seat0_win_rate_pct', 0.0):5.1f}%" if st.get("seat0_games", 0) > 0 else "-"
        s1_wr = f"{st.get('seat1_win_rate_pct', 0.0):5.1f}%" if st.get("seat1_games", 0) > 0 else "-"
        avg_sc = f"{st.get('avg_score', 0.0):4.1f}"
        print(f"{i:4} | {m.name:<16} | {m.model_type:<10} | {m.elo:7.1f} | {total:5} | {m.wins}-{m.ties}-{m.losses:^5} | {wr:>6} | {s0_wr:>6} | {s1_wr:>6} | {avg_sc:>5}")

    print("-" * 80)
    print("TACTICAL METRICS (VP/Turn, Cards, Reserves, Nobles):")
    for m in models:
        st = m.stats
        if m.games > 0:
            print(f" - {m.name:<16}: VP/Turn={st.get('avg_vp_turn', 0.0):.3f} | Cards={st.get('avg_cards', 0.0):.2f} | Res(Acq/Buy)={st.get('avg_reserves_acquired', 0.0):.1f}/{st.get('avg_reserves_bought', 0.0):.1f} ({st.get('reserves_redemption_rate_pct', 0.0):.1f}%) | Nobles={st.get('avg_nobles', 0.0):.2f}")

    print("-" * 80)
    print("RECENT MATCHES:")
    for r in recent:
        w_n = r["winner_name"] or "Draw"
        print(f" #{r['id']:<4} | {r['p0_name']:<12} {r['p0_score']}:{r['p1_score']} {r['p1_name']:<12} | Winner: {w_n:<12} ({r.get('completed_plies')} plies)")
    print("=" * 80)


def show_dashboard(store: Store, live_mode: bool = False, interval: float = 3.0) -> None:
    if not HAS_RICH:
        print_ascii_dashboard(store)
        return

    console = Console()
    if not live_mode:
        console.print(render_rich_dashboard(store))
        return

    try:
        with Live(render_rich_dashboard(store), console=console, refresh_per_second=1) as live:
            while True:
                time.sleep(interval)
                live.update(render_rich_dashboard(store))
    except KeyboardInterrupt:
        pass
