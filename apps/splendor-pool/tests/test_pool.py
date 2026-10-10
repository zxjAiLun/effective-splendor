"""Unit tests for Splendor Pool components."""

import json
import tempfile
from pathlib import Path

from splendor_pool.config import Config
from splendor_pool.elo import calculate_expected, compute_elo_update
from splendor_pool.models import (
    create_custom_spec,
    create_heuristic_spec,
    create_m50_policy_spec,
)
from splendor_pool.stats import accumulate_model_stats, extract_match_stats
from splendor_pool.store import Store


def test_elo_calculations():
    # Equal rating: expected should be 0.5
    exp = calculate_expected(1500.0, 1500.0)
    assert round(exp, 4) == 0.5

    # 400 point difference: higher rated player expected ~ 0.9091
    exp_high = calculate_expected(1900.0, 1500.0)
    assert round(exp_high, 4) == 0.9091

    # Win update
    res = compute_elo_update(1500.0, 1500.0, 1.0, k_factor=32.0)
    assert res.delta_a == 16.0
    assert res.delta_b == -16.0
    assert res.elo_after_a == 1516.0
    assert res.elo_after_b == 1484.0

    # Draw update
    res_draw = compute_elo_update(1500.0, 1500.0, 0.5, k_factor=32.0)
    assert res_draw.delta_a == 0.0
    assert res_draw.delta_b == 0.0


def test_models_and_adapter():
    h_spec = create_heuristic_spec("h-02", "agent-heuristic-v02", weight=2.0)
    agent_cfg = h_spec.to_agent_config("/usr/bin/splendor")
    assert agent_cfg.program == "/usr/bin/splendor"
    assert agent_cfg.args == ["agent-heuristic-v02", "--seed", "42"]
    assert h_spec.weight == 2.0

    m50_spec = create_m50_policy_spec("aran", "/tmp/w.json", mode="greedy")
    m50_cfg = m50_spec.to_agent_config("/usr/bin/splendor")
    assert m50_cfg.args == ["agent-m50-policy", "--weights", "/tmp/w.json", "--mode", "greedy"]


def test_stats_extraction():
    fake_report = {
        "outcome": {
            "result": {
                "scores": [15, 12],
                "ranks": [0, 1],
                "winners": [0],
            },
            "completed_plies": 40,
        }
    }
    fake_replay = {
        "steps": [
            {"actor": 0, "action": {"type": "buy_market", "tier": "One", "slot": 0}},
            {"actor": 1, "action": {"type": "reserve_market", "tier": "One", "slot": 1}},
            {"actor": 0, "action": {"type": "choose_noble", "noble": 1}},
            {"actor": 1, "action": {"type": "buy_reserved", "slot": 0}},
        ]
    }
    p0, p1 = extract_match_stats(fake_report, fake_replay)
    assert p0.score == 15
    assert p0.won == 1.0
    assert p0.purchased_cards == 1
    assert p0.nobles == 1
    assert p0.turns == 20

    assert p1.score == 12
    assert p1.won == 0.0
    assert p1.reserves_acquired == 1
    assert p1.reserves_bought == 1
    assert p1.reserves_stranded == 0

    acc = accumulate_model_stats({}, p0, "opp", 12)
    assert acc["games"] == 1
    assert acc["total_score"] == 15
    assert acc["avg_score"] == 15.0
    assert acc["seat0_win_rate_pct"] == 100.0
    assert acc["head_to_head"]["opp"]["wins"] == 1


def test_store_operations():
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        cfg = Config.default(tdp)
        store = Store(cfg)
        store.initialize()

        # Enforce paused check
        assert not store.is_paused()
        store.pause(True)
        assert store.is_paused()
        store.pause(False)
        assert not store.is_paused()

        # Add models
        m1_id = store.add_model(create_heuristic_spec("m1", "agent-heuristic"))
        m2_id = store.add_model(create_heuristic_spec("m2", "agent-heuristic-v02"))

        models = store.list_models()
        assert len(models) == 2
        assert models[0].name in ("m1", "m2")

        # Sampling
        pair = store.sample_matchup()
        assert pair is not None
        assert pair[0].id != pair[1].id

        # Match life cycle
        mid = store.create_match(m1_id, m2_id, seed=123)
        store.start_match(mid)

        elo_res = compute_elo_update(1500.0, 1500.0, 1.0)
        store.complete_match(
            match_id=mid,
            winner_id=m1_id,
            p0_score=15,
            p1_score=10,
            completed_plies=42,
            replay_path="rep.json",
            report_path="rep.json",
            elo_result=elo_res,
            p0_new_stats_json="{}",
            p1_new_stats_json="{}",
        )

        m1_updated = store.get_model(m1_id)
        m2_updated = store.get_model(m2_id)
        assert m1_updated.elo == 1516.0
        assert m1_updated.wins == 1
        assert m2_updated.elo == 1484.0
        assert m2_updated.losses == 1

        recent = store.list_recent_matches(limit=5)
        assert len(recent) == 1
        assert recent[0]["winner_name"] == "m1"
        assert recent[0]["p0_elo_delta"] == 16.0
