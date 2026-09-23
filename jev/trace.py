"""Read one local Jev run and project it into a per-step interaction trace.

This module is the *only* reader of `local-artifacts/jev/<run>/` journals. It is
read-only by construction: the verified replay (or verified truncated prefix) is
the game authority, and the agent journal is joined to it; the journal can never
add, change or remove a game action.

Correlation rules (each one exists because the naive version was wrong):

* plies, not request ids. The arena's `request_id` is match-global and is reset
  when a rollout resumes from a prefix, so it is never used to address a ply.
* a decision is matched by the ``ply`` the referee reported on the request, then
  confirmed against the pre-action observation hash and the action that was
  actually recorded. A mismatch is reported as a mismatch; it is not smoothed
  over into "no trace".
* every attempt of a stage is kept, so a retry stays visible under one decision.

Nothing here runs a model, a reviewer, or any paid inference.
"""
from __future__ import annotations

import json
from pathlib import Path

# Only these event kinds exist in the journal. Unknown kinds are ignored, so a
# future field cannot silently become part of a claim about behaviour.
TRACE_EVENTS = ("decision_start", "helper_complete", "request_start", "request_error",
                "retry_wait", "request_received", "decision_choice", "action_sent")

# A single journal line, and a whole journal, are bounded before parsing.
MAX_JOURNAL_LINE_BYTES = 4_000_000
MAX_JOURNAL_BYTES = 64_000_000


class TraceError(Exception):
    """A run exists but its trace cannot be read safely."""

    def __init__(self, message: str, code: str = "trace_unavailable"):
        super().__init__(message)
        self.code = code


def _safe_component(value: str) -> bool:
    return (isinstance(value, str) and 0 < len(value) <= 128
            and value not in (".", "..")
            and all(c.isascii() and (c.isalnum() or c in "-_") for c in value))


def read_run(run_id: str, root: Path) -> dict:
    """Load the journal, metrics and config of one run directory."""
    if not _safe_component(run_id):
        raise TraceError(f"invalid run id `{run_id}`")
    directory = (root / run_id).resolve()
    if directory.parent != root.resolve():
        raise TraceError(f"invalid run id `{run_id}`")
    if not directory.is_dir():
        raise TraceError(f"unknown run `{run_id}`")

    journal = directory / "metrics.jsonl"
    events = []
    if journal.is_file():
        if journal.stat().st_size > MAX_JOURNAL_BYTES:
            raise TraceError("trace journal is too large", "trace_too_large")
        with journal.open("r", encoding="utf-8") as stream:
            for number, line in enumerate(stream, 1):
                if len(line) > MAX_JOURNAL_LINE_BYTES:
                    raise TraceError(f"trace journal line {number} is too large", "trace_line_too_large")
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except ValueError:
                    raise TraceError(f"trace journal line {number} is not valid JSON",
                                     "trace_corrupt") from None
                if isinstance(value, dict) and value.get("event") in TRACE_EVENTS:
                    events.append(value)

    def optional(name):
        path = directory / name
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return None

    return {"run_id": run_id, "directory": str(directory), "events": events,
            "metrics": optional("metrics.json"), "config": optional("config.json"),
            "manifest": optional("manifest.json"), "runner_status": optional("runner-status.json"),
            "has_verified_game": (directory / "replay.json").is_file() or (directory / "prefix.json").is_file()}


def index_by_ply(events: list[dict]) -> dict[int, dict]:
    """Group one run's decisions by the ply the referee reported.

    A ply seen more than once (a resumed rollout, or two journalled attempts)
    keeps both and is marked ambiguous; the caller must surface that rather than
    pick one silently.
    """
    decisions: dict[int, list[dict]] = {}
    open_entry: dict | None = None
    for event in events:
        kind = event.get("event")
        if kind == "decision_start":
            ply = event.get("ply")
            if isinstance(ply, int) and ply >= 0:
                entry = {"ply": ply, "events": [],
                         "observation_hash": event.get("observation_hash"),
                         "actor": event.get("actor")}
                decisions.setdefault(ply, []).append(entry)
                open_entry = entry
            else:
                # Without a reported ply this call cannot be addressed to a step.
                open_entry = None
            continue
        if open_entry is not None:
            open_entry["events"].append(event)
    return decisions


def summarize(entry: dict) -> dict:
    """Project one decision's raw events into what the viewer renders."""
    stages = []
    stage = None
    for event in entry["events"]:
        kind = event.get("event")
        if kind == "helper_complete":
            stages.append({"stage": "helper", "attempts": [], "latency_ms": event.get("latency_ms")})
            stage = None
            continue
        if kind == "request_start":
            stage = {"stage": event.get("stage"), "attempts": [], "candidates": event.get("candidates"),
                     "candidate_ids": event.get("candidate_ids"), "requested_model": event.get("requested_model"),
                     "payload_sha256": event.get("payload_sha256"),
                     "payload_snapshot": event.get("payload_snapshot"),
                     "payload_snapshot_recorded": event.get("payload_snapshot_recorded")}
            stages.append(stage)
            continue
        if stage is None:
            continue
        if kind == "request_error":
            stage["attempts"].append({"outcome": "error", "code": event.get("code"),
                                      "http_status": event.get("http_status"),
                                      "latency_ms": event.get("latency_ms")})
        elif kind == "retry_wait":
            stage["attempts"].append({"outcome": "retry_wait", "seconds": event.get("seconds")})
        elif kind == "request_received":
            stage["attempts"].append({"outcome": "received", "selected_id": event.get("selected_id"),
                                      "returned_model": event.get("returned_model"),
                                      "usage": event.get("usage"),
                                      "probabilities": event.get("probabilities"),
                                      "confidence": event.get("confidence"),
                                      "latency_ms": event.get("latency_ms")})
    choice = next((e for e in entry["events"] if e.get("event") == "decision_choice"), None)
    return {"ply": entry["ply"], "actor": entry.get("actor"),
            "observation_hash": entry.get("observation_hash"), "stages": stages,
            "family": (choice or {}).get("family"),
            "selected_index": (choice or {}).get("selected_index"),
            "selected_action": (choice or {}).get("selected_action"),
            "offered_indices": (choice or {}).get("offered_indices"),
            "noops_removed": (choice or {}).get("noops_removed"),
            "routed_out": (choice or {}).get("routed_out"),
            "cap_removed": (choice or {}).get("cap_removed"),
            "action_sent": any(e.get("event") == "action_sent" for e in entry["events"])}
