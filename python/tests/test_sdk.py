"""Python 环境、协议运行时与原生裁判的接入测试。"""

import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from splendor_env import SplendorEnv, run_agent

ROOT = Path(__file__).resolve().parents[2]
BINARY = Path(os.environ.get("SPLENDOR_EXECUTABLE", ROOT / "target" / "debug" /
                             ("splendor.exe" if os.name == "nt" else "splendor"))).resolve()


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.env = SplendorEnv(BINARY)
        self.addCleanup(self.env.close)

    def test_reset_and_catalog(self):
        first = self.env.reset(seed=42, player_count=3)
        self.assertEqual(first, self.env.reset(seed=42, player_count=3))
        self.assertEqual(first["observation"]["public"]["player_count"], 3)
        catalog = self.env.catalog()
        self.assertEqual(len(catalog["cards"]), 90)
        self.assertEqual(len(catalog["nobles"]), 10)
        self.assertEqual(catalog["color_order"], ["White", "Blue", "Green", "Red", "Black"])

    def test_illegal_action_does_not_change_state(self):
        state = self.env.reset(seed=42)
        with self.assertRaises(ValueError):
            self.env.step({"type": "pass"})
        self.assertEqual(state, self.env.observe(0))
        with self.assertRaises(ValueError):
            self.env.observe(2)
        self.assertEqual(state, self.env.observe(0))

    def test_blind_reserve_and_projected_history(self):
        state = self.env.reset(seed=42)
        action = next(a for a in state["legal_actions"] if a["type"] == "reserve_deck")
        opponent = self.env.step(action)
        owner = self.env.observe(0)
        self.assertEqual(opponent["current_player"], 1)
        self.assertEqual(len(owner["observation"]["private"]["reserved"]), 1)
        self.assertEqual(owner["legal_actions"], [])
        self.assertEqual(opponent["observation"]["public"]["players"][0]["public_reserved"], [])
        reserve = next(e for e in opponent["visible_history"] if e["type"] == "card_reserved")
        self.assertIsNone(reserve["card"])
        self.assertNotIn("seed", opponent["visible_history"][0])

    def test_reset_after_step_and_invalid_reset(self):
        initial = self.env.reset(seed=7, player_count=4)
        after = self.env.step(initial["legal_actions"][0])
        with self.assertRaises(ValueError):
            self.env.reset(seed=7, player_count=1)
        self.assertEqual(after, self.env.observe(after["current_player"]))
        self.assertEqual(initial, self.env.reset(seed=7, player_count=4))

    def test_close_stops_process(self):
        self.env.reset()
        self.env.close()
        self.assertEqual(self.env._process.poll(), 0)
        with self.assertRaises(RuntimeError):
            self.env.reset()


