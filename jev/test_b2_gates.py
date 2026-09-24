"""B2 gates: the local request-size gate and the pinned-model drift gate.

Both are experiment-integrity guards, not strategy. They exist because Stage B
measured a real provider ceiling (76,133 B accepted / 76,134 B rejected) and
resolved the floating alias to a concrete model; neither fact may be left to the
server to rediscover mid-run.
"""
from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
import unittest.mock
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import agent  # noqa: E402
import runtime  # noqa: E402
import transport  # noqa: E402


class RequestSizeGateTests(unittest.TestCase):
    def test_the_budget_is_conservative_not_on_the_measured_edge(self):
        # The measured boundary for the real payload shape was 76,133 accepted /
        # 76,134 rejected. Sitting on it would let a one-field change break a
        # run, so the budget keeps real margin.
        self.assertLess(transport.MAX_REQUEST_BYTES, 76_133)
        self.assertGreaterEqual(transport.MAX_REQUEST_BYTES, 60_000)

    def test_an_oversized_payload_is_refused_locally_and_never_sent(self):
        payload = {"state": {"pad": "z" * (transport.MAX_REQUEST_BYTES + 100)},
                   "model": "jev-1.13.0", "questions": {}}
        with unittest.mock.patch.object(transport, "credential", return_value="k"), \
                unittest.mock.patch.object(
                    transport.urllib.request.OpenerDirector, "open",
                    side_effect=AssertionError("the network must not be touched")):
            with self.assertRaises(runtime.ServiceFault) as caught:
                transport.https_request(payload, 5)
        self.assertEqual(caught.exception.code, "request_payload_too_large")

    def test_the_gate_uses_the_same_encoder_the_transport_sends(self):
        # A gate computed from a different serialization could disagree with the
        # bytes actually transmitted, which is worse than no gate at all.
        source = (HERE / "transport.py").read_text(encoding="utf-8")
        self.assertIn("body = encode(payload)", source)
        self.assertIn('len(body.encode("utf-8")) > MAX_REQUEST_BYTES', source)


class PinnedModelTests(unittest.TestCase):
    def test_the_model_is_pinned_to_a_concrete_version_not_the_floating_alias(self):
        # Stage B resolved `jev-latest` -> jev-1.13.0, and a probe confirmed the
        # concrete version is accepted. One experiment must use one model.
        self.assertNotEqual(agent.MODEL, "jev-latest")
        self.assertRegex(agent.MODEL, r"^jev-[0-9]+\.[0-9]+\.[0-9]+$")

    def test_a_drifted_response_identity_fails_closed(self):
        # Driven through the real request loop: a response carrying a different
        # model must abort rather than blend two policies into one result set.
        session = runtime.Session("jev-1.13.0", expected_model="jev-1.13.0")
        events = []
        session.emit = lambda name, **fields: events.append((name, fields))
        session.metrics["api_calls"] = 0
        session.max_calls = 10
        response = {"model": "jev-9.9.9",
                    "answers": {"move": {"type": "choice", "choice": "a0"}},
                    "usage": {"input_tokens": 1, "output_tokens": 1}}
        payload = {"state": {}, "model": "jev-1.13.0",
                   "questions": {"move": {"type": "choice", "instructions": "pick",
                                            "criteria": {"a0": {"label": "x"}}}}}
        with self.assertRaises(runtime.AgentFault) as caught:
            session.ask(payload, runtime.Deadline(5000), lambda *a, **k: response)
        self.assertEqual(caught.exception.code, "model_identity_drift")
        self.assertIn(("model_identity_drift", {"expected": "jev-1.13.0", "returned": "jev-9.9.9"}),
                      events)


    def test_missing_response_identity_also_fails_closed(self):
        session = runtime.Session(agent.MODEL, expected_model=agent.EXPECTED_MODEL)
        payload = agent.question({}, "family", "choose", {"buy": "buy"})
        response = {"answers": {"family": {"type": "choice", "choice": "buy"}}}
        with self.assertRaises(runtime.AgentFault) as caught:
            session.ask(payload, runtime.Deadline(5000), lambda *a, **kw: response)
        self.assertEqual(caught.exception.code, "model_identity_drift")
        self.assertEqual(session.metrics["api_calls"], 1)


class ManifestIdentityTests(unittest.TestCase):
    def test_the_match_manifest_reads_the_pinned_model_instead_of_the_alias(self):
        # A manifest that recorded the floating alias while the code pins a
        # concrete version would detach the experiment record from the run that
        # produced it. The value must come from the agent, not be restated.
        source = (HERE / "match.py").read_text(encoding="utf-8")
        self.assertIn("requested_model\": agent_module.MODEL", source)
        self.assertNotIn('"requested_model": "jev-latest"', source)

    def test_b2_runner_refuses_current_policy_before_artifacts_or_arena(self):
        import run_batch
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "must-not-exist"
            with unittest.mock.patch.object(run_batch, "run_arena", side_effect=AssertionError("no paid call")):
                with self.assertRaisesRegex(ValueError, "current policy is not B2"):
                    run_batch.one_game({}, out, Path("unused"), 30, 100)
                with unittest.mock.patch.object(sys, "argv", ["run_batch.py", "--batch-dir", str(out)]), \
                     contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                    run_batch.main()
                self.assertEqual(caught.exception.code, 2)
            self.assertFalse(out.exists())

    def test_the_batch_manifest_never_states_the_floating_alias(self):
        source = (HERE / "run_batch.py").read_text(encoding="utf-8")
        self.assertIn("requested_model\": agent_module.MODEL", source)
        self.assertNotIn('"requested_model": "jev-latest"', source)


class FactsRepresentationTests(unittest.TestCase):
    # B2 compaction tests remain in commit 80514df. The active policy no longer
    # has heuristic terms or an abbreviated color legend to compact.
    def test_named_colors_are_unambiguous(self):
        self.assertEqual(agent.COLORS, ("white", "blue", "green", "red", "black"))
        self.assertNotEqual(agent.sparse_gems({"blue": 2}), agent.sparse_gems({"black": 2}))

    def test_no_heuristic_scoring_or_shortlist_functions_in_active_policy(self):
        for name in ("heuristic_terms", "TERM_NAMES", "TERM_GLOSSARY", "candidate_indices", "MAX_OPTIONS"):
            self.assertFalse(hasattr(agent, name), name)


if __name__ == "__main__":
    unittest.main()
