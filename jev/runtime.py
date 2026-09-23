"""Local lifecycle utilities. No credential, raw HTTP body or exception text logging."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time

AGENT_VERSION = "0.2.0"


class AgentFault(Exception):
    def __init__(self, message: str, code: str = "agent_error"):
        super().__init__(message)
        self.code = code


class ServiceFault(AgentFault):
    def __init__(self, code: str, http_status: int | None = None, retry_after: float = 0.0):
        super().__init__(code, code)
        self.http_status = http_status
        self.retry_after = retry_after

    @property
    def retryable(self) -> bool:
        # Timeouts have ambiguous billing and no remaining-time guarantee; don't retry them.
        return self.http_status in (429, 502, 503, 504, 529) or self.code == "connection_error"


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(encode(value).encode()).hexdigest()


def atomic_json(path: Path, value) -> None:
    temporary = path.with_name(path.name + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            stream.write(encode(value) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def run_child(command, *, timeout: float, input: str = "", **kwargs):
    """One owned child; timeout/cancellation kills and reaps it before returning.

    HTTP worker and score helper have no descendants. Arena-tree ownership is
    handled by match.py instead; never pass an arena process to this helper.
    """
    with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True, encoding="utf-8", **kwargs) as proc:
        try:
            stdout, stderr = proc.communicate(input, timeout=timeout)
        except BaseException:
            proc.kill()
            proc.communicate()
            raise
        return subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)


class Deadline:
    def __init__(self, milliseconds: int, clock=time.monotonic):
        if type(milliseconds) is not int or not 0 < milliseconds <= 86_400_000:
            raise AgentFault("invalid decision deadline", "invalid_deadline")
        self.clock = clock
        # Time reserved for final local log/flush and action delivery.
        self.end = clock() + milliseconds / 1000 - min(0.5, milliseconds / 10000)

    def remaining(self, cap: float | None = None) -> float:
        left = self.end - self.clock()
        if left <= 0:
            raise AgentFault("decision deadline exhausted", "decision_timeout")
        return min(left, cap) if cap is not None else left


def usage_values(response) -> dict | None:
    u = response.get("usage") if isinstance(response, dict) else None
    if not isinstance(u, dict):
        return None
    if any(type(u.get(k)) is not int or u[k] < 0 for k in ("input_tokens", "output_tokens")):
        return None
    return {k: u[k] for k in ("input_tokens", "output_tokens")}


def safe_model(value) -> str | None:
    return value if isinstance(value, str) and re.fullmatch(r"jev[-A-Za-z0-9._:]{1,70}", value) else None


class Session:
    def __init__(self, model: str, *, max_calls=100, summary_path: Path | None = None,
                 clock=time.monotonic, sleeper=time.sleep):
        if type(max_calls) is not int or not 1 <= max_calls <= 10000:
            raise AgentFault("invalid API call budget", "invalid_budget")
        self.max_calls, self.clock, self.sleep = max_calls, clock, sleeper
        self.summary_path = summary_path
        self.stream = None
        self.request_id = None
        self.start = clock()
        self.metrics = dict(schema_version=2, agent_version=AGENT_VERSION, status="running", model=model,
                            model_version=None, model_versions=[], max_api_calls=max_calls,
                            api_calls=0, stage1_calls=0, stage2_calls=0, unknown_usage_attempts=0,
                            decisions=0, families_offered=0, options_offered=0, options_omitted=0,
                            noops_removed=0, routed_out=0, cap_removed=0, input_tokens=0, output_tokens=0)
        if summary_path is not None:
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            if summary_path.exists():
                raise AgentFault("metrics output exists", "output_exists")
            self.stream = summary_path.with_suffix(".jsonl").open("x", encoding="utf-8")
        self.emit("session_start", max_api_calls=max_calls, agent_version=AGENT_VERSION, requested_model=model)

    def emit(self, event, **fields):
        record = dict(event=event, request_id=self.request_id, elapsed_ms=round((self.clock()-self.start)*1000, 3), **fields)
        if self.stream:
            self.stream.write(encode(record) + "\n")
            self.stream.flush()
            os.fsync(self.stream.fileno())
        if self.summary_path:
            atomic_json(self.summary_path, self.metrics)

    def finish(self, status, error_code=None):
        self.metrics.update(status=status, error_code=error_code)
        try:
            self.emit("session_end", status=status, error_code=error_code)
        finally:
            if self.stream:
                self.stream.close()

    def ask(self, payload, deadline: Deadline, call):
        question_id = next(iter(payload["questions"]))
        criteria = payload["questions"][question_id]["criteria"]
        stage = "stage1_calls" if question_id == "family" else "stage2_calls"
        for attempt in range(2):
            if self.metrics["api_calls"] >= self.max_calls:
                raise AgentFault("Jev API call budget exhausted", "api_budget")
            deadline.remaining()
            self.metrics["api_calls"] += 1
            self.metrics[stage] += 1
            self.metrics["unknown_usage_attempts"] += 1
            started = self.clock()
            self.emit("request_start", stage=question_id, attempt=attempt+1,
                      payload_sha256=digest(payload), candidate_ids=list(criteria),
                      candidates=criteria, requested_model=payload["model"])
            try:
                response = call(payload, timeout=deadline.remaining(18.0))
            except ServiceFault as exc:
                self.emit("request_error", stage=question_id, attempt=attempt+1, code=exc.code,
                          http_status=exc.http_status, latency_ms=round((self.clock()-started)*1000, 3))
                if not exc.retryable or attempt == 1:
                    raise
                wait = max(0.5, exc.retry_after)
                if self.metrics["api_calls"] >= self.max_calls:
                    raise AgentFault("Jev API call budget exhausted", "api_budget")
                if wait + 0.1 >= deadline.remaining():
                    raise AgentFault("insufficient time for retry", "decision_timeout") from None
                self.emit("retry_wait", stage=question_id, seconds=wait)
                self.sleep(wait)
                continue
            except BaseException as exc:
                # Never log arbitrary exception text from dependencies or injected transports.
                self.emit("request_error", stage=question_id, attempt=attempt+1,
                          code="cancelled" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "local_error",
                          latency_ms=round((self.clock()-started)*1000, 3))
                raise
            usage = usage_values(response)
            if usage is not None:
                self.metrics["unknown_usage_attempts"] -= 1
                for key, value in usage.items():
                    self.metrics[key] += value
            model = safe_model(response.get("model")) if isinstance(response, dict) else None
            if model:
                self.metrics["model_version"] = model
                if model not in self.metrics["model_versions"]:
                    self.metrics["model_versions"].append(model)
            answer = response.get("answers", {}) if isinstance(response, dict) else {}
            answer = answer.get(question_id, {}) if isinstance(answer, dict) else {}
            choice = answer.get("choice") if isinstance(answer, dict) else None
            choice = choice if isinstance(choice, str) and choice in criteria else None
            probabilities = answer.get("probabilities") if isinstance(answer, dict) else None
            if not isinstance(probabilities, dict) or set(probabilities) != set(criteria) or any(
                type(v) not in (float, int) or not math.isfinite(v) or not 0 <= v <= 1 for v in probabilities.values()
            ):
                probabilities = None
            confidence = answer.get("confidence") if isinstance(answer, dict) else None
            if type(confidence) not in (float, int) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
                confidence = None
            self.emit("request_received", stage=question_id, attempt=attempt+1, selected_id=choice,
                      returned_model=model, usage=usage, probabilities=probabilities, confidence=confidence,
                      latency_ms=round((self.clock()-started)*1000, 3))
            # Even a late/invalid response retains reported usage, but never produces an action.
            deadline.remaining()
            return response
