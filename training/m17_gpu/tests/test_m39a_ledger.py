from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
LEDGER_SCRIPT = REPO_ROOT / "training" / "m17_gpu" / "m39a_provenance_ledger.py"
REAL_LEDGER = (
    REPO_ROOT / "local-artifacts" / "m39a-formal-run" / "provenance-ledger.json"
)

pytestmark = pytest.mark.skipif(
    not REAL_LEDGER.is_file(),
    reason="formal run ledger is local-only",
)

_MODULE = None


def _ledger_module():
    global _MODULE
    if _MODULE is None:
        sys.path.insert(0, str(REPO_ROOT / "training" / "m17_gpu"))
        spec = importlib.util.spec_from_file_location(
            "m39a_provenance_ledger", LEDGER_SCRIPT
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _MODULE = module
    return _MODULE


# One shared recomputation cache across tests: hashing 678 MB batches per
# test would take minutes; the artifacts do not change during a test run.
_CYCLE_CACHE: dict[int, dict] = {}


@pytest.fixture()
def module_with_cache(monkeypatch: pytest.MonkeyPatch):
    module = _ledger_module()

    original = module.cycle_attestation

    def cached(cycle: int):
        if cycle not in _CYCLE_CACHE:
            _CYCLE_CACHE[cycle] = original(cycle)
        return dict(_CYCLE_CACHE[cycle])

    monkeypatch.setattr(module, "cycle_attestation", cached)
    yield module


@pytest.fixture()
def ledger_copy(tmp_path: Path) -> Path:
    path = tmp_path / "ledger.json"
    path.write_text(REAL_LEDGER.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def _validate(module, ledger_path: Path) -> tuple[int, str]:
    try:
        module.validate(ledger_path)
        return 0, ""
    except SystemExit as exit_error:
        code = exit_error.code
        message = str(exit_error)
        return (code if isinstance(code, int) else 1), message
    except Exception as error:  # noqa: BLE001 - test harness
        return 1, str(error)


def test_valid_ledger_passes(module_with_cache, ledger_copy: Path) -> None:
    # The real validate prints failures to stderr and raises SystemExit;
    # capture stderr content via monkeypatched print target instead.
    import io

    stderr = io.StringIO()
    module = module_with_cache
    captured: list[str] = []

    def fake_print(*args, **kwargs):
        if kwargs.get("file") is not None:
            captured.append(" ".join(str(a) for a in args))

    original_print = __builtins__["print"] if isinstance(__builtins__, dict) else __builtins__.print
    try:
        module.validate(ledger_copy)
    except SystemExit as error:
        captured_text = "\n".join(captured)
        pytest.fail(f"valid ledger must pass, got exit {error.code}\n{captured_text}")


def _expect_rejection(module, ledger_copy: Path, *fragments: str) -> None:
    import contextlib
    import io

    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        try:
            module.validate(ledger_copy)
        except SystemExit:
            text = stderr.getvalue()
            for fragment in fragments:
                assert fragment in text, f"expected {fragment!r} in:\n{text}"
            return
        except Exception as error:  # noqa: BLE001
            pytest.fail(f"expected SystemExit, got {error!r}")
    pytest.fail("ledger was accepted but must be rejected")


def test_forged_segment_source_is_rejected(module_with_cache, ledger_copy: Path) -> None:
    ledger = json.loads(ledger_copy.read_text(encoding="utf-8"))
    for segment in ledger["segments"]:
        segment["source_commit"] = "ARBITRARY-UNVERIFIED-SOURCE"
        segment["agent_source_sha256"] = "f" * 64
        segment["driver_source_sha256"] = "f" * 64
    ledger_copy.write_text(json.dumps(ledger), encoding="utf-8")
    _expect_rejection(
        module_with_cache,
        ledger_copy,
        "agent_source_sha256 mismatch",
        "source_commit mismatch",
    )


def test_empty_incidents_are_rejected(module_with_cache, ledger_copy: Path) -> None:
    ledger = json.loads(ledger_copy.read_text(encoding="utf-8"))
    ledger["incidents"] = []
    ledger_copy.write_text(json.dumps(ledger), encoding="utf-8")
    _expect_rejection(
        module_with_cache, ledger_copy, "incident count 0 != frozen expectation"
    )


def test_forged_checkpoint_semantic_hash_is_rejected(
    module_with_cache, ledger_copy: Path
) -> None:
    ledger = json.loads(ledger_copy.read_text(encoding="utf-8"))
    ledger["cycles"][3]["checkpoint_hash"] = "f" * 64
    ledger_copy.write_text(json.dumps(ledger), encoding="utf-8")
    _expect_rejection(module_with_cache, ledger_copy, "checkpoint_hash mismatch")


def test_forged_truncation_stats_are_rejected(
    module_with_cache, ledger_copy: Path
) -> None:
    ledger = json.loads(ledger_copy.read_text(encoding="utf-8"))
    ledger["cycles"][5]["truncated_games"] = 999
    ledger["cycles"][5]["observed_max_plies"] = 9999
    ledger_copy.write_text(json.dumps(ledger), encoding="utf-8")
    _expect_rejection(
        module_with_cache,
        ledger_copy,
        "truncated_games mismatch",
        "observed_max_plies mismatch",
    )


def test_result_block_must_match_recomputed_counts(
    module_with_cache, ledger_copy: Path
) -> None:
    ledger = json.loads(ledger_copy.read_text(encoding="utf-8"))
    ledger["result"]["truncated_games"] = 999
    ledger_copy.write_text(json.dumps(ledger), encoding="utf-8")
    _expect_rejection(
        module_with_cache, ledger_copy, "result block does not match the frozen"
    )


def test_missing_bindings_are_rejected(module_with_cache, ledger_copy: Path) -> None:
    ledger = json.loads(ledger_copy.read_text(encoding="utf-8"))
    del ledger["bindings"]
    ledger_copy.write_text(json.dumps(ledger), encoding="utf-8")
    _expect_rejection(module_with_cache, ledger_copy, "ledger has no bindings object")


def test_tampered_incident_evidence_sha_is_rejected(
    module_with_cache, ledger_copy: Path
) -> None:
    ledger = json.loads(ledger_copy.read_text(encoding="utf-8"))
    for incident in ledger["incidents"]:
        if incident["name"] == "cycle-7-game-3335-agent-eof":
            incident["files"]["arena-report.json"] = "f" * 64
    ledger_copy.write_text(json.dumps(ledger), encoding="utf-8")
    _expect_rejection(module_with_cache, ledger_copy, "files mismatch")


def test_dropped_cycle_is_rejected(module_with_cache, ledger_copy: Path) -> None:
    ledger = json.loads(ledger_copy.read_text(encoding="utf-8"))
    ledger["cycles"] = ledger["cycles"][:7]
    ledger_copy.write_text(json.dumps(ledger), encoding="utf-8")
    _expect_rejection(module_with_cache, ledger_copy, "must list exactly 8 cycles")


def test_removed_segment_is_rejected(module_with_cache, ledger_copy: Path) -> None:
    ledger = json.loads(ledger_copy.read_text(encoding="utf-8"))
    ledger["segments"] = [
        segment
        for segment in ledger["segments"]
        if "ABORTED" not in segment["segment"]
    ]
    ledger_copy.write_text(json.dumps(ledger), encoding="utf-8")
    _expect_rejection(module_with_cache, ledger_copy, "segment count")
