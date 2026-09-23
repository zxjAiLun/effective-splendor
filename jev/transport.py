"""One-request TypeSafe HTTPS worker; parent enforces wall-clock deadline by reaping it."""
from __future__ import annotations

import json
import math
import os
import ssl
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.request

from runtime import AgentFault, ServiceFault, encode, run_child

HERE = Path(__file__).resolve().parent
API_URL = "https://api.typesafe.ai/v1/systemone"
MAX_RESPONSE_BYTES = 256_000


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Reject same-origin redirects too: this endpoint is fixed. Never forward Authorization.
        raise ServiceFault("redirect_blocked", code)


def credential() -> str:
    value = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not value:
        path = Path(os.environ.get("TYPESAFE_API_KEY_FILE", str(HERE.parent / "TYPESAFE_API_KEY")))
        try:
            value = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            raise ServiceFault("credential_unavailable") from None
    if not value or not value.isascii() or any(c.isspace() or ord(c) < 33 for c in value):
        raise ServiceFault("credential_invalid")
    return value


def https_request(payload: dict, timeout: float) -> dict:
    request = urllib.request.Request(API_URL, data=encode(payload).encode(), method="POST", headers={
        "Authorization": "Bearer " + credential(), "Content-Type": "application/json"})
    opener = urllib.request.build_opener(NoRedirect())  # Default SSL verification remains enabled.
    try:
        with opener.open(request, timeout=timeout) as response:
            if response.status != 200 or response.geturl() != API_URL:
                raise ServiceFault("unexpected_response")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ServiceFault("response_too_large")
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        retry_after = 0.0
        try:
            retry_after = float(exc.headers.get("Retry-After", "0"))
            if not math.isfinite(retry_after) or retry_after < 0:
                retry_after = 0.0
        except (ValueError, TypeError, AttributeError):
            pass
        exc.close()  # Don't read, persist or echo the response body, reason, URL or headers.
        raise ServiceFault("http_error", exc.code, retry_after) from None
    except (TimeoutError, subprocess.TimeoutExpired):
        raise ServiceFault("http_timeout") from None
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise ServiceFault("http_timeout") from None
        if isinstance(exc.reason, ssl.SSLError):
            raise ServiceFault("tls_error") from None
        raise ServiceFault("connection_error") from None
    except ssl.SSLError:
        raise ServiceFault("tls_error") from None
    except OSError:
        raise ServiceFault("connection_error") from None
    except (ValueError, UnicodeError):
        raise ServiceFault("invalid_json") from None


def evaluate(payload: dict, timeout: float = 18.0) -> dict:
    if not math.isfinite(timeout) or timeout <= 0:
        raise AgentFault("decision deadline exhausted", "decision_timeout")
    try:
        result = run_child([sys.executable, str(HERE / "transport.py"), str(timeout)],
                           input=encode(payload), timeout=timeout)
    except subprocess.TimeoutExpired:
        raise ServiceFault("http_timeout") from None
    except OSError:
        raise ServiceFault("worker_unavailable") from None
    if result.returncode != 0:
        raise ServiceFault("worker_failed")
    try:
        envelope = json.loads(result.stdout)
        if envelope["ok"] is True:
            return envelope["response"]
        code = envelope["code"]
        if code not in {"redirect_blocked", "credential_unavailable", "credential_invalid", "unexpected_response",
                        "response_too_large", "http_error", "http_timeout", "tls_error", "connection_error", "invalid_json"}:
            raise ValueError()
        status = envelope.get("http_status")
        if status is not None and (type(status) is not int or not 100 <= status <= 599):
            raise ValueError()
        retry_after = envelope.get("retry_after", 0.0)
        if type(retry_after) not in (float, int) or not math.isfinite(retry_after) or retry_after < 0:
            raise ValueError()
        raise ServiceFault(code, status, retry_after)
    except (KeyError, TypeError, ValueError):
        raise ServiceFault("worker_invalid_response") from None


def worker_main() -> None:
    try:
        timeout = float(sys.argv[1])
        raw = sys.stdin.buffer.read(2_000_001)
        if len(raw) > 2_000_000 or not math.isfinite(timeout) or timeout <= 0:
            raise ServiceFault("invalid_json")
        response = https_request(json.loads(raw), timeout)
        print(encode({"ok": True, "response": response}))
    except ServiceFault as exc:
        print(encode({"ok": False, "code": exc.code, "http_status": exc.http_status, "retry_after": exc.retry_after}))
    except (ValueError, TypeError, IndexError, OSError):
        print(encode({"ok": False, "code": "invalid_json"}))


if __name__ == "__main__":
    worker_main()
