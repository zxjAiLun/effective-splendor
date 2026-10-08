"""Fault injection only: the process boundary is mocked; no engine is launched."""
import copy
from pathlib import Path
import time
import unittest
from unittest.mock import Mock, patch

from scripts import prism_eval_failure_guard as guard
from training.prism.tests import test_ppo_fixed_eval as fixtures


class FailureGuardTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.FixedEvalTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.fixture.config["seeds"].append(943002)
        self.fixture.write_config()
        self.output = self.fixture.root / "guard"
        self.policy = dict(format=guard.FORMAT, max_games=4, max_safety_failures=1,
                           deadline_unix=time.time() + 600, automatic_game_retries=0,
                           supervisor_identity="synthetic-test-supervisor")
        self.policy_path = self.fixture.root / "policy.json"
        self.calls = []

    def prepare(self):
        guard.fixed.atomic_json(self.policy_path, self.policy)
        return guard.prepare(self.fixture.config_path, self.policy_path, self.output)

    def runner(self, failures=None):
        failures = failures or {}

        def execute(argv, **kwargs):
            index = len(self.calls)
            self.calls.append(argv)
            if index in failures:
                return Mock(returncode=1, stdout=b"", stderr=failures[index])
            return self.fixture.fake_run(argv, **kwargs)
        return execute

    def run_batch(self, failures=None):
        with patch.object(guard.fixed.subprocess, "run", side_effect=self.runner(failures)):
            return guard.run(self.output, before_game=lambda: None)

    @staticmethod
    def safety():
        return b"error: engine internal error: match exceeded ply safety limit\n"

    def test_prepare_is_zero_dispatch_and_refuses_existing_directory(self):
        with patch.object(guard.fixed.subprocess, "run") as launch:
            self.prepare()
            launch.assert_not_called()
        with self.assertRaises(FileExistsError):
            self.prepare()

    def test_complete_batch_and_read_only_inspect(self):
        self.prepare()
        result = self.run_batch()
        self.assertEqual(len(self.calls), 4)
        self.assertEqual(result["execution_state"], "FINISHED")
        self.assertEqual(result["grid_state"], "COMPLETE")
        self.assertTrue(result["formal_grid_eligible"])
        with patch.object(guard.fixed.subprocess, "run") as launch:
            self.assertEqual(guard.inspect(self.output), result)
            launch.assert_not_called()
        self.assertEqual(result["rule_replay_audit"], "NOT_RUN")

    def test_safety_failure_keeps_gap_and_runs_next_unique_keys(self):
        self.prepare()
        result = self.run_batch({1: self.safety()})
        self.assertEqual(len(self.calls), 4)
        self.assertEqual(result["execution_state"], "FINISHED")
        self.assertEqual(result["completed_games"], 3)
        self.assertEqual(result["grid_state"], "INCOMPLETE")
        self.assertFalse(result["formal_grid_eligible"])
        self.assertEqual(result["complete_seed_pairs"], {"parent/greedy": 1})
        self.assertEqual(result["automatic_game_retries"], 0)
        ledger = guard.fixed.read_json(self.output / "ledger.json")
        failure = ledger["entries"][result["missing_keys"][0]]
        self.assertEqual(failure["kind"], "PLY_SAFETY_LIMIT")
        self.assertNotIn("row", failure)
        self.assertEqual(guard.inspect(self.output), result)
        self.assertEqual(len({a[a.index("--config") + 1] for a in self.calls}), 4)

    def test_failure_budget_exhaustion_stops_with_unattempted_keys(self):
        self.policy["max_safety_failures"] = 0
        self.prepare()
        with self.assertRaisesRegex(ValueError, "failure budget exhausted"):
            self.run_batch({0: self.safety()})
        result = guard.inspect(self.output)
        self.assertEqual(result["execution_state"], "STOPPED")
        self.assertEqual(len(result["pending_keys"]), 3)
        self.assertEqual(len(self.calls), 1)

    def test_unknown_error_containing_safety_words_still_stops(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError, "run-match failed"):
            self.run_batch({0: self.safety() + b"illegal action\n"})
        self.assertEqual(len(self.calls), 1)
        entry = next(iter(guard.fixed.read_json(self.output / "ledger.json")["entries"].values()))
        self.assertEqual(entry["kind"], "UNKNOWN_FAILURE")

    def test_game_wall_timeout_never_continues(self):
        self.prepare()
        with patch.object(guard.fixed.subprocess, "run",
                          side_effect=guard.fixed.subprocess.TimeoutExpired("synthetic", 5)) as launch:
            with self.assertRaisesRegex(ValueError, "wall timeout"):
                guard.run(self.output, before_game=lambda: None)
            self.assertEqual(launch.call_count, 1)
        self.assertEqual(guard.inspect(self.output)["execution_state"], "STOPPED")

    def test_second_run_cannot_respawn_failed_or_completed_games(self):
        self.prepare()
        self.run_batch({1: self.safety()})
        before = (self.output / "ledger.json").read_bytes()
        with patch.object(guard.fixed.subprocess, "run") as launch:
            with self.assertRaisesRegex(ValueError, "already dispatched"):
                guard.run(self.output, before_game=lambda: None)
            launch.assert_not_called()
        self.assertEqual(before, (self.output / "ledger.json").read_bytes())

    def test_crash_lock_is_retained_and_second_writer_rejected(self):
        self.prepare()
        (self.output / "writer.lock").write_text("orphan writer", encoding="ascii")
        with patch.object(guard.fixed.subprocess, "run") as launch:
            with self.assertRaises(FileExistsError):
                guard.run(self.output, before_game=lambda: None)
            launch.assert_not_called()
        self.assertTrue((self.output / "writer.lock").exists())

    def test_supervisor_stop_is_not_a_draw_or_game_attempt(self):
        self.prepare()
        with patch.object(guard.fixed.subprocess, "run") as launch:
            with self.assertRaisesRegex(ValueError, "resource limit"):
                guard.run(self.output, before_game=Mock(side_effect=ValueError("resource limit")))
            launch.assert_not_called()
        result = guard.inspect(self.output)
        self.assertEqual(result["completed_games"], 0)
        self.assertEqual(len(result["pending_keys"]), 4)

    def test_deadline_checked_before_dispatch(self):
        self.prepare()
        with patch.object(guard.time, "time", return_value=self.policy["deadline_unix"]), \
             patch.object(guard.fixed.subprocess, "run") as launch:
            with self.assertRaisesRegex(ValueError, "deadline"):
                guard.run(self.output, before_game=lambda: None)
            launch.assert_not_called()

    def test_missing_supervisor_is_rejected(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError, "callback"):
            guard.run(self.output, before_game=None)
        self.assertFalse((self.output / "ledger.json").exists())

    def test_interrupt_preserves_dispatched_key_without_score(self):
        self.prepare()
        with patch.object(guard.fixed.subprocess, "run", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                guard.run(self.output, before_game=lambda: None)
        result = guard.inspect(self.output)
        self.assertEqual(result["execution_state"], "STOPPED")
        self.assertEqual(len(result["interrupted_keys"]), 1)
        self.assertEqual(result["completed_games"], 0)

    def test_safety_words_with_report_or_wrong_identity_are_not_continuable(self):
        self.prepare()
        self.run_batch({0: self.safety()})
        job = guard.jobs(self.fixture.config)[0]
        path = guard.game_directory(self.output / "evaluation", job)
        entry = guard.fixed.read_json(path / "game.json")
        guard.fixed.atomic_json(path / "report.json", {"outcome": "unknown"})
        self.assertEqual(guard.classify_failure(path, entry, guard.fixed._game_key(*job), job),
                         "UNKNOWN_FAILURE")
        # A failure from another key is not evidence for this key.
        wrong_job = (*job[:2], job[2] + 1, job[3])
        self.assertEqual(guard.classify_failure(path, entry, guard.fixed._game_key(*wrong_job), wrong_job),
                         "UNKNOWN_FAILURE")

    def test_orphan_evaluation_directory_is_not_adopted(self):
        self.prepare()
        (self.output / "evaluation").mkdir()
        with self.assertRaisesRegex(ValueError, "already dispatched"):
            guard.run(self.output, before_game=lambda: None)

    def test_source_snapshot_config_policy_drift_rejected(self):
        self.prepare()
        targets = [self.output / "source" / guard.SOURCES[0],
                   self.output / "config.json", self.output / "policy.json"]
        for path in targets:
            old = path.read_bytes()
            try:
                if path.suffix == ".py":
                    path.write_bytes(old + b"\n# drift\n")
                else:
                    data = guard.fixed.read_json(path)
                    data["drift"] = True
                    guard.fixed.atomic_json(path, data)
                with self.subTest(path=path), self.assertRaisesRegex(ValueError, "drift"):
                    guard.run(self.output, before_game=lambda: None)
            finally:
                path.write_bytes(old)

    def test_completed_and_failed_evidence_drift_rejected(self):
        self.prepare()
        self.run_batch({1: self.safety()})
        for pattern in ("**/replay.json", "**/stderr.log"):
            path = next((self.output / "evaluation").glob(pattern))
            original = path.read_bytes()
            try:
                path.write_bytes(original + b"drift")
                with self.assertRaisesRegex(ValueError, "artifact drift"):
                    guard.inspect(self.output)
            finally:
                path.write_bytes(original)

    def test_grid_rejects_duplicate_row_identity_and_scores(self):
        self.prepare()
        self.run_batch()
        entries = guard.fixed.read_json(self.output / "ledger.json")["entries"]
        keys = list(entries)
        for field, value in (("seed", 123), ("candidate_seat", True),
                             ("candidate_score", .25), ("record", "draw")):
            invalid = copy.deepcopy(entries)
            invalid[keys[0]]["row"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                guard.grid_status(self.fixture.config, invalid, "FINISHED")
        invalid = copy.deepcopy(entries)
        invalid[keys[1]] = copy.deepcopy(invalid[keys[0]])
        with self.assertRaisesRegex(ValueError, "identity"):
            guard.grid_status(self.fixture.config, invalid, "FINISHED")
        invalid = copy.deepcopy(entries)
        invalid[keys[0]]["row"]["candidate_score"] = 0
        invalid[keys[0]]["row"]["record"] = "loss"
        ledger_path = self.output / "ledger.json"
        ledger = guard.fixed.read_json(ledger_path)
        ledger["entries"] = invalid
        guard.fixed.atomic_json(ledger_path, ledger)
        with self.assertRaisesRegex(ValueError, "ledger/game row drift"):
            guard.inspect(self.output)

    def test_real_saved_m67_safety_record_is_classified_without_execution(self):
        directory = guard.ROOT / (
            "local-artifacts/prism/m67-alpha-repeat/r2-failure-harvest-20261007/"
            "evaluation/a-common/shards/shard-00201/games/candidate-a/general/seed-9831381-seat-0")
        if not directory.exists():
            self.skipTest("local historical artifact not distributed")
        job = ("candidate-a", "general", 9831381, 0)
        with patch.object(guard.fixed.subprocess, "run") as launch:
            result = guard.classify_failure(directory, guard.fixed.read_json(directory / "game.json"),
                                            guard.fixed._game_key(*job), job)
            self.assertEqual(result, "PLY_SAFETY_LIMIT")
            launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
