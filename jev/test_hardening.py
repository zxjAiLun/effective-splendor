"""Offline hardening gates: no real TypeSafe calls; local children and fake HTTP only."""
from __future__ import annotations

import contextlib
import copy
from email.message import Message
import io
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
import urllib.response
from unittest.mock import Mock, patch

import agent
import match
from runtime import AgentFault, Deadline, ServiceFault, Session, run_child
import transport

ROOT = Path(__file__).resolve().parents[1]
BINARY = Path(os.environ.get("JEV_TEST_BINARY", ROOT / ("target/release/splendor.exe" if os.name == "nt" else "target/release/splendor")))
FIXTURE = [json.loads(x) for x in (ROOT / "fixtures/protocol/v0.5/normal-game.ndjson").read_text().splitlines()]
OBS = next(x["observation"] for x in FIXTURE if x["type"] == "observation")
LEGAL = next(x["legal_actions"] for x in FIXTURE if x["type"] == "request_action")
CATALOG = agent.load_catalog()


def zero_terms(_obs, actions, **_kwargs):
    return [{k: 0 for k in agent.TERM_NAMES} for _ in actions]


def response(stage, choice, tokens=100):
    return {"model": "jev-1.13.0", "answers": {stage: {"type": "choice", "choice": choice}},
            "usage": {"input_tokens": tokens, "output_tokens": 10}}


def transcript(deadline_ms=45000):
    data = copy.deepcopy(FIXTURE)
    data[-1]["deadline_ms"] = deadline_ms
    data.append(dict(type="game_end", protocol_version="0.5", game_id=data[0]["game_id"], recipient_player_id=0))
    return [json.dumps(x) for x in data]


class FakeClock:
    def __init__(self): self.now = 0.0
    def __call__(self): return self.now
    def sleep(self, seconds): self.now += seconds


class SemanticsTests(unittest.TestCase):
    def test_reserve_card_points_are_future_not_immediate(self):
        reserve = next(a for a in LEGAL if a["type"] == "reserve_market" and CATALOG["cards"][OBS["public"]["market"][0][a["slot"]]]["prestige"] > 0 and a["tier"] == "One")
        desc = agent.description(reserve, OBS, CATALOG)
        self.assertEqual(desc["known_effects"]["card_vp_now"], 0)
        self.assertIsNone(desc["known_effects"]["permanent_bonus_gained"])
        self.assertGreater(desc["known_effects"]["reserved_card_vp_if_later_bought"], 0)
        buy = {"type": "buy_market", "tier": reserve["tier"], "slot": reserve["slot"]}
        bought = agent.description(buy, OBS, CATALOG)
        self.assertEqual(bought["known_effects"]["card_vp_now"], desc["known_effects"]["reserved_card_vp_if_later_bought"])
        self.assertIsNone(bought["known_effects"]["noble_vp_now"], "don't fabricate purchase noble settlement")
        self.assertIn("zero immediate VP", agent.TERM_GLOSSARY["prestige"])

    def test_public_reserves_named_colors_and_no_nested_leak(self):
        obs = copy.deepcopy(OBS)
        obs["public"]["players"][1]["public_reserved"] = [0]
        obs["public"]["players"][1]["tokens"]["untrusted"] = "SECRET_SENTINEL"
        obs["private"]["opponent_blind"] = "SECRET_SENTINEL"
        state = agent.public_state(obs, CATALOG)
        self.assertEqual(state["players"][1]["public_reserved"][0]["id"], 0)
        self.assertEqual(set(state["players"][0]["bonuses_by_color"]), set(agent.COLORS))
        self.assertEqual(set(state["nobles"][0]["requirements_by_color"]), set(agent.COLORS))
        self.assertNotIn("SECRET_SENTINEL", json.dumps(state))
        self.assertNotIn("bonuses", state["players"][0])
        self.assertIn("fewer purchased", state["rules"]["ending"])

    def test_stage1_does_not_reintroduce_prior_and_has_glossary(self):
        scores = zero_terms(OBS, LEGAL)
        for t in scores: t["category_base"] = 123456789
        request = agent.family_question(OBS, LEGAL, list(range(len(LEGAL))), scores, CATALOG)
        text = json.dumps(request)
        self.assertNotIn("category_base", text)
        self.assertNotIn('"heuristic_total"', text)
        self.assertNotIn("123456789", text)
        self.assertIn("advisory_term_definitions", text)
        self.assertIn("zero immediate VP", text)

    def test_single_family_skips_stage1_and_cap_reports_only_cap(self):
        # Synthetic over-cap selection test, not a claim about a reachable legal set.
        legal = [next(a for a in LEGAL if a["type"] == "take_tokens")] * 81
        scores = zero_terms(OBS, legal)
        scores[80]["new_target"] = 100
        offered = []
        trace = []
        def call(payload):
            self.assertEqual(set(payload["questions"]), {"move"})
            offered.append(payload)
            return response("move", "a0")
        _, _, count, calls = agent.pick(OBS, legal, CATALOG, call, lambda *_: scores, lambda **info: trace.append(info))
        self.assertEqual((count, calls), (80, 1))
        self.assertEqual(trace[0]["routed_out"], 0)
        self.assertEqual(trace[0]["noops_removed"], 0)
        self.assertEqual(trace[0]["cap_removed"], 1)
        self.assertEqual(trace[0]["selected_index"], 80)

    def test_selected_singleton_family_skips_stage2(self):
        legal = [next(a for a in LEGAL if a["type"] == "take_tokens"), next(a for a in LEGAL if a["type"] == "reserve_market")]
        calls = []
        def call(payload):
            calls.append(set(payload["questions"]))
            return response("family", "reserve")
        picked, _, _, count = agent.pick(OBS, legal, CATALOG, call, zero_terms)
        self.assertEqual(calls, [{"family"}])
        self.assertEqual((picked, count), (legal[1], 1))


