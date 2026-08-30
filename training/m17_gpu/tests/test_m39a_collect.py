from __future__ import annotations

import json
from pathlib import Path

import pytest

from splendor_gpu.m39a_collect import _collect_games
from splendor_gpu.m39a_contract import load_plan, plan_hash, scheduled_game


class _NullServer:
    url = "127.0.0.1:65534"
    ready_file = Path("null-server-ready.json")


def _make_game_dir(out_dir: Path, game_index: int, files: list[str]) -> Path:
    game = scheduled_game(game_index)
    game_dir = out_dir / "games" / f"game-{game_index:06d}"
    game_dir.mkdir(parents=True, exist_ok=True)
    for name in files:
        (game_dir / name).write_text("{}", encoding="utf-8")
    return game_dir


def _run_collect(out_dir: Path, plan_path: Path, splendor: Path | None = None) -> None:
    plan = load_plan(plan_path)
    if splendor is None:
        splendor = out_dir / "splendor.exe"
        splendor.write_text("fake", encoding="utf-8")
    _collect_games(
        server=_NullServer(),
        plan=plan,
        digest=plan_hash(plan),
        checkpoint=Path("unused.pt"),
        checkpoint_sha256="a" * 64,
        cycle=1,
        count=1,
        start=0,
        catalog_path=Path("catalog.json"),
        splendor=splendor,
        out_dir=out_dir,
        device="cuda",
        sources=[],
        elapsed=[],
    )


PLAN = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "benchmarks/m39a-arena-driven-policy-value-rl.plan.json"
)


def test_partial_report_replay_sidecar_is_rejected(tmp_path: Path) -> None:
    _make_game_dir(tmp_path, 0, ["arena-config.json", "arena-report.json"])
    with pytest.raises(RuntimeError, match="partial artifacts"):
        _run_collect(tmp_path, PLAN)


def test_config_only_directory_is_recoverable(tmp_path: Path) -> None:
    game_dir = _make_game_dir(tmp_path, 0, ["arena-config.json"])
    (game_dir / "arena-config.json").write_text(
        json.dumps({"stale": "server-url-from-dead-run"}), encoding="utf-8"
    )
    # The runner is a fake executable that fails immediately; what matters is
    # that the stale config was removed and rewritten (the new config's
    # content embeds the live server URL) before the run is attempted.
    fake = tmp_path / "splendor.cmd"
    fake.write_text("@echo off\r\nexit /b 1\r\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="failed rc="):
        _run_collect(tmp_path, PLAN, splendor=fake)
    config = json.loads((game_dir / "arena-config.json").read_text(encoding="utf-8"))
    assert "stale" not in config
    args = config["agents"][0]["args"]
    assert "127.0.0.1:65534" in args


def test_replay_and_prefix_coexistence_is_rejected(tmp_path: Path) -> None:
    game = scheduled_game(0)
    files = [
        "arena-report.json",
        "replay.json",
        "rollout-prefix.json",
        *(f"seat-{seat}.sidecar.json" for seat in game.learner_seats),
    ]
    _make_game_dir(tmp_path, 0, files)
    with pytest.raises(RuntimeError, match="both replay and prefix"):
        _run_collect(tmp_path, PLAN)


def test_complete_terminal_game_resumes_without_rerun(tmp_path: Path) -> None:
    game = scheduled_game(0)
    report = {"outcome": {"status": "completed", "completed_plies": 60}}
    files = ["arena-report.json", "replay.json", "arena-config.json"]
    game_dir = _make_game_dir(tmp_path, 0, files)
    (game_dir / "arena-report.json").write_text(json.dumps(report), encoding="utf-8")
    for seat in game.learner_seats:
        (game_dir / f"seat-{seat}.sidecar.json").write_text("{}", encoding="utf-8")
    sources: list[dict] = []
    _collect_games(
        server=_NullServer(),
        plan=load_plan(PLAN),
        digest=plan_hash(load_plan(PLAN)),
        checkpoint=Path("unused.pt"),
        checkpoint_sha256="a" * 64,
        cycle=1,
        count=1,
        start=0,
        catalog_path=Path("catalog.json"),
        splendor=Path("splendor.exe"),
        out_dir=tmp_path,
        device="cuda",
        sources=sources,
        elapsed=[],
    )
    assert sources and sources[0]["prefix_path"] == ""
