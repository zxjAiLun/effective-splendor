"""Offline gates for the local Jev interaction-trace reader and summary writer.

No network, no model, no paid inference: every case builds a small run directory
on disk and asserts what the reader may and may not claim from it.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import match
import runtime
import trace as trace_reader


def write(directory: Path, name: str, value) -> None:
    (directory / name).write_text(json.dumps(value), encoding="utf-8")


def journal(directory: Path, events: list[dict]) -> None:
    (directory / "metrics.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")


def decision_events(ply: int, obs_hash: str = "obs", actor: int = 0,
                    selected=None, recorded=None) -> list[dict]:
    return [
        {"event": "session_start", "request_id": None},
        {"event": "decision_start", "request_id": ply + 1, "ply": ply,
         "actor": actor, "observation_hash": obs_hash, "legal_count": 5},
        {"event": "helper_complete", "request_id": ply + 1, "latency_ms": 3.0},
        {"event": "request_start", "request_id": ply + 1, "stage": "family", "attempt": 1,
         "candidates": {"take_tokens": {"family": "Take gems"}}, "candidate_ids": ["take_tokens"],
         "requested_model": "jev-latest", "payload_sha256": "deadbeef",
         "payload_snapshot": {"state": {"viewer": actor}, "model": "jev-latest",
                              "questions": {"family": {}}},
         "payload_snapshot_recorded": True},
        {"event": "request_received", "request_id": ply + 1, "stage": "family", "attempt": 1,
         "selected_id": "take_tokens", "returned_model": "jev-1.13.0",
         "usage": {"input_tokens": 100, "output_tokens": 5}, "latency_ms": 120.0},
        {"event": "decision_choice", "request_id": ply + 1, "family": "take_tokens",
         "family_count": 2, "noops_removed": 1, "routed_out": 4, "cap_removed": 0,
         "offered_indices": [0, 1], "selected_index": 0,
         "selected_action": selected or {"type": "take_tokens", "take": {"white": 2}}},
        {"event": "action_sent", "request_id": ply + 1},
    ]


class RunFixture(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.root, ignore_errors=True))
        self.run = self.root / "1700000000-seat0-abcd1234"
        self.run.mkdir()
        write(self.run, "config.json", {"agents": [{"program": "python", "args": ["-u", "jev/agent.py"]},
                                                   {"program": "splendor"}]})


class ReaderTests(RunFixture):
    def test_unknown_and_unsafe_run_ids_are_refused(self):
        for bad in ["", ".", "..", "a/b", "a\\b", "with space", "x" * 129]:
            with self.assertRaises(trace_reader.TraceError):
                trace_reader.read_run(bad, self.root)

    def test_a_directory_without_a_journal_reads_as_absent_not_empty(self):
        info = trace_reader.read_run(self.run.name, self.root)
        self.assertEqual(info["events"], [])
        self.assertFalse(info["has_verified_game"])
        self.assertIsNone(info["metrics"])

    def test_corrupt_or_oversized_journals_refuse_instead_of_being_skipped(self):
        (self.run / "metrics.jsonl").write_text('{"event":"decision_start"}\nnot json\n', encoding="utf-8")
        with self.assertRaises(trace_reader.TraceError) as caught:
            trace_reader.read_run(self.run.name, self.root)
        self.assertEqual(caught.exception.code, "trace_corrupt")
        with patch.object(trace_reader, "MAX_JOURNAL_LINE_BYTES", 10):
            journal(self.run, decision_events(0))
            with self.assertRaises(trace_reader.TraceError) as caught:
                trace_reader.read_run(self.run.name, self.root)
            self.assertEqual(caught.exception.code, "trace_line_too_large")

    def test_unknown_event_kinds_are_ignored_so_a_future_field_cannot_become_a_claim(self):
        journal(self.run, [*decision_events(0), {"event": "internal_reasoning", "text": "SECRET"}])
        info = trace_reader.read_run(self.run.name, self.root)
        self.assertNotIn("SECRET", json.dumps(info["events"]))
        self.assertNotIn("internal_reasoning", [e["event"] for e in info["events"]])

    def test_decisions_group_by_reported_ply_and_duplicates_stay_ambiguous(self):
        journal(self.run, [*decision_events(2), *decision_events(2), *decision_events(5)])
        index = trace_reader.index_by_ply(trace_reader.read_run(self.run.name, self.root)["events"])
        self.assertEqual(sorted(index), [2, 5])
        self.assertEqual(len(index[2]), 2)
        self.assertEqual(len(index[5]), 1)

    def test_a_journal_without_ply_is_not_attributed_to_a_step(self):
        events = decision_events(0)
        events[1].pop("ply")
        journal(self.run, events)
        self.assertEqual(trace_reader.index_by_ply(
            trace_reader.read_run(self.run.name, self.root)["events"]), {})


class SummaryTests(RunFixture):
    def summarize(self, events, *, replay_steps=None, prefix_steps=None):
        journal(self.run, events)
        if replay_steps is not None:
            write(self.run, "replay.json", {"steps": [{} for _ in range(replay_steps)]})
        if prefix_steps is not None:
            write(self.run, "prefix.json", {"steps": [{} for _ in range(prefix_steps)]})
        write(self.run, "metrics.json", {"status": "completed", "agent_version": "0.3.0",
                                         "input_tokens": 100, "output_tokens": 5})
        with patch.object(match, "atomic_json", runtime.atomic_json):
            match.write_trace_summary(self.run)
        return json.loads((self.run / "trace-summary.json").read_text(encoding="utf-8"))

    def test_summary_binds_the_verified_document_and_counts_decisions(self):
        summary = self.summarize([*decision_events(0), *decision_events(1)], replay_steps=12)
        self.assertEqual(summary["game_document"], "completed_replay")
        self.assertEqual(summary["game_plies"], 12)
        self.assertEqual(summary["journal_decisions"], 2)
        self.assertTrue(summary["journal_recorded"])
        self.assertEqual(summary["ambiguous_plies"], [])
        stages = summary["decisions"]["0"]["stages"]
        self.assertEqual([s["stage"] for s in stages], ["helper", "family"])
        self.assertEqual(stages[1]["attempts"][0]["selected_id"], "take_tokens")
        self.assertTrue(stages[1]["payload_snapshot_recorded"])
        self.assertEqual(stages[1]["candidate_ids"], ["take_tokens"])
        self.assertEqual(summary["decisions"]["0"]["selected_index"], 0)
        self.assertEqual(summary["decisions"]["0"]["routed_out"], 4)

    def test_a_truncated_run_is_not_reported_as_a_completed_one(self):
        summary = self.summarize(decision_events(0), prefix_steps=4)
        self.assertEqual(summary["game_document"], "truncated_prefix")
        self.assertEqual(summary["game_plies"], 4)

    def test_a_run_with_no_document_says_so_and_still_records_the_journal(self):
        summary = self.summarize(decision_events(0))
        self.assertEqual(summary["game_document"], "unavailable")
        self.assertIsNone(summary["game_plies"])
        self.assertEqual(summary["journal_decisions"], 1)

    def test_duplicate_plies_are_flagged_and_the_latest_entry_is_the_one_described(self):
        first = decision_events(3, obs_hash="old")
        second = decision_events(3, obs_hash="new", recorded=None)
        summary = self.summarize([*first, *second], replay_steps=10)
        self.assertEqual(summary["ambiguous_plies"], [{"ply": 3, "count": 2}])
        self.assertEqual(summary["decisions"]["3"]["observation_hash"], "new")

    def test_an_unreadable_journal_does_not_prevent_the_game_artifact_from_existing(self):
        (self.run / "metrics.jsonl").write_text("not json\n", encoding="utf-8")
        write(self.run, "replay.json", {"steps": [{}]})
        with self.assertRaises(trace_reader.TraceError):
            match.write_trace_summary(self.run)
        # The failure is in the trace projection only; the replay itself is untouched.
        self.assertTrue((self.run / "replay.json").is_file())
        self.assertFalse((self.run / "trace-summary.json").exists())


class SnapshotTests(unittest.TestCase):
    def test_only_a_clean_application_payload_is_published(self):
        payload = {"state": {"viewer": 0}, "model": "jev-latest", "questions": {"family": {}}}
        self.assertEqual(runtime.safe_payload(payload), payload)

    def test_a_payload_with_an_unexpected_field_is_dropped_not_partially_copied(self):
        for extra in [{"authorization": "Bearer SECRET"}, {"api_key": "SECRET"}, {"extra": 1}]:
            bad = {"state": {}, "model": "m", "questions": {}, **extra}
            self.assertIsNone(runtime.safe_payload(bad), extra)

    def test_an_oversized_payload_keeps_its_hash_and_reports_no_snapshot(self):
        big = {"state": {"x": "y" * 300_000}, "model": "m", "questions": {}}
        self.assertIsNone(runtime.safe_payload(big))
        self.assertEqual(len(runtime.digest(big)), 64)

    def test_identity_keeps_only_allowlisted_scalars(self):
        kept = runtime.safe_identity({"game_id": "g", "run_id": "r", "seat": 0, "ply": 3,
                                      "replay_document_hash": "h", "secret": "SECRET",
                                      "nested": {"a": 1}})
        self.assertEqual(kept, {"game_id": "g", "run_id": "r", "seat": 0, "ply": 3,
                                "replay_document_hash": "h"})
        self.assertIsNone(runtime.safe_identity({"secret": "x"}))
        self.assertIsNone(runtime.safe_identity({"run_id": "x" * 500}))

    def test_session_records_the_identity_and_the_snapshot_on_the_journal(self):
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(directory, ignore_errors=True))
        session = runtime.Session("jev-latest", summary_path=directory / "metrics.json")
        try:
            session.identify({"game_id": "g", "run_id": "r", "seat": 1})
            session.request_id = 4
            session.emit("decision_start", ply=7, actor=1)
        finally:
            session.finish("completed")
        records = [json.loads(l) for l in (directory / "metrics.jsonl").read_text().splitlines()]
        bound = next(r for r in records if r["event"] == "identity_bound")
        self.assertEqual(bound["identity"], {"game_id": "g", "run_id": "r", "seat": 1})
        self.assertEqual(session.metrics["identity"]["seat"], 1)
        self.assertEqual(session.metrics["schema_version"], 4)
        self.assertEqual(session.metrics["agent_version"], "0.4.0")

    def test_the_registered_identity_is_never_invented_from_an_unknown_message(self):
        session = runtime.Session("jev-latest")
        for value in [{"run_id": ""}, {}, {"secret": "x"}, None]:
            with self.assertRaises(runtime.AgentFault):
                session.identify(value)
        self.assertIsNone(session.identity)


class AgentBindingTests(unittest.TestCase):
    def test_game_start_binds_the_run_id_only_when_the_runner_declared_one(self):
        import agent

        fixture = [json.loads(x) for x in
                   (Path(agent.HERE).parents[0] / "fixtures/protocol/v0.5/normal-game.ndjson")
                   .read_text().splitlines()]

        sessions = []

        def drive_with(game_start, metrics_path):
            lines = []
            for message in fixture:
                message = dict(message)
                if message["type"] == "game_start" and game_start is not None:
                    message["run_trace_id"] = game_start
                lines.append(json.dumps(message))
            session = runtime.Session(agent.MODEL, summary_path=metrics_path)
            sessions.append(session)
            # The fixture reaches a decision; an empty fake response fails closed.
            # Only the identity binding recorded before that fault is asserted.
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(agent.AgentFault):
                    agent.drive(iter(lines), lambda *a, **k: {}, session)
            return session

        directory = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(directory, ignore_errors=True))
        try:
            bound = drive_with("run-abc", directory / "with.json")
            self.assertEqual(bound.identity["run_id"], "run-abc")
            self.assertIsNone(drive_with(None, directory / "without.json").identity)
        finally:
            for session in sessions:
                if session.stream:
                    session.stream.close()

    def test_decision_start_carries_the_ply_the_arena_reported(self):
        source = (Path(__file__).parent / "agent.py").read_text(encoding="utf-8")
        self.assertIn("ply=msg.get(\"ply\")", source)
        self.assertIn("observation_hash=obs_hash", source)


if __name__ == "__main__":
    unittest.main()
