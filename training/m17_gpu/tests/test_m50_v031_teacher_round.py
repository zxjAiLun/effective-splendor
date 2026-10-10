"""Mock-only checks for the teacher data round; never starts real agents."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import m50_v031_teacher_round as teacher


def config(tmp_path):
    return {
        "status": "FROZEN", "round_id": "test-teacher", "artifact_root": str(tmp_path), "workers": 2,
        "teacher": {"program": "teacher-v031.exe", "args": ["agent-heuristic-v02", "--seed", "20260926"],
                    "seed_start": 9331000, "games": 2000},
        "evaluation": {"smoke": {"seed_start": 9333999, "seed_count": 1, "games": 2},
                       "screen": {"seed_start": 9334000, "seed_count": 128, "games": 256},
                       "confirmation": {"seed_start": 9335000, "seed_count": 250, "games": 500}},
    }


def test_teacher_uses_two_identical_frozen_teachers_not_neural_agent(tmp_path):
    cfg = config(tmp_path)
    match = teacher.teacher_match_config(cfg, 9331000)
    assert match["seed"] == 9331000
    assert len(match["agents"]) == 2 and match["agents"][0] == match["agents"][1]
    assert match["agents"][0]["program"].endswith("teacher-v031.exe")
    assert match["agents"][0]["args"] == cfg["teacher"]["args"]
    assert "agent-m50-policy" not in match["agents"][0]["args"]


def test_training_uses_2000_unique_seeds_and_game_level_split(tmp_path):
    cfg = config(tmp_path)
    seeds = teacher.teacher_seeds(cfg)
    assert len(seeds) == len(set(seeds)) == 2000
    assert (seeds[0], seeds[-1]) == (9331000, 9332999)
    assert sum(seed % 5 == 0 for seed in seeds) == 400
    cfg["evaluation"]["screen"]["seed_start"] = seeds[-1]
    with pytest.raises(AssertionError, match="overlap"):
        teacher.teacher_seeds(cfg)


def test_collection_counts_first_smoke_once_and_does_not_repeat(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    monkeypatch.setattr(teacher, "verify_identities", lambda _: None)
    calls = []
    def game(_, seed):
        calls.append(seed)
        return {"seed": seed}
    monkeypatch.setattr(teacher, "run_teacher_game", game)
    result = teacher.collect(cfg)
    assert result == {"status": "PASS", "teacher_games": 2000}
    assert len(calls) == len(set(calls)) == 2000 and calls[0] == 9331000
    journal = (tmp_path / "teacher/completion.jsonl").read_text().splitlines()
    assert len(journal) == 2000
    with pytest.raises(FileExistsError):
        teacher.collect(cfg)
    assert len(calls) == 2000


def test_collection_stops_on_error_without_replacement_seeds(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    monkeypatch.setattr(teacher, "verify_identities", lambda _: None)
    calls = []
    def game(_, seed):
        calls.append(seed)
        if seed == 9331001:
            raise RuntimeError("fixture failure")
        return {"seed": seed}
    monkeypatch.setattr(teacher, "run_teacher_game", game)
    with pytest.raises(RuntimeError, match="no automatic retries"):
        teacher.collect(cfg)
    assert len(calls) == len(set(calls)) < 2000
    assert calls.count(9331001) == 1
    manifest = json.loads((tmp_path / "teacher/manifest.json").read_text())
    assert len(manifest["errors"]) == 1


def test_logged_command_records_one_failure_and_refuses_retry(tmp_path, monkeypatch):
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=7)
    monkeypatch.setattr(teacher.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="exited 7"):
        teacher.logged_command(tmp_path, "example", ["not-executed"])
    assert json.loads((tmp_path / "example.command.json").read_text())["returncode"] == 7
    with pytest.raises(FileExistsError):
        teacher.logged_command(tmp_path, "example", ["not-executed"])
    assert len(calls) == 1


@pytest.mark.parametrize("fail", [False, True])
def test_evaluation_binds_new_config_and_restores_frozen_helper(tmp_path, monkeypatch, fail):
    cfg = config(tmp_path)
    new_path = tmp_path / "new-config.json"
    original = teacher.common.DEFAULT_CONFIG
    monkeypatch.setattr(teacher, "verify_identities", lambda _: None)
    def evaluate(actual, phase):
        assert actual is cfg and phase == "smoke"
        assert teacher.common.DEFAULT_CONFIG == new_path
        if fail:
            raise RuntimeError("fixture")
        return {"status": "mock-only"}
    monkeypatch.setattr(teacher.common, "evaluate", evaluate)
    if fail:
        with pytest.raises(RuntimeError):
            teacher.evaluate(cfg, "smoke", new_path)
    else:
        assert teacher.evaluate(cfg, "smoke", new_path) == {"status": "mock-only"}
    assert teacher.common.DEFAULT_CONFIG == original


@pytest.mark.parametrize("rate", [.49, .5])
def test_confirmation_does_not_run_at_or_below_half(tmp_path, monkeypatch, rate):
    cfg = config(tmp_path)
    monkeypatch.setattr(teacher, "verify_identities", lambda _: None)
    (tmp_path / "screen").mkdir()
    (tmp_path / "screen/summary.json").write_text(json.dumps({"status": "VALID", "total_games": 256, "score_rate": rate}))
    with pytest.raises(AssertionError, match="confirmation prohibited"):
        teacher.evaluate(cfg, "confirmation", tmp_path / "new-config.json")
    assert not (tmp_path / "confirmation").exists()
