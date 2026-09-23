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


def zero_terms(actions):
    return [{name: 0 for name in agent.TERM_NAMES} for _ in actions]


class AgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = [json.loads(line) for line in (ROOT / "fixtures/protocol/v0.5/normal-game.ndjson").read_text(encoding="utf-8").splitlines()]
        cls.obs = next(x["observation"] for x in cls.fixture if x["type"] == "observation")
        cls.legal = next(x["legal_actions"] for x in cls.fixture if x["type"] == "request_action")
        cls.catalog = agent.load_catalog()

    def test_catalog_is_canonical(self):
        self.assertEqual(self.catalog, build_catalog.catalog())

    def test_only_observable_information_and_canonical_terms_are_forwarded(self):
        observation = json.loads(json.dumps(self.obs))
        observation["referee_deck"] = "UNREACHABLE"
        observation["private"]["hidden_opponent"] = "UNREACHABLE"
        terms = zero_terms(self.legal)
        indices = agent.candidate_indices(self.legal)
        stage1 = agent.family_question(observation, self.legal, indices, terms, self.catalog)
        stage2, _ = agent.move_question(observation, self.legal, indices, terms, self.catalog, "take_tokens")
        for payload in (stage1, stage2):
            text = json.dumps(payload)
            self.assertNotIn("UNREACHABLE", text)
            self.assertNotIn("observation_hash", text)
            self.assertNotIn("ruleset_fingerprint", text)
            self.assertNotIn("referee_deck", text)
            self.assertEqual(payload["state"]["market"][0][0]["id"], self.obs["public"]["market"][0][0])
        self.assertEqual(set(stage2["questions"]["move"]["criteria"]["a0"]["existing_heuristic_terms"]),
                         set(agent.TERM_NAMES) | {"heuristic_total"})
        self.assertIn("probability, points", stage2["questions"]["move"]["instructions"])

    def test_two_stage_category_then_exact_legal_action(self):
        # The existing fixture's 30 token choices exercise stage two; add a
        # distinct certified-family value to exercise stage-one routing.
        legal = self.legal + [{"type": "buy_market", "tier": "One", "slot": 0}]
        answers = iter([
            {"model": "jev-1.13.0", "answers": {"family": {"type": "choice", "choice": "take_tokens"}},
             "usage": {"input_tokens": 100, "output_tokens": 10}},
            {"model": "jev-1.13.0", "answers": {"move": {"type": "choice", "choice": "a9"}},
             "usage": {"input_tokens": 200, "output_tokens": 20}},
        ])
        payloads = []
        def call(payload):
            payloads.append(payload)
            return next(answers)
        action, usage, count, calls = agent.pick(self.obs, legal, self.catalog, call,
                                                  lambda _obs, actions: zero_terms(actions))
        self.assertEqual(action, self.legal[9])
        self.assertEqual([set(p["questions"]) for p in payloads], [{"family"}, {"move"}])
        self.assertEqual(usage, {"input_tokens": 300, "output_tokens": 30})
        self.assertEqual((count, calls), (15, 2))

    def test_rejects_invalid_stage_and_move_responses_without_fallback(self):
        legal = self.legal + [{"type": "buy_market", "tier": "One", "slot": 0}]
        no_call_terms = lambda _obs, actions: zero_terms(actions)
        with self.assertRaises(agent.AgentFault):
            agent.pick(self.obs, legal, self.catalog,
                       lambda _: {"answers": {"family": {"type": "choice", "choice": "unknown"}}}, no_call_terms)
        responses = iter([
            {"answers": {"family": {"type": "choice", "choice": "take_tokens"}}},
            {"answers": {"move": {"type": "choice", "choice": "a999"}}},
        ])
        with self.assertRaises(agent.AgentFault):
            agent.pick(self.obs, legal, self.catalog, lambda _: next(responses), no_call_terms)

    def test_noop_filter_and_singleton_skip_api(self):
        noop = {"type": "take_tokens", "take": self.legal[0]["take"], "return": self.legal[0]["take"]}
        self.assertNotIn(0, agent.candidate_indices([noop, self.legal[0]]))
        self.assertEqual(agent.candidate_indices([noop]), [0])
        chosen, usage, size, calls = agent.pick(self.obs, [self.legal[0]], self.catalog,
                                                lambda _: self.fail("singleton must not call API"),
                                                lambda *_: self.fail("singleton needs no baseline terms"))
        self.assertEqual((chosen, usage, size, calls), (self.legal[0], None, 1, 0))

    def test_call_budget_and_metrics_for_two_stage_protocol(self):
        end = {"type": "game_end", "protocol_version": "0.5", "game_id": self.fixture[0]["game_id"],
               "recipient_player_id": 0, "result": {}}
        output = io.StringIO()
        responses = iter([
            {"model": "jev-1.13.0", "answers": {"family": {"type": "choice", "choice": "take_tokens"}},
             "usage": {"input_tokens": 20, "output_tokens": 2}},
            {"model": "jev-1.13.0", "answers": {"move": {"type": "choice", "choice": "a3"}},
             "usage": {"input_tokens": 50, "output_tokens": 5}},
        ])
        # Fixture has two action families after no-op filtering, so both stages run.
        with contextlib.redirect_stdout(output):
            metrics = agent.run([json.dumps(x) for x in [*self.fixture, end]], lambda _: next(responses),
                                lambda _obs, actions: zero_terms(actions))
        emitted = [json.loads(x) for x in output.getvalue().splitlines()]
        self.assertEqual([x["type"] for x in emitted], ["hello", "action"])
        self.assertEqual(emitted[1]["action"], self.legal[3])
        self.assertEqual(emitted[1]["request_id"], self.fixture[-1]["request_id"])
        self.assertEqual(metrics["api_calls"], 2)
        self.assertEqual(metrics["stage1_calls"], 1)
        self.assertEqual(metrics["stage2_calls"], 1)
        self.assertEqual(metrics["input_tokens"], 70)
        self.assertEqual(metrics["model_version"], "jev-1.13.0")
        corrupted = [dict(x) for x in self.fixture]
        corrupted[-1]["observation_hash"] = "wrong"
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(agent.AgentFault, "request observation"):
            agent.run([json.dumps(x) for x in corrupted], term_provider=lambda *_: [])

    def test_two_stage_budget_never_exceeds_configured_call_cap(self):
        end = {"type": "game_end", "protocol_version": "0.5", "game_id": self.fixture[0]["game_id"],
               "recipient_player_id": 0, "result": {}}
        calls = []
        def call(payload):
            calls.append(payload)
            return {"answers": {"family": {"type": "choice", "choice": "take_tokens"}}}
        with patch.dict("os.environ", {"JEV_MAX_API_CALLS": "1"}), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(agent.AgentFault, "call budget"):
                agent.run([json.dumps(x) for x in [*self.fixture, end]], call,
                          lambda _obs, actions: zero_terms(actions))
        self.assertEqual(len(calls), 1, "stage 2 must not exceed the one-call budget")

    def test_http_error_does_not_log_remote_body_or_key(self):
        with patch.dict("os.environ", {"TYPESAFE_API_KEY": "fake-test-key"}), patch.object(
            agent.urllib.request, "urlopen", side_effect=urllib.error.HTTPError(
                agent.API_URL, 429, "SENSITIVE REMOTE BODY", {}, io.BytesIO(b"SENSITIVE REMOTE BODY"))
        ):
            with self.assertRaises(agent.AgentFault) as caught:
                agent.evaluate({"state": "test"})
            self.assertEqual(str(caught.exception), "TypeSafe HTTP 429")

    def test_credential_not_forwarded_to_request_state(self):
        with patch.dict("os.environ", {"TYPESAFE_API_KEY": "fake-test-key"}):
            self.assertEqual(agent.credential(), "fake-test-key")
            payload = agent.family_question(self.obs, self.legal, list(range(len(self.legal))),
                                            zero_terms(self.legal), self.catalog)
            self.assertNotIn("fake-test-key", json.dumps(payload))


if __name__ == "__main__":
    unittest.main()
