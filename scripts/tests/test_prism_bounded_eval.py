"""Synthetic process-boundary integration tests: zero games or model inference."""
import copy
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

from scripts import prism_bounded_eval as bounded
from training.prism.tests.test_ppo_fixed_eval import FixedEvalTests


def trace(seed, catalog, actions, *, capped=False):
    steps = [{"ply": i, "actor": actor, "action": action,
              "state_hash_before": f"{i:064x}", "state_hash_after": f"{i+1:064x}"}
             for i, (actor, action) in enumerate(actions)]
    return {"format": "splendor-rollout-prefix" if capped else "effective-splendor-replay",
            "version": 1, "player_count": 2, "seed": seed, "ruleset_fingerprint": catalog,
            "initial_state_hash": f"{0:064x}", "steps": steps,
            "cap_state_hash" if capped else "final_state_hash": f"{len(steps):064x}",
            **({"ply_cap": len(steps)} if capped else {})}


class BoundedEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = FixedEvalTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.fixture.config["seeds"].append(943002)
        self.fixture.config["candidates"]["parent"]["args"][0] = "agent-prism"
        self.fixture.write_config()
        self.output = self.fixture.root / "bounded"
        self.policy_path = self.fixture.root / "policy.json"
        self.policy = dict(format=bounded.FORMAT, max_games=4, max_truncated_games=1,
                           ply_cap=8, deadline_unix=time.time() + 600, cpu_seconds=100,
                           memory_bytes=256*1024**2, storage_bytes=16*1024**2,
                           max_processes=8, automatic_game_retries=0)
        self.calls = []
        self.noop = {"type": "take_tokens", "take": {"red": 1}, "return": {"red": 1}}

    def prepare(self):
        bounded.write(self.policy_path, self.policy)
        return bounded.prepare(self.fixture.config_path, self.policy_path, self.output)

    def launch(self, outcomes=None, mutate=None, resource=None):
        outcomes = outcomes or {}

        def launch(argv, directory, output, validated, policy, remaining):
            index = len(self.calls)
            self.calls.append(argv)
            self.assertEqual(argv[1], "run-rollout")
            self.assertEqual(int(argv[argv.index("--max-plies")+1]), policy["ply_cap"])
            config = bounded.read(directory / "match-config.json")
            commands = config["agents"]
            self.assertEqual(sum(c["args"][0] == "agent-prism" for c in commands), 1)
            capped = outcomes.get(index) == "cap"
            actions = [(i % 2, copy.deepcopy(self.noop)) for i in range(8 if capped else 2)]
            data = trace(config["seed"], validated["config"]["catalog_fingerprint"], actions, capped=capped)
            if capped:
                outcome = {"status": "truncated", "completed_plies": 8,
                           "cap_state_hash": data["cap_state_hash"], "cap_scores": [10, 5]}
                filename = "prefix.json"
            else:
                result = {"scores": [15, 5], "ranks": [0, 1], "winners": [0], "reason": "prestige_threshold"}
                data["result"] = result
                outcome = {"status": "completed", "completed_plies": 2,
                           "replay_final_hash": data["final_state_hash"], "result": result}
                filename = "replay.json"
            report = {"format": "effective-splendor-arena-report", "version": 1,
                      "game_id": config["game_id"], "player_count": 2,
                      "ruleset_fingerprint": data["ruleset_fingerprint"], "outcome": outcome}
            if mutate:
                mutate(report, data, index)
            bounded.write(directory / filename, data)
            bounded.write(directory / "report.json", report)
            (directory / "stdout.log").write_text("synthetic fixture", encoding="utf-8")
            (directory / "stderr.log").write_text("", encoding="utf-8")
            return resource or {"returncode": 0, "stop_reason": None, "cpu_seconds": .2}
        return launch

    def run_batch(self, **kwargs):
        with patch.object(bounded, "launch", side_effect=self.launch(**kwargs)):
            return bounded.run(self.output)

    def test_prepare_zero_dispatch_and_exclusive(self):
        with patch.object(bounded, "launch") as launch:
            self.prepare()
            launch.assert_not_called()
        with self.assertRaises(FileExistsError):
            self.prepare()

    def test_completed_grid_and_inspect_without_launch(self):
        self.prepare()
        result = self.run_batch()
        self.assertEqual(result["completed_games"], 4)
        self.assertEqual(result["grid_state"], "COMPLETE")
        self.assertEqual(result["truncated_games"], 0)
        self.assertEqual(result["rule_replay_audit"], "NOT_RUN_INDEPENDENTLY")
        with patch.object(bounded, "launch") as launch:
            self.assertEqual(result, bounded.inspect(self.output))
            launch.assert_not_called()

    def test_complete_cap_complete_preserves_prefix_and_missing_pair(self):
        self.prepare()
        result = self.run_batch(outcomes={1: "cap"})
        self.assertEqual(len(self.calls), 4)
        self.assertEqual(result["execution_state"], "FINISHED")
        self.assertEqual(result["completed_games"], 3)
        self.assertEqual(result["completion_rate"], .75)
        self.assertEqual(result["truncated_games"], 1)
        self.assertEqual(result["complete_seed_pairs"], {"parent/greedy": 1})
        self.assertFalse(result["formal_grid_eligible"])
        ledger = bounded.read(self.output / "ledger.json")
        cap = next(e for e in ledger["entries"].values() if e.get("kind") == "PLY_CAP_TRUNCATED")
        self.assertNotIn("row", cap)
        self.assertIn("prefix.json", cap["evidence_sha256"])
        self.assertNotIn("replay.json", cap["evidence_sha256"])
        self.assertEqual(cap["metrics"]["trailing_main_without_purchase"], 8)

    def test_truncation_budget_exhaustion_stops_next_dispatch(self):
        self.policy["max_truncated_games"] = 0
        self.prepare()
        with self.assertRaisesRegex(ValueError, "truncation budget"):
            self.run_batch(outcomes={0: "cap"})
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(bounded.inspect(self.output)["pending_keys"]), 3)

    def test_resource_stop_never_continues_even_with_valid_prefix(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError, "process/resource"):
            self.run_batch(outcomes={0: "cap"},
                           resource={"returncode": 0, "stop_reason": "wall_deadline", "cpu_seconds": .2})
        self.assertEqual(len(self.calls), 1)
        result = bounded.inspect(self.output)
        self.assertEqual(result["truncated_games"], 0)
        self.assertEqual(result["consumed_cpu_seconds"], 100)

    def test_unknown_exit_stops(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError, "process/resource"):
            self.run_batch(resource={"returncode": 1, "stop_reason": None, "cpu_seconds": .2})
        self.assertEqual(len(self.calls), 1)

    def test_invalid_truncations_stop_instead_of_becoming_gaps_allowed_to_continue(self):
        changes = [
            lambda r, p: r["outcome"].update(result={"scores": [10, 5]}),
            lambda r, p: p.update(result={}),
            lambda r, p: p.update(seed=123),
            lambda r, p: p.update(ply_cap=7),
            lambda r, p: r["outcome"].update(completed_plies=True),
            lambda r, p: r.update(game_id="wrong"),
            lambda r, p: p["steps"][2].update(state_hash_before="f"*64),
            lambda r, p: p["steps"][1].update(ply=4),
            lambda r, p: p["steps"][1].update(actor=True),
            lambda r, p: r["outcome"].update(cap_state_hash="f"*64),
            lambda r, p: r.update(version=True),
            lambda r, p: p.update(version=True),
        ]
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                self.output = self.fixture.root / f"bad-{index}"
                self.prepare()
                self.calls.clear()
                with self.assertRaises(ValueError):
                    self.run_batch(outcomes={0: "cap"}, mutate=lambda r, p, i: change(r, p))
                self.assertEqual(len(self.calls), 1)
                self.assertEqual(bounded.inspect(self.output)["truncated_games"], 0)

    def test_missing_prefix_stops(self):
        self.prepare()
        runner = self.launch(outcomes={0: "cap"})
        def missing(*args):
            result = runner(*args)
            (args[1] / "prefix.json").unlink()
            return result
        with patch.object(bounded, "launch", side_effect=missing):
            with self.assertRaises(FileNotFoundError):
                bounded.run(self.output)
        self.assertEqual(len(self.calls), 1)

    def test_restart_and_orphan_dispatch_refused(self):
        self.prepare()
        self.run_batch()
        with patch.object(bounded, "launch") as launch:
            with self.assertRaisesRegex(ValueError, "existing dispatch"):
                bounded.run(self.output)
            launch.assert_not_called()
        self.output = self.fixture.root / "crashed"
        self.prepare()
        (self.output / "once-only.lock").write_text("previous owner")
        with self.assertRaises(FileExistsError):
            bounded.run(self.output)

    def test_artifact_and_ledger_drift_refused(self):
        self.prepare()
        self.run_batch(outcomes={1: "cap"})
        path = next(self.output.glob("games/**/prefix.json"))
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "artifact set/hash"):
            bounded.inspect(self.output)

    def test_cpu_total_recomputed_even_when_summary_matches_tampered_ledger(self):
        self.prepare()
        self.run_batch()
        ledger = bounded.read(self.output / "ledger.json")
        ledger["consumed_cpu_seconds"] = 0
        bounded.write(self.output / "ledger.json", ledger)
        bounded.write(self.output / "grid-status.json", bounded.summary(self.fixture.config, ledger))
        with self.assertRaisesRegex(ValueError, "ledger CPU total drift"):
            bounded.inspect(self.output)

    def test_cpu_sum_preserves_dispatch_order_for_unsorted_seed_cohort(self):
        self.fixture.config["seeds"] = [943002, 943001]
        self.fixture.write_config()
        self.prepare()
        runner = self.launch()
        cpu = iter([.1, .2, .3, .4])
        def varying(*args):
            result = runner(*args)
            result["cpu_seconds"] = next(cpu)
            return result
        with patch.object(bounded, "launch", side_effect=varying):
            result = bounded.run(self.output)
        self.assertEqual(result["consumed_cpu_seconds"], sum([.1, .2, .3, .4]))
        self.assertEqual(result, bounded.inspect(self.output))

    def test_process_command_revalidated_even_with_updated_evidence_hash(self):
        self.prepare()
        self.run_batch()
        ledger = bounded.read(self.output / "ledger.json")
        key = next(iter(ledger["entries"]))
        job = bounded.legacy.jobs(self.fixture.config)[0]
        directory = bounded.legacy.game_directory(self.output, job)
        resource = bounded.read(directory / "process-result.json")
        resource["argv"][1] = "run-match"
        bounded.write(directory / "process-result.json", resource)
        ledger["entries"][key]["evidence_sha256"] = bounded.evidence(directory)
        bounded.write(self.output / "ledger.json", ledger)
        with self.assertRaisesRegex(ValueError, "process command drift"):
            bounded.inspect(self.output)

    def test_unknown_failure_cannot_reclaim_reserved_cpu(self):
        self.prepare()
        with self.assertRaises(ValueError):
            self.run_batch(resource={"returncode": 1, "stop_reason": None, "cpu_seconds": .2})
        ledger = bounded.read(self.output / "ledger.json")
        ledger["consumed_cpu_seconds"] = .2
        bounded.write(self.output / "ledger.json", ledger)
        with self.assertRaisesRegex(ValueError, "failure CPU reservation drift"):
            bounded.inspect(self.output)

    def test_source_config_and_asset_drift_refused_before_launch(self):
        self.prepare()
        original = (self.output / "config.json").read_bytes()
        config = bounded.read(self.output / "config.json")
        config["seeds"].append(1)
        bounded.write(self.output / "config.json", config)
        with self.assertRaisesRegex(ValueError, "config drift"):
            bounded.run(self.output)
        (self.output / "config.json").write_bytes(original)
        path = self.output / "source" / bounded.SOURCES[0]
        original = path.read_bytes()
        path.write_bytes(original + b"\n")
        with self.assertRaisesRegex(ValueError, "source drift"):
            bounded.run(self.output)
        path.write_bytes(original)
        Path(self.fixture.config["engine"]["program"]).write_bytes(b"drift")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            bounded.run(self.output)
        self.assertFalse((self.output / "once-only.lock").exists())

    def test_explicit_valid_finite_policy_required(self):
        for key, value in (("ply_cap", 10000), ("ply_cap", True), ("cpu_seconds", float("nan")),
                           ("max_games", 3), ("automatic_game_retries", 1), ("max_truncated_games", 5)):
            with self.subTest(key=key):
                policy = dict(self.policy, **{key: value})
                with self.assertRaises(ValueError):
                    bounded.validate_policy(policy, self.fixture.config)

    def test_expired_deadline_prevents_dispatch(self):
        self.prepare()
        with patch.object(bounded.time, "time", return_value=self.policy["deadline_unix"] + 1):
            with self.assertRaisesRegex(ValueError, "deadline"):
                self.run_batch()
        self.assertEqual(len(self.calls), 0)

    def test_cumulative_cpu_limit_stops(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError, "CPU budget"):
            self.run_batch(resource={"returncode": 0, "stop_reason": None, "cpu_seconds": 60})
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(len(bounded.inspect(self.output)["pending_keys"]), 2)

    def test_trace_distinguishes_main_noble_buy_reserve_and_token_swap(self):
        actions = [(0, self.noop), (1, self.noop), (0, {"type": "choose_noble"}),
                   (0, self.noop), (1, {"type": "reserve_market"}),
                   (0, {"type": "buy_market"}),
                   (1, {"type": "take_tokens", "take": {"red": 1}, "return": {"green": 1}})]
        metrics = bounded.trace_metrics(trace(1, "c", actions))
        self.assertEqual(metrics["total_main"], 6)
        self.assertEqual(metrics["longest_main_without_purchase"], 4)
        self.assertEqual(metrics["trailing_main_without_purchase"], 1)
        self.assertEqual(metrics["by_actor"][0]["longest_own_token_noop_run"], 2)
        self.assertEqual(metrics["by_actor"][0]["purchases"], 1)
        self.assertEqual(metrics["by_actor"][1]["reserves"], 1)
        self.assertEqual(metrics["legal_purchase_opportunities"], "NOT_MEASURED")

    def test_saved_9999_ply_incident_progress_regression_without_inference(self):
        path = bounded.ROOT / "local-artifacts/prism/m67-alpha-repeat/r3-evidence/diagnostic/prefix.json"
        if not path.exists():
            self.skipTest("local-only historical prefix unavailable")
        self.assertEqual(bounded.sha(path),
                         "93e8ba01e140851150712b7c9bd74b32d5cc9e3872206d09e5b1a4a24b5cc452")
        metrics = bounded.trace_metrics(bounded.read(path))
        self.assertEqual(metrics["completed_plies"], 9999)
        self.assertEqual(metrics["total_main"], 9999)
        self.assertEqual(metrics["trailing_main_without_purchase"], 9964)
        self.assertEqual(metrics["longest_main_without_purchase"], 9964)
        self.assertEqual([c["purchases"] for c in metrics["by_actor"]], [3, 4])
        self.assertEqual([c["token_noops"] for c in metrics["by_actor"]], [4011, 4977])
        self.assertEqual([c["longest_own_token_noop_run"] for c in metrics["by_actor"]], [3327, 4977])
        self.assertEqual(metrics["legal_purchase_opportunities"], "NOT_MEASURED")

    def test_environment_restored_even_after_error(self):
        import os
        with patch.dict(os.environ, {"PRISM_DSW_REMAINING_WALL": "original"}):
            with self.assertRaises(RuntimeError):
                with bounded.scoped_environment({"PRISM_DSW_REMAINING_WALL": "temporary"}):
                    raise RuntimeError("synthetic")
            self.assertEqual(os.environ["PRISM_DSW_REMAINING_WALL"], "original")

    def test_hard_crash_dispatch_inspects_as_unknown_and_cannot_restart(self):
        self.prepare()
        key = bounded.fixed._game_key("parent", "greedy", 943001, 0)
        bounded.write(self.output / "ledger.json",
                      {"execution_state": "RUNNING", "entries": {key: {"state": "DISPATCHED"}},
                       "consumed_cpu_seconds": 0,
                       "manifest_sha256": bounded.sha(self.output / "manifest.json")})
        result = bounded.inspect(self.output)
        self.assertEqual(result["execution_state"], "RUNNING_UNCONFIRMED")
        self.assertEqual(result["interrupted_keys"], [key])
        self.assertEqual(len(result["pending_keys"]), 3)
        with self.assertRaisesRegex(ValueError, "existing dispatch"):
            bounded.run(self.output)

    @unittest.skipUnless(os.name == "nt", "local Windows Job Object smoke")
    def test_startup_time_deducted_from_absolute_deadline(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        self.output.mkdir()
        directory = self.output / "startup"
        directory.mkdir()
        tree = MagicMock()
        tree.__enter__.return_value = tree
        tree.start.return_value = SimpleNamespace(pid=os.getpid())
        tree.wait.return_value = {"returncode": 124, "stop_reason": "wall_deadline",
                                  "user_cpu_seconds": 0, "kernel_cpu_seconds": 0}
        validated = {"base": str(self.fixture.root), "config": {"timeouts": {"game_wall_seconds": 5}}}
        deadline = self.policy["deadline_unix"]
        with patch("training.prism_portable.engine.ppo.processes.ProcessTree", return_value=tree), \
             patch.object(bounded.time, "time", side_effect=[deadline-10, deadline+1, deadline+1]):
            bounded.launch([sys.executable, "-c", "pass"], directory, self.output,
                           validated, self.policy, 10)
        self.assertEqual(tree.wait.call_args.kwargs["wall_seconds"], 0)
        identity = bounded.read(directory / "process-identity.json")
        self.assertEqual(identity["cwd"], str(self.fixture.root.resolve()))
        self.assertTrue(identity["node"])

    @unittest.skipUnless(os.name == "nt", "local Windows Job Object smoke")
    def test_real_supervised_non_game_process_and_timeout_cleanup(self):
        import psutil
        self.output.mkdir()
        validated = {"base": str(self.fixture.root),
                     "config": {"timeouts": {"game_wall_seconds": 5}}}
        directory = self.output / "normal"
        directory.mkdir()
        result = bounded.launch([sys.executable, "-c", "print('no-game supervisor smoke')"],
                                directory, self.output, validated, self.policy, 10)
        self.assertEqual(result["returncode"], 0)
        self.assertIsNone(result["stop_reason"])
        self.assertGreaterEqual(result["cpu_seconds"], 0)
        directory = self.output / "timeout"
        directory.mkdir()
        marker = directory / "child.json"
        code = ("import subprocess,sys,time,json;from pathlib import Path;"
                "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);"
                "Path(sys.argv[1]).write_text(json.dumps({'pid':p.pid}));time.sleep(30)")
        validated["config"]["timeouts"]["game_wall_seconds"] = 1
        result = bounded.launch([sys.executable, "-c", code, str(marker)],
                                directory, self.output, validated, self.policy, 10)
        self.assertEqual(result["stop_reason"], "wall_deadline")
        self.assertTrue(marker.exists())
        self.assertFalse(psutil.pid_exists(bounded.read(marker)["pid"]))


if __name__ == "__main__":
    unittest.main()