class LifecycleTests(unittest.TestCase):
    def run_case(self, call, *, deadline_ms=45000, max_calls=100, helper=zero_terms, clock=None):
        clock = clock or FakeClock()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name)/"metrics.json"
        session = Session(agent.MODEL, summary_path=path, max_calls=max_calls, clock=clock, sleeper=clock.sleep)
        output = io.StringIO()
        error = None
        try:
            with contextlib.redirect_stdout(output):
                agent.run(transcript(deadline_ms), call, helper, session=session)
        except BaseException as exc:
            error = exc
        metrics = json.loads(path.read_text())
        events = [json.loads(x) for x in path.with_suffix(".jsonl").read_text().splitlines()]
        self.assertFalse(path.with_name(path.name+".tmp").exists())
        return error, metrics, events, output.getvalue()

    def test_partial_usage_and_failed_summary_survive_second_stage_429(self):
        def call(payload, **kw):
            if "family" in payload["questions"]: return response("family", "take_tokens")
            raise ServiceFault("http_error", 429)
        err, m, events, stdout = self.run_case(call)
        self.assertIsInstance(err, ServiceFault)
        self.assertEqual(m["status"], "failed")
        self.assertEqual(m["api_calls"], 3)  # Stage 1 + two bounded stage-2 attempts.
        self.assertEqual(m["input_tokens"], 100)
        self.assertEqual(m["unknown_usage_attempts"], 2)
        self.assertEqual(m["decisions"], 0)
        self.assertEqual(events[-1]["event"], "session_end")
        self.assertNotIn('"type":"action"', stdout)

    def test_retry_recovers_and_model_versions_are_not_overwritten(self):
        calls = []
        def call(payload, **kw):
            calls.append(payload)
            if len(calls) == 1: raise ServiceFault("http_error", 529)
            if "family" in payload["questions"]: return response("family", "take_tokens", 20)
            out = response("move", "a0", 30)
            out["model"] = "jev-other-test"
            return out
        err, m, events, stdout = self.run_case(call)
        self.assertIsNone(err)
        self.assertEqual(m["status"], "completed")
        self.assertEqual(m["api_calls"], 3)
        self.assertEqual(m["input_tokens"], 50)
        self.assertEqual(m["model_versions"], ["jev-1.13.0", "jev-other-test"])
        self.assertEqual(m["noops_removed"]+m["routed_out"]+m["cap_removed"], m["options_omitted"])
        self.assertEqual(m["routed_out"], 15)
        self.assertEqual(m["cap_removed"], 0)
        self.assertIn('"type":"action"', stdout)
        self.assertTrue(any(e["event"] == "decision_choice" and e["selected_index"] == 0 for e in events))

    def test_auth_error_and_invalid_choice_are_not_retried(self):
        for fault in (ServiceFault("http_error", 401), ServiceFault("redirect_blocked", 302)):
            def call(payload, **kw): raise fault
            err, m, _, _ = self.run_case(call)
            self.assertEqual(m["api_calls"], 1)
            self.assertEqual(m["error_code"], fault.code)
        err, m, events, _ = self.run_case(lambda *_a, **_k: response("family", "SECRET_SENTINEL"))
        self.assertIsInstance(err, AgentFault)
        self.assertEqual(m["api_calls"], 1)
        self.assertEqual(m["input_tokens"], 100)
        self.assertNotIn("SECRET_SENTINEL", json.dumps(events))

    def test_budget_counts_retries_before_they_are_sent(self):
        def call(*args, **kw): raise ServiceFault("http_error", 429)
        err, m, _, _ = self.run_case(call, max_calls=1)
        self.assertEqual(err.code, "api_budget")
        self.assertEqual(m["api_calls"], 1)

    def test_shared_deadline_includes_helper_both_stages_and_retry_wait(self):
        clock = FakeClock()
        timeouts = []
        def helper(o, a, **kw):
            clock.sleep(.2)
            return zero_terms(o, a)
        def call(payload, *, timeout):
            timeouts.append(timeout)
            clock.sleep(.3)
            if "family" in payload["questions"]: return response("family", "take_tokens")
            clock.sleep(.3)  # Past the .9s effective deadline.
            return response("move", "a0")
        err, m, _, stdout = self.run_case(call, deadline_ms=1000, helper=helper, clock=clock)
        self.assertEqual(err.code, "decision_timeout")
        self.assertLess(timeouts[1], timeouts[0])
        self.assertEqual(m["input_tokens"], 200, "late response usage is still retained")
        self.assertNotIn('"type":"action"', stdout)
        err, m, _, _ = self.run_case(lambda *a, **kw: (_ for _ in ()).throw(ServiceFault("http_error", 429, 5)), deadline_ms=1000)
        self.assertEqual(err.code, "decision_timeout")
        self.assertEqual(m["api_calls"], 1)

    def test_cancellation_keeps_partial_usage_and_does_not_echo_exception(self):
        def call(payload, **kw):
            if "family" in payload["questions"]: return response("family", "take_tokens")
            raise KeyboardInterrupt("SECRET_SENTINEL")
        err, m, events, _ = self.run_case(call)
        self.assertIsInstance(err, KeyboardInterrupt)
        self.assertEqual(m["status"], "cancelled")
        self.assertEqual(m["input_tokens"], 100)
        self.assertNotIn("SECRET_SENTINEL", json.dumps(events))


