from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SCRIPT = REPO_ROOT / "training" / "m17_gpu" / "m39a_eval_provenance.py"
G2_PROV = REPO_ROOT / "local-artifacts" / "m39a-eval-g2" / "g2-provenance.json"
G3_PROV = REPO_ROOT / "local-artifacts" / "m39a-eval-g3" / "g3-provenance.json"

pytestmark = pytest.mark.skipif(
    not G2_PROV.is_file(),
    reason="evaluation provenance ledgers are local-only",
)

_MODULE = None


def _module():
    global _MODULE
    if _MODULE is None:
        sys.path.insert(0, str(REPO_ROOT / "training" / "m17_gpu"))
        spec = importlib.util.spec_from_file_location(
            "m39a_eval_provenance", SCRIPT
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _MODULE = module
    return _MODULE


def _expect_rejection(module, ledger_path: Path, *fragments: str) -> None:
    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        try:
            module.validate(ledger_path)
        except SystemExit:
            text = stderr.getvalue()
            for fragment in fragments:
                assert fragment in text, f"expected {fragment!r} in:\n{text}"
            return
        except Exception as error:  # noqa: BLE001
            pytest.fail(f"expected SystemExit, got {error!r}")
    pytest.fail("ledger was accepted but must be rejected")


def _copy(tmp_path: Path, source: Path) -> Path:
    path = tmp_path / source.name
    path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def test_valid_g2_provenance_passes(tmp_path: Path) -> None:
    module = _module()
    path = _copy(tmp_path, G2_PROV)
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        module.validate(path)
    assert '"status": "valid"' in stdout.getvalue()


def test_valid_g3_provenance_passes(tmp_path: Path) -> None:
    module = _module()
    path = _copy(tmp_path, G3_PROV)
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        module.validate(path)
    assert '"status": "valid"' in stdout.getvalue()


def test_tampered_report_hash_is_rejected(tmp_path: Path) -> None:
    module = _module()
    path = _copy(tmp_path, G2_PROV)
    ledger = json.loads(path.read_text(encoding="utf-8"))
    for row in ledger["rows"]:
        if row["report_sha256"] is not None:
            row["report_sha256"] = "f" * 64
            break
    path.write_text(json.dumps(ledger), encoding="utf-8")
    _expect_rejection(module, path, "report_sha256 mismatch")


def test_forged_outcome_is_rejected(tmp_path: Path) -> None:
    """An outcome not matching the on-disk replay/result fails."""
    module = _module()
    path = _copy(tmp_path, G2_PROV)
    ledger = json.loads(path.read_text(encoding="utf-8"))
    for row in ledger["rows"]:
        if row["outcome"] is not None:
            row["outcome"] = "win" if row["outcome"] != "win" else "loss"
            break
    path.write_text(json.dumps(ledger), encoding="utf-8")
    _expect_rejection(module, path, "outcome mismatch")


def test_swapped_seed_binding_is_rejected(tmp_path: Path) -> None:
    """A row claiming the wrong slot seed fails the artifact binding."""
    module = _module()
    path = _copy(tmp_path, G2_PROV)
    ledger = json.loads(path.read_text(encoding="utf-8"))
    ledger["rows"][10]["seed"] = ledger["rows"][10]["seed"] + 1
    path.write_text(json.dumps(ledger), encoding="utf-8")
    _expect_rejection(module, path, "mismatch")


def test_hidden_nontermination_row_is_rejected(tmp_path: Path) -> None:
    """Claiming the ply-limit slot completed fails: no report/replay exist,
    so the adversarial rebuild cannot reproduce the claimed outcome."""
    module = _module()
    path = _copy(tmp_path, G2_PROV)
    ledger = json.loads(path.read_text(encoding="utf-8"))
    for row in ledger["rows"]:
        if row["deterministic_nontermination"]:
            row["deterministic_nontermination"] = False
            row["completed"] = True
            row["outcome"] = "win"
    path.write_text(json.dumps(ledger), encoding="utf-8")
    _expect_rejection(module, path, "mismatch")


def test_forged_bindings_are_rejected(tmp_path: Path) -> None:
    module = _module()
    path = _copy(tmp_path, G2_PROV)
    ledger = json.loads(path.read_text(encoding="utf-8"))
    ledger["bindings"]["executable_sha256"] = "f" * 64
    path.write_text(json.dumps(ledger), encoding="utf-8")
    _expect_rejection(module, path, "binding executable_sha256 mismatch")


def test_dropped_nontermination_evidence_is_rejected(tmp_path: Path) -> None:
    module = _module()
    path = _copy(tmp_path, G2_PROV)
    ledger = json.loads(path.read_text(encoding="utf-8"))
    ledger["nontermination_evidence"]["files"]["stderr.txt"] = "f" * 64
    path.write_text(json.dumps(ledger), encoding="utf-8")
    _expect_rejection(module, path, "stderr.txt SHA mismatch")


def test_tampered_replay_hash_is_rejected(tmp_path: Path) -> None:
    module = _module()
    path = _copy(tmp_path, G3_PROV)
    ledger = json.loads(path.read_text(encoding="utf-8"))
    for row in ledger["rows"]:
        if row["replay_sha256"] is not None:
            row["replay_sha256"] = "0" * 64
            break
    path.write_text(json.dumps(ledger), encoding="utf-8")
    _expect_rejection(module, path, "replay_sha256 mismatch")
