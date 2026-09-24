"""Core agent/protocol gates. All TypeSafe calls are mocked."""
import contextlib
import copy
import io
import json
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

import agent
import build_catalog
import transport

ROOT = Path(__file__).resolve().parents[1]


def answer(stage, choice, probabilities=None, tokens=10):
    body = {"type": "choice", "choice": choice}
    if probabilities is not None:
        body["probabilities"] = probabilities
    return {"model": "jev-1.13.0", "answers": {stage: body},
            "usage": {"input_tokens": tokens, "output_tokens": 1}}


class AgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = [json.loads(line) for line in (ROOT / "fixtures/protocol/v0.5/normal-game.ndjson").read_text(encoding="utf-8").splitlines()]
        cls.obs = next(x["observation"] for x in cls.fixture if x["type"] == "observation")
        cls.legal = next(x["legal_actions"] for x in cls.fixture if x["type"] == "request_action")
        cls.catalog = agent.load_catalog()

    def test_catalog_is_canonical(self):
        self.assertEqual(self.catalog, build_catalog.catalog())

    def test_only_facts_and_no_heuristic_helper_or_nested_leak(self):
        obs = copy.deepcopy(self.obs)
        obs["referee_deck"] = "SECRET_SENTINEL"
        obs["private"]["hidden_opponent"] = "SECRET_SENTINEL"
        payloads = []
        def fake(payload):
            payloads.append(payload)
            if "family" in payload["questions"]:
                return answer("family", "take_double")
            return answer("colors", "white", dict(zip(agent.COLORS, [.6, .2, .1, .05, .05])))
        with patch("subprocess.Popen", side_effect=AssertionError("no score helper allowed")):
            agent.pick(obs, self.legal, self.catalog, fake)
        text = json.dumps(payloads)
        for banned in ("SECRET_SENTINEL", "heuristic", "category_base", "advisory_term", "best_move_example",
                       "observation_hash", "ruleset_fingerprint", "referee_deck"):
            self.assertNotIn(banned, text)
        self.assertEqual(payloads[0]["state"]["market"][0][0]["id"], self.obs["public"]["market"][0][0])
        self.assertEqual(set(payloads[0]["questions"]["family"]["criteria"]), {"take_double", "take_distinct", "reserve"})
        self.assertEqual(set(payloads[1]["questions"]["colors"]["criteria"]), set(agent.COLORS))

    def test_protocol_budget_metrics_and_probability_mapping(self):
        end = {"type": "game_end", "protocol_version": "0.5", "game_id": self.fixture[0]["game_id"], "recipient_player_id": 0}
        responses = iter([answer("family", "take_double", tokens=20),
                          answer("colors", "red", dict(zip(agent.COLORS, [.1, .1, .1, .6, .1])), tokens=50)])
        with contextlib.redirect_stdout(io.StringIO()) as output:
            metrics = agent.run([json.dumps(x) for x in [*self.fixture, end]], lambda _, **kw: next(responses))
        emitted = [json.loads(x) for x in output.getvalue().splitlines()]
        self.assertEqual([x["type"] for x in emitted], ["hello", "action"])
        self.assertEqual(emitted[1]["action"], self.legal[3])
        self.assertEqual(emitted[1]["request_id"], self.fixture[-1]["request_id"])
        self.assertEqual(metrics["api_calls"], 2)
        self.assertEqual(metrics["stage_calls"], {"family": 1, "colors": 1})
        self.assertEqual(metrics["input_tokens"], 70)
        self.assertEqual(metrics["policy_id"], agent.POLICY_ID)
        self.assertEqual(metrics["noops_removed"], 0)
        self.assertEqual(metrics["cap_removed"], 0)
        corrupted = copy.deepcopy(self.fixture)
        corrupted[-1]["observation_hash"] = "wrong"
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(agent.AgentFault, "request observation"):
            agent.run([json.dumps(x) for x in corrupted])

    def test_singleton_skips_network(self):
        chosen, usage, size, calls = agent.pick(self.obs, [self.legal[0]], self.catalog,
                                               lambda _: self.fail("singleton must not call API"))
        self.assertEqual((chosen, usage, size, calls), (self.legal[0], None, 1, 0))

    def test_budget_does_not_send_second_request(self):
        calls = []
        def fake(payload, **kw):
            calls.append(payload)
            return answer("family", "take_double")
        with patch.dict("os.environ", {"JEV_MAX_API_CALLS": "1"}), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(agent.AgentFault, "call budget"):
                agent.run([json.dumps(x) for x in self.fixture], fake)
        self.assertEqual(len(calls), 1)

    def test_invalid_family_never_falls_back(self):
        with self.assertRaises(agent.AgentFault):
            agent.pick(self.obs, self.legal, self.catalog, lambda _: answer("family", "not_legal"))

    def test_http_error_does_not_log_remote_body_or_key(self):
        opener = Mock()
        opener.open.side_effect = urllib.error.HTTPError(agent.API_URL, 429, "SENSITIVE REMOTE BODY", {}, io.BytesIO())
        with patch.dict("os.environ", {"TYPESAFE_API_KEY": "fake-test-key"}), patch.object(
            transport.urllib.request, "build_opener", return_value=opener
        ):
            with self.assertRaises(agent.AgentFault) as caught:
                transport.https_request({"state": "test"}, 1.0)
            self.assertEqual(str(caught.exception), "http_error")
            self.assertEqual(caught.exception.http_status, 429)

    def test_credential_not_forwarded_to_request_state(self):
        with patch.dict("os.environ", {"TYPESAFE_API_KEY": "fake-test-key"}):
            self.assertEqual(agent.credential(), "fake-test-key")
            payload = agent.question(agent.public_state(self.obs, self.catalog), "family", "Choose.", {"buy": "buy"})
            self.assertNotIn("fake-test-key", json.dumps(payload))


if __name__ == "__main__":
    unittest.main()
