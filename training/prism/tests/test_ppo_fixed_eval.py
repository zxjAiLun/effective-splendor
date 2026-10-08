"""Stdlib evaluator contract tests; all matches are synthetic/mocked."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import prism_ppo_fixed_eval as evaluator


class FixedEvalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config_path = self.root / "fixed.json"
        self.output = self.root / "eval"
        self.config = self.make_config()
        self.write_config()

    def tearDown(self):
        self.temp.cleanup()

    def asset(self, name, payload):
        path = self.root / name
        path.write_bytes(payload)
        return {"path": str(path), "sha256": hashlib.sha256(payload).hexdigest()}

    def make_config(self):
        engine = self.asset("engine.exe", b"fake engine")
        candidate_program = self.asset("candidate.exe", b"candidate binary")
        opponent_program = self.asset("opponent.exe", b"opponent binary")
        weights = self.asset("weights.json", b"synthetic pinned weights")
        return {
            "format": evaluator.FORMAT,
            "engine": {"program": engine["path"], "sha256": engine["sha256"]},
            "catalog_fingerprint": "synthetic-catalog-v1",
            "action_seed": 54010001,
            "seeds": [943001],
            "candidates": {
                "parent": {"program": candidate_program["path"],
                           "sha256": candidate_program["sha256"],
                           "args": ["agent-prism-sample", "--weights", weights["path"],
                                    "--seed", "54010001"], "files": [weights]},
            },
            "opponents": {
                "greedy": {"program": opponent_program["path"],
                           "sha256": opponent_program["sha256"],
                           "args": ["agent-heuristic-v02", "--seed", "20260926"], "files": []},
            },
            "timeouts": {"game_wall_seconds": 5, "handshake_timeout_ms": 1000,
                         "move_timeout_ms": 1000, "shutdown_grace_ms": 100},
        }

    def write_config(self):
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")

    def fake_run(self, argv, *, cwd, stdout, stderr, timeout, check, shell):
        self.assertFalse(shell)
        self.assertFalse(check)
        self.assertEqual(timeout, 5)
        match_config = evaluator.read_json(argv[argv.index("--config") + 1])
        report_path = Path(argv[argv.index("--report-out") + 1])
        replay_path = Path(argv[argv.index("--replay-out") + 1])
        game_id, seed = match_config["game_id"], match_config["seed"]
        candidate_seat = next(i for i, agent in enumerate(match_config["agents"])
                              if agent["args"][0] == "agent-prism-sample")
        if candidate_seat == 0:
            result = {"scores": [15, 10], "ranks": [0, 1], "winners": [0],
                      "reason": "prestige_threshold"}
        else:
            result = {"scores": [10, 10], "ranks": [0, 0], "winners": [0, 1],
                      "reason": "stalemate"}
        final_hash = f"{seed:064x}"[-64:]
        report = {"format": "effective-splendor-arena-report", "version": 1,
                  "game_id": game_id, "ruleset_fingerprint": self.config["catalog_fingerprint"],
                  "player_count": 2,
                  "agents": [{"seat": i, "agent_name": "prism-sample" if i == candidate_seat else "greedy",
                              "agent_version": "0.1.0" if i == candidate_seat else "1"}
                             for i in range(2)],
                  "outcome": {"status": "completed", "result": result, "completed_plies": 2,
                              "replay_final_hash": final_hash}}
        replay = {"format": "effective-splendor-replay", "version": 1, "seed": seed,
                  "player_count": 2, "ruleset_fingerprint": self.config["catalog_fingerprint"],
                  "steps": [{"ply": 0}, {"ply": 1}], "final_state_hash": final_hash,
                  "result": result}
        report_path.write_text(json.dumps(report), encoding="utf-8")
        replay_path.write_text(json.dumps(replay), encoding="utf-8")
        return mock.Mock(returncode=0, stdout=b"synthetic stdout\n", stderr=b"")

    def test_aggregate_wins_draws_losses_seats_and_paired_parent_delta(self):
        config = copy.deepcopy(self.config)
        config["candidates"]["candidate"] = copy.deepcopy(config["candidates"]["parent"])
        validated = evaluator.validate_config(config, self.config_path)
        validated["config_sha256"] = evaluator.canonical_hash(config)
        rows = [
            {"candidate": candidate, "opponent": "greedy", "seed": seed,
             "candidate_seat": seat, "record": record, "candidate_score": score,
             "candidate_points": points, "opponent_points": 10, "plies": 20 + seat}
            for candidate, outcomes in (("parent", [(943001, 0, "win", 1.0),
                                                         (943001, 1, "loss", 0.0),
                                                         (943002, 0, "draw", 0.5),
                                                         (943002, 1, "win", 1.0)]),
                                         ("candidate", [(943001, 0, "loss", 0.0),
                                                            (943001, 1, "win", 1.0),
                                                            (943002, 0, "draw", 0.5),
                                                            (943002, 1, "draw", 0.5)]))
            for seed, seat, record, score in outcomes
            for points in [15 if score else 10]
        ]
        validated["config"]["seeds"] = [943001, 943002]
        result = evaluator.aggregate(validated, rows)
        parent = result["candidate_opponent"]["parent"]["greedy"]
        self.assertEqual((parent["games"], parent["wins"], parent["draws"], parent["losses"]),
                         (4, 2, 1, 1))
        self.assertEqual(parent["score_rate"], 0.625)
        self.assertEqual(parent["per_seed_score_rate"], [0.5, 0.75])
        self.assertEqual(parent["seat"]["0"]["wins"], 1)
        self.assertAlmostEqual(result["candidate_minus_first_parent"]["candidate"]["mean_delta_score_rate"], -0.125)
        self.assertEqual(result["verdict"], "DEVELOPMENT_ONLY_NOT_PROMOTED")

    def test_mocked_games_resume_without_duplicate_spawn_and_common_game_ids(self):
        calls = []

        def runner(*args, **kwargs):
            calls.append(args[0])
            return self.fake_run(*args, **kwargs)

        with mock.patch.object(evaluator.subprocess, "run", side_effect=runner):
            first = evaluator.run_eval(self.config_path, self.output)
            second = evaluator.run_eval(self.config_path, self.output)
        self.assertEqual(first, second)
        self.assertEqual(first["games"], 2)
        self.assertEqual(first["candidate_opponent"]["parent"]["greedy"]["score_rate"], 0.75)
        progress = evaluator.read_json(self.output / "progress.json")
        self.assertEqual(len(progress["games"]), 2)
        ids = [row["game_id"] for row in progress["games"].values()]
        self.assertEqual(len(set(ids)), 2)
        self.assertTrue(all("parent" not in game_id for game_id in ids))
        self.assertEqual((self.output / "games/parent/greedy/seed-943001-seat-0/stdout.log").read_text(),
                         "synthetic stdout\n")

    def test_config_drift_rejected_before_spawn(self):
        with mock.patch.object(evaluator.subprocess, "run", side_effect=self.fake_run):
            evaluator.run_eval(self.config_path, self.output)
        changed = copy.deepcopy(self.config)
        changed["timeouts"]["move_timeout_ms"] += 1
        changed_path = self.root / "changed.json"
        changed_path.write_text(json.dumps(changed), encoding="utf-8")
        with mock.patch.object(evaluator.subprocess, "run") as spawn:
            with self.assertRaisesRegex(ValueError, "config drift"):
                evaluator.run_eval(changed_path, self.output)
        spawn.assert_not_called()

    def test_nonterminal_or_failed_match_is_retained_and_never_retried(self):
        calls = []

        def aborted(argv, **kwargs):
            calls.append(argv)
            return mock.Mock(returncode=2, stdout=b"partial out", stderr=b"partial err")

        with mock.patch.object(evaluator.subprocess, "run", side_effect=aborted):
            with self.assertRaisesRegex(ValueError, "run-match failed"):
                evaluator.run_eval(self.config_path, self.output)
        with mock.patch.object(evaluator.subprocess, "run") as spawn:
            with self.assertRaisesRegex(ValueError, "failed/in-progress"):
                evaluator.run_eval(self.config_path, self.output)
        spawn.assert_not_called()
        self.assertEqual(len(calls), 1)
        self.assertTrue((self.output / "games/parent/greedy/seed-943001-seat-0/stderr.log").is_file())

    def test_completed_report_rejects_nonterminal_and_report_replay_mismatch(self):
        report = {"format": "effective-splendor-arena-report", "version": 1,
                  "game_id": "g", "ruleset_fingerprint": "catalog", "player_count": 2,
                  "outcome": {"status": "aborted"}}
        with self.assertRaisesRegex(ValueError, "not normally completed"):
            evaluator._report_result(report, {}, game_id="g", seed=1, seat=0, catalog="catalog")
        result = {"scores": [15, 10], "ranks": [0, 1], "winners": [0], "reason": "prestige_threshold"}
        report["outcome"] = {"status": "completed", "result": result, "completed_plies": 1,
                             "replay_final_hash": "a" * 64}
        replay = {"format": "effective-splendor-replay", "version": 1, "seed": 1,
                  "player_count": 2, "ruleset_fingerprint": "catalog", "steps": [{}],
                  "final_state_hash": "b" * 64, "result": result}
        with self.assertRaisesRegex(ValueError, "final hash mismatch"):
            evaluator._report_result(report, replay, game_id="g", seed=1, seat=0, catalog="catalog")

    def test_result_publish_gap_recovers_without_respawning_games(self):
        with mock.patch.object(evaluator.subprocess, "run", side_effect=self.fake_run):
            original = evaluator.run_eval(self.config_path, self.output)
        completion_path = self.output / "completion.json"
        completion = evaluator.read_json(completion_path)
        completion.pop("result_sha256")
        evaluator.atomic_json(completion_path, completion)
        with mock.patch.object(evaluator.subprocess, "run") as spawn:
            recovered = evaluator.run_eval(self.config_path, self.output)
        spawn.assert_not_called()
        self.assertEqual(original, recovered)
        self.assertEqual(evaluator.read_json(completion_path)["result_sha256"],
                         evaluator.sha256_file(self.output / "result.json"))



if __name__ == "__main__":
    unittest.main()
