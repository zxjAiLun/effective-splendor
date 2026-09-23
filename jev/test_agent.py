"""Run with `python -m unittest discover -s jev -p 'test_*.py'`."""
import contextlib
import io
import json
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import agent
import build_catalog

ROOT = Path(__file__).resolve().parents[1]


class AgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = [json.loads(line) for line in (ROOT / "fixtures/protocol/v0.5/normal-game.ndjson").read_text(encoding="utf-8").splitlines()]
        cls.obs = next(x["observation"] for x in cls.fixture if x["type"] == "observation")
        cls.legal = next(x["legal_actions"] for x in cls.fixture if x["type"] == "request_action")
        cls.catalog = agent.load_catalog()

    def test_catalog_is_canonical(self):
        self.assertEqual(self.catalog, build_catalog.catalog())

    def test_only_observable_information_leaves_process(self):
        observation = json.loads(json.dumps(self.obs))
        observation["referee_deck"] = "UNREACHABLE"
        observation["private"]["hidden_opponent"] = "UNREACHABLE"
        payload, offered = agent.question(observation, self.legal, self.catalog)
        text = json.dumps(payload)
        self.assertNotIn("UNREACHABLE", text)
        self.assertNotIn("observation_hash", text)
        self.assertNotIn("seed", text)
        self.assertNotIn("ruleset_fingerprint", text)
        self.assertEqual(len(offered), len(self.legal))
        self.assertEqual(payload["state"]["market"][0][0]["id"], self.obs["public"]["market"][0][0])

    def test_choice_maps_to_exact_legal_action(self):
        action, usage, count = agent.pick(self.obs, self.legal, self.catalog,
            lambda payload: {"answers": {"move": {"type": "choice", "choice": "a9"}},
                             "usage": {"input_tokens": 123, "output_tokens": 10}})
        self.assertEqual(action, self.legal[9])
        self.assertEqual(usage["input_tokens"], 123)
        self.assertEqual(count, 30)

    def test_rejects_invalid_model_response_and_does_not_substitute_heuristic(self):
        for result in ({"answers": {"move": {"type": "choice", "choice": "a999"}}},
                       {"answers": {"move": {"type": "score", "choice": "a0"}}},
                       {"answers": {}}, {}, []):
            with self.subTest(result=result), self.assertRaises(agent.AgentFault):
                agent.pick(self.obs, self.legal, self.catalog, lambda _: result)

    def test_singleton_skips_api_and_many_actions_are_bounded(self):
        chosen, usage, size = agent.pick(self.obs, [self.legal[0]], self.catalog,
                                         lambda _: self.fail("singleton must not call API"))
        self.assertEqual((chosen, usage, size), (self.legal[0], None, 1))
        many = self.legal * 5
        offered = agent.candidates(many)
        self.assertEqual(len(offered), agent.MAX_OPTIONS)
        self.assertTrue(all(a in many for a in offered))
        self.assertTrue(any(a["type"] == "take_tokens" for a in offered))
        self.assertTrue(any(a["type"] == "reserve_market" for a in offered))
        noop = {"type": "take_tokens", "take": self.legal[0]["take"], "return": self.legal[0]["take"]}
        self.assertNotIn(noop, agent.candidates([noop, self.legal[0]]))
        self.assertEqual(agent.candidates([noop]), [noop])

    def test_protocol_round_trip_and_request_correlation(self):
        end = {"type": "game_end", "protocol_version": "0.5", "game_id": self.fixture[0]["game_id"],
               "recipient_player_id": 0, "result": {}}
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            metrics = agent.run([json.dumps(x) for x in [*self.fixture, end]],
                lambda _: {"model": "jev-1.13.0", "answers": {"move": {"type": "choice", "choice": "a3"}},
                           "usage": {"input_tokens": 50, "output_tokens": 5}})
        emitted = [json.loads(x) for x in output.getvalue().splitlines()]
        self.assertEqual([x["type"] for x in emitted], ["hello", "action"])
        self.assertEqual(emitted[1]["action"], self.legal[3])
        self.assertEqual(emitted[1]["request_id"], self.fixture[-1]["request_id"])
        self.assertEqual(metrics["api_calls"], 1)
        self.assertEqual(metrics["input_tokens"], 50)
        self.assertEqual(metrics["model_version"], "jev-1.13.0")
        corrupted = [dict(x) for x in self.fixture]
        corrupted[-1]["observation_hash"] = "wrong"
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(agent.AgentFault, "request observation"):
            agent.run([json.dumps(x) for x in corrupted])

    def test_http_error_does_not_log_remote_body_or_key(self):
        with patch.dict("os.environ", {"TYPESAFE_API_KEY": "fake-test-key"}), patch.object(
            agent.urllib.request, "urlopen", side_effect=urllib.error.HTTPError(
                agent.API_URL, 429, "SENSITIVE REMOTE BODY", {}, io.BytesIO(b"SENSITIVE REMOTE BODY"))
        ):
            with self.assertRaises(agent.AgentFault) as caught:
                agent.evaluate({"state": "test"})
            self.assertEqual(str(caught.exception), "TypeSafe HTTP 429")

    def test_credential_only_read_on_http_not_in_state(self):
        with patch.dict("os.environ", {"TYPESAFE_API_KEY": "fake-test-key"}):
            self.assertEqual(agent.credential(), "fake-test-key")
            payload, _ = agent.question(self.obs, self.legal, self.catalog)
            self.assertNotIn("fake-test-key", json.dumps(payload))


if __name__ == "__main__":
    unittest.main()