class AgentTests(unittest.TestCase):
    def transcript(self):
        meta = {"protocol_version": "0.5", "game_id": "test", "recipient_player_id": 0}
        return [
            {"type": "hello", "protocol_version": "0.5", "game_id": "test"},
            {"type": "game_start", **meta},
            {"type": "event", **meta, "event": {"type": "game_started", "player_count": 2}},
            {"type": "observation", **meta, "observation_hash": "view",
             "observation": {"viewer": 0}},
            {"type": "request_action", **meta, "observation_hash": "view", "request_id": 4,
             "deadline_ms": 1000, "legal_actions": [{"type": "pass"}]},
            {"type": "ping", **meta},
            {"type": "game_end", **meta, "result": {"winners": [0]}},
        ]

    def drive(self, transcript, policy=None):
        output = io.StringIO()
        result = run_agent(policy or (lambda decision: decision.legal_actions[0]),
                           name="test-agent", input_stream=io.StringIO(
                               "".join(json.dumps(m) + "\n" for m in transcript)),
                           output_stream=output)
        return result, [json.loads(line) for line in output.getvalue().splitlines()]

    def test_handshake_action_and_history(self):
        decisions = []
        def policy(decision):
            decisions.append(decision)
            return decision.legal_actions[0]
        result, replies = self.drive(self.transcript(), policy)
        self.assertEqual(result["type"], "game_end")
        self.assertEqual([r["type"] for r in replies], ["hello", "action", "pong"])
        self.assertEqual(replies[1], {"type": "action", "protocol_version": "0.5",
                                    "game_id": "test", "request_id": 4, "action": {"type": "pass"}})
        self.assertEqual(decisions[0].visible_history[0]["type"], "game_started")

    def test_wrong_view_or_seat_or_repeated_request(self):
        for field, value in [("observation_hash", "wrong"), ("recipient_player_id", 1),
                             ("game_id", "other")]:
            transcript = self.transcript()
            transcript[4][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.drive(transcript)
        transcript = self.transcript()
        transcript.insert(5, copy.deepcopy(transcript[4]))
        with self.assertRaises(ValueError):
            self.drive(transcript)

    def test_policy_must_choose_legal_action(self):
        with self.assertRaises(ValueError):
            self.drive(self.transcript(), lambda decision: {"type": "buy_reserved", "slot": 0})

    def test_eof_is_not_a_game_result(self):
        with self.assertRaises(EOFError):
            self.drive(self.transcript()[:-1])

    def test_truncation_is_distinct_from_terminal(self):
        transcript = self.transcript()
        transcript[-1] = {**transcript[-1], "type": "game_truncated"}
        del transcript[-1]["result"]
        result, _ = self.drive(transcript)
        self.assertEqual(result["type"], "game_truncated")
        self.assertNotIn("result", result)


class CliInteropTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="splendor-sdk-")
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.environment = {**os.environ, "PYTHONPATH": str(ROOT / "python")}

    def command(self, *args, expected=0):
        process = subprocess.run([str(BINARY), *map(str, args)], text=True, encoding="utf-8",
                                 capture_output=True, timeout=30, env=self.environment)
        self.assertEqual(process.returncode, expected, process.stderr)
        return process

    def save(self, name, value):
        path = self.directory / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def agents(self):
        return [{"program": str(BINARY), "args": ["agent-random", "--seed", "1"]},
                {"program": sys.executable, "args": ["-m", "splendor_env.random_agent", "--seed", "2"]}]

    def limits(self):
        return {"handshake_timeout_ms": 10000, "move_timeout_ms": 2000, "shutdown_grace_ms": 2000}

    def test_python_agent_and_rust_agent_share_verified_replay(self):
        config = self.save("match.json", {"game_id": "接入验收", "seed": 42,
                                         **self.limits(), "agents": self.agents()})
        report, replay = self.directory / "report.json", self.directory / "replay.json"
        process = self.command("run-match", "--config", config, "--report-out", report,
                               "--replay-out", replay)
        self.assertEqual(json.loads(process.stdout)["status"], "completed")
        self.command("verify-replay", "--input", replay)
        original = report.read_bytes()
        self.command("run-match", "--config", config, "--report-out", report,
                     "--replay-out", replay, expected=1)
        self.assertEqual(report.read_bytes(), original)

    def test_eval_rotates_both_agents(self):
        plan = self.save("plan.json", {"format": "effective-splendor-evaluation-plan", "version": 1,
                                      "evaluation_id": "sdk-eval", "game_seeds": [42], **self.limits(),
                                      "agents": [{"id": name, "command": command}
                                                 for name, command in zip(["rust", "python"], self.agents())]})
        output = self.directory / "evaluation"
        self.command("eval", "--plan", plan, "--out-dir", output)
        report = json.loads((output / "eval-report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["scheduled_matches"], 2)
        self.assertEqual(len(report["records"]), 2)
        self.assertEqual([row["agent_ids_by_seat"] for row in report["records"]],
                         [["rust", "python"], ["python", "rust"]])
        for agent in report["agents"]:
            self.assertEqual(agent["completed_matches"], 2)
            self.assertEqual(agent["aborted_matches"], 0)


if __name__ == "__main__":
    unittest.main()