class TransportTests(unittest.TestCase):
    def test_real_urllib_redirect_chain_never_sends_second_request(self):
        real_build = urllib.request.build_opener
        seen = []
        class FakeHTTPS(urllib.request.HTTPSHandler):
            def https_open(self, request):
                seen.append(request.full_url)
                headers = Message()
                headers["Location"] = "http://example.invalid/would-steal-key"
                reply = urllib.response.addinfourl(io.BytesIO(b"SECRET_BODY"), headers, request.full_url, 302)
                reply.msg = "Found"
                return reply
        def build(*handlers): return real_build(FakeHTTPS(), *handlers)
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "FAKE_KEY"}), \
             patch.object(transport.urllib.request, "build_opener", side_effect=build), \
             patch("socket.create_connection", side_effect=AssertionError("network forbidden")):
            with self.assertRaises(ServiceFault) as caught:
                transport.https_request({"state": "test"}, .1)
        self.assertEqual(caught.exception.code, "redirect_blocked")
        self.assertEqual(seen, [transport.API_URL])
        self.assertNotIn("FAKE_KEY", str(caught.exception))

    def test_owned_child_is_reaped_on_wall_timeout(self):
        real_popen = subprocess.Popen
        children = []
        def launch(*args, **kwargs):
            proc = real_popen(*args, **kwargs)
            children.append(proc)
            return proc
        with patch("runtime.subprocess.Popen", side_effect=launch):
            with self.assertRaises(subprocess.TimeoutExpired):
                run_child([sys.executable, "-c", "import time;time.sleep(60)"], timeout=.15)
        self.assertIsNotNone(children[0].poll())

    def test_wrapped_socket_timeout_or_tls_error_is_not_retryable(self):
        for reason, code in [(TimeoutError("SECRET"), "http_timeout"), (ssl.SSLCertVerificationError("SECRET"), "tls_error")]:
            opener = Mock()
            opener.open.side_effect = urllib.error.URLError(reason)
            with patch.dict(os.environ, {"TYPESAFE_API_KEY": "FAKE_KEY"}), patch.object(
                transport.urllib.request, "build_opener", return_value=opener
            ):
                with self.assertRaises(ServiceFault) as caught:
                    transport.https_request({"state": "test"}, .1)
            self.assertEqual(caught.exception.code, code)
            self.assertFalse(caught.exception.retryable)

    def test_parent_worker_serialization_and_deadline_without_network(self):
        original = transport.run_child
        for slow in (False, True):
            def launch(command, **kwargs):
                body = ("import sys,time;sys.path.insert(0," + repr(str(ROOT/'jev')) + ");import transport;"
                        "transport.https_request=lambda p,t: " +
                        ("(time.sleep(60) or {})" if slow else "{'model':'jev-test','answers':{'move':{'type':'choice','choice':'a0'}},'usage':{'input_tokens':4,'output_tokens':1}}") +
                        ";transport.worker_main()")
                return original([sys.executable,"-c",body,command[-1]], **kwargs)
            with patch.object(transport, "run_child", side_effect=launch):
                if slow:
                    with self.assertRaises(ServiceFault) as caught:
                        transport.evaluate({"state":"test"}, .2)
                    self.assertEqual(caught.exception.code,"http_timeout")
                else:
                    result = transport.evaluate({"state":"test"}, 3)
                    self.assertEqual(result["usage"]["input_tokens"],4)

    def test_worker_timeout_is_not_retried_or_exposed(self):
        with patch.object(transport, "run_child", side_effect=subprocess.TimeoutExpired("SECRET_COMMAND", 1)):
            with self.assertRaises(ServiceFault) as caught:
                transport.evaluate({"state": "test"}, .1)
        self.assertEqual(caught.exception.code, "http_timeout")
        self.assertFalse(caught.exception.retryable)
        self.assertNotIn("SECRET_COMMAND", str(caught.exception))

    @unittest.skipUnless(os.name == "nt", "Windows taskkill descendant gate")
    def test_runner_timeout_kills_spawned_descendant_on_windows(self):
        import ctypes
        from ctypes import wintypes
        with tempfile.TemporaryDirectory() as directory:
            pid_file = Path(directory)/"child.pid"
            code = ("import subprocess,sys,time;from pathlib import Path;"
                    "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
                    f"Path({str(pid_file)!r}).write_text(str(p.pid));time.sleep(60)")
            with self.assertRaises(subprocess.TimeoutExpired):
                match.run_arena([sys.executable,"-c",code],cwd=ROOT,env=os.environ.copy(),timeout=1.0)
            pid = int(pid_file.read_text())
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
            kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
            handle = kernel.OpenProcess(0x00100000, False, pid)
            if handle:
                try:
                    self.assertEqual(kernel.WaitForSingleObject(handle, 0), 0, "descendant still running")
                finally:
                    kernel.CloseHandle(handle)

    def test_runner_cancellation_reaps_its_direct_process(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            match.run_arena([sys.executable, "-c", "import time;time.sleep(60)"], cwd=ROOT, env=os.environ.copy(), timeout=.15)


@unittest.skipUnless(BINARY.is_file(), "build release splendor-cli for sidecar/arena integration gates")
class RealBoundaryTests(unittest.TestCase):
    def call_helper(self, value):
        return subprocess.run([str(BINARY), "agent-heuristic-terms"], input=json.dumps(value)+"\n", capture_output=True, text=True, timeout=10)

    def test_actual_sidecar_rejects_bad_indices_and_extra_fields_without_panic(self):
        valid = {"observation": OBS, "legal_actions": LEGAL}
        good = self.call_helper(valid)
        self.assertEqual(good.returncode, 0, good.stderr)
        self.assertEqual(len(json.loads(good.stdout)["terms"]), len(LEGAL))
        bad_slot = {"observation": OBS, "legal_actions": [{"type": "buy_market", "tier": "One", "slot": 255}]}
        bad_viewer = copy.deepcopy(valid)
        bad_viewer["observation"]["viewer"] = 255
        bad_bonus = copy.deepcopy(valid)
        bad_bonus["observation"]["public"]["players"][0]["bonuses"] = [255] * 5
        for bad in (dict(valid, seed=42), bad_slot, bad_viewer, bad_bonus):
            result = self.call_helper(bad)
            self.assertEqual(result.returncode, 1)
            self.assertNotIn("panicked", result.stderr)
            self.assertFalse(result.stdout)
        oversized = subprocess.run([str(BINARY), "agent-heuristic-terms"], input=" " * 2_000_001,
                                   capture_output=True, text=True, timeout=10)
        self.assertEqual(oversized.returncode, 1)

    def test_match_manifest_binds_runtime_and_keeps_credentials_out(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)/"new-match"
            args = ["match.py", "--binary", str(BINARY), "--out-dir", str(out), "--max-plies", "4"]
            result = subprocess.CompletedProcess([], 0, json.dumps({"status": "truncated"}), "")
            with patch.object(sys, "argv", args), patch.object(match, "run_arena", return_value=result), \
                 patch.dict(os.environ, {"TYPESAFE_API_KEY": "SECRET_SENTINEL", "JEV_MAX_API_CALLS": "12"}), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(match.main(), 0)
            manifest = json.loads((out/"manifest.json").read_text())
            self.assertEqual(manifest["max_api_calls"], 12)
            self.assertEqual(manifest["agent_version"], "0.3.0")
            self.assertIn("jev/transport.py", manifest["source_sha256"])
            self.assertEqual(len(manifest["binary_sha256"]), 64)
            self.assertNotIn("SECRET_SENTINEL", (out/"manifest.json").read_text())

    def test_actual_arena_with_fake_decider_records_verified_truncation(self):
        # No production flag enables fake inference. Test-owned child injects a callable.
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            wrapper = out/"offline_agent.py"
            wrapper.write_text("import sys\nsys.path.insert(0," + repr(str(ROOT/'jev')) + ")\nimport agent\n"
                "def fake(payload, **kw):\n"
                " qid=next(iter(payload['questions'])); chosen=next(iter(payload['questions'][qid]['criteria']))\n"
                " return {'model':'jev-test','answers':{qid:{'type':'choice','choice':chosen}},'usage':{'input_tokens':1,'output_tokens':1}}\n"
                "agent.run(sys.stdin,call=fake)\n", encoding="utf-8")
            config = dict(game_id="jev-offline-hardening", run_trace_id="offline", seed=20260926,
                          handshake_timeout_ms=10000,
                          move_timeout_ms=10000, shutdown_grace_ms=2000,
                          agents=[dict(program=sys.executable,args=[str(wrapper)]),
                                  dict(program=str(BINARY),args=["agent-heuristic","--seed","20260927"])])
            (out/"config.json").write_text(json.dumps(config),encoding="utf-8")
            env = dict(os.environ, JEV_SPLENDOR_BINARY=str(BINARY), JEV_METRICS_FILE=str(out/"metrics.json"),
                       JEV_MAX_API_CALLS="10", TYPESAFE_API_KEY="FAKE_KEY_UNUSED",
                       # The fake decider reports its own identity; the drift
                       # gate must be told which identity to expect.
                       JEV_MODEL="jev-test", JEV_EXPECTED_MODEL="jev-test")
            result = subprocess.run([str(BINARY),"run-rollout","--config",str(out/"config.json"),"--max-plies","4",
                                     "--report-out",str(out/"report.json"),"--replay-out",str(out/"replay.json"),
                                     "--prefix-out",str(out/"prefix.json")], cwd=ROOT,env=env,capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            report = json.loads((out/"report.json").read_text())
            self.assertEqual(report["outcome"]["status"],"truncated")
            self.assertNotIn("result",report["outcome"])
            metrics = json.loads((out/"metrics.json").read_text())
            self.assertEqual(metrics["status"],"truncated")
            self.assertEqual(metrics["decisions"],2)
            self.assertEqual(metrics["api_calls"],4)
            self.assertNotIn("FAKE_KEY_UNUSED",(out/"metrics.jsonl").read_text())
            self.assertTrue((out/"prefix.json").is_file())

            # The interaction trace must carry the ply and observation hash the
            # arena actually sent, so a step can be addressed the same way here
            # and in the GUI.
            self.assertEqual(metrics["identity"], {"game_id":"jev-offline-hardening",
                                                   "run_id":"offline", "seat":0})
            records = [json.loads(line) for line in (out/"metrics.jsonl").read_text().splitlines()]
            starts = [r for r in records if r["event"] == "decision_start"]
            # Plies are match-global: in a two-player game the seat-0 agent decides
            # on even plies. The GUI joins on this plus the observation hash.
            self.assertEqual([r["ply"] for r in starts], [0, 2])
            self.assertEqual({r["actor"] for r in starts}, {0})
            self.assertTrue(all(isinstance(r.get("observation_hash"), str) for r in starts))
            # The snapshot is the exact application payload, with no credential:
            # the agent never receives one, so it can never be written down here.
            requests = [r for r in records if r["event"] == "request_start"]
            self.assertEqual(len(requests), 4)
            for request in requests:
                self.assertTrue(request["payload_snapshot_recorded"])
                self.assertEqual(set(request["payload_snapshot"]), {"state", "model", "questions"})
                # The requested model is whatever this run pinned, never the
                # floating alias unless the experiment deliberately asks for it.
                self.assertEqual(request["payload_snapshot"]["model"], "jev-test")
            self.assertNotIn("FAKE_KEY_UNUSED", json.dumps(requests))

    def test_trace_summary_joins_the_journal_to_the_verified_prefix(self):
        import trace as trace_reader

        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            wrapper = out/"offline_agent.py"
            wrapper.write_text("import sys\nsys.path.insert(0," + repr(str(ROOT/'jev')) + ")\nimport agent\n"
                "def fake(payload, **kw):\n"
                " qid=next(iter(payload['questions'])); chosen=next(iter(payload['questions'][qid]['criteria']))\n"
                " return {'model':'jev-test','answers':{qid:{'type':'choice','choice':chosen}},'usage':{'input_tokens':1,'output_tokens':1}}\n"
                "agent.run(sys.stdin,call=fake)\n", encoding="utf-8")
            config = dict(game_id="jev-offline-tracejoin", run_trace_id="offline", seed=20260928,
                          handshake_timeout_ms=10000, move_timeout_ms=10000, shutdown_grace_ms=2000,
                          agents=[dict(program=sys.executable,args=[str(wrapper)]),
                                  dict(program=str(BINARY),args=["agent-heuristic","--seed","20260929"])])
            (out/"config.json").write_text(json.dumps(config),encoding="utf-8")
            env = dict(os.environ, JEV_SPLENDOR_BINARY=str(BINARY), JEV_METRICS_FILE=str(out/"metrics.json"),
                       JEV_MAX_API_CALLS="10", TYPESAFE_API_KEY="FAKE_KEY_UNUSED",
                       # The fake decider reports its own identity; the drift
                       # gate must be told which identity to expect.
                       JEV_MODEL="jev-test", JEV_EXPECTED_MODEL="jev-test")
            result = subprocess.run([str(BINARY),"run-rollout","--config",str(out/"config.json"),"--max-plies","4",
                                     "--report-out",str(out/"report.json"),"--replay-out",str(out/"replay.json"),
                                     "--prefix-out",str(out/"prefix.json")], cwd=ROOT,env=env,capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            match.write_trace_summary(out)
            summary = json.loads((out/"trace-summary.json").read_text())
            self.assertEqual(summary["game_document"], "truncated_prefix")
            self.assertEqual(summary["journal_decisions"], 2)
            self.assertEqual(summary["ambiguous_plies"], [])
            # Match-global plies: seat 0 decides on plies 0 and 2 in a 2-player game.
            self.assertEqual(sorted(summary["decisions"]), ["0", "2"])
            for ply in ("0", "2"):
                entry = summary["decisions"][ply]
                self.assertEqual(entry["actor"], 0)
                self.assertTrue(entry["action_sent"])
                # A non-forced decision has a local helper plus both Jev stages.
                self.assertEqual([s["stage"] for s in entry["stages"]],
                                 ["helper", "family", "move"])
            # The summary is a projection of the same journal the reader loads, so
            # both must agree on which plies carry a call.
            read = trace_reader.read_run(out.name, out.parent)
            indexed = trace_reader.index_by_ply(read["events"])
            self.assertEqual(sorted(indexed), [0, 2])
            self.assertEqual({e["actor"] for e in indexed[0]}, {0})


if __name__ == "__main__":
    unittest.main()
