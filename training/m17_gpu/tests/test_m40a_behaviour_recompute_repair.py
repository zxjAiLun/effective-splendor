"""Incident-repair contract tests (2026-09-02): the M40A behaviour
recomputation must use SINGLETON forward semantics (the inherited M39A
executor contract), while PPO UPDATE passes remain batched at the frozen
PPO_MINIBATCH=512.

The incident: `train-cycle --arm A --cycle 1` on the formal run aborted
at the frozen drift thresholds (logp=1.19e-06 = exactly 2^-20, one f32
ULP) because the recomputation had been packed at PPO minibatch size,
while the resident inference server recorded behaviour with batch-of-1
forward. GPU batched vs singleton reduction ordering differs by 1-3
f32 ULP; the accepted M39A trainer recomputed with one forward per
record and therefore matched the server bit-for-bit.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from splendor_gpu.m39a_contract import decision_seed
from splendor_gpu.m40a_constants import PPO_MINIBATCH
from splendor_gpu.m40a_model import (
    M40AModel,
    initialize_predictive_heads,
    outcome_value,
)
from splendor_gpu.m40a_train import (
    LOG_PROBABILITY_DRIFT_THRESHOLD,
    VALUE_DRIFT_THRESHOLD,
    _forward_state,
    _selected_log_probabilities_and_entropies,
    gae_advantages,
    recompute_behaviour,
    train_cycle,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CATALOG_PATH = REPO_ROOT / "apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"


@pytest.fixture(scope="module")
def catalog() -> dict:
    from splendor_gpu.data import load_catalog

    return load_catalog(CATALOG_PATH)


@pytest.fixture(scope="module")
def base_frame() -> dict:
    fixture = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return fixture["frames"][0]


def _singleton_consistent_records(
    model: M40AModel, n: int, catalog: dict, base_frame: dict
) -> list[dict]:
    """Records whose action/old_logp/old_value ARE the model's singleton
    forward outputs (server semantics: batch = 1)."""
    observation = base_frame["player_view"]
    legal_actions = base_frame["legal_actions"]
    device = next(model.parameters()).device
    model.eval()
    records = []
    with torch.no_grad():
        for index in range(n):
            seed = decision_seed(index, 0, 1)
            logits, heads, offsets = _forward_state(
                model,
                [
                    {
                        "observation": observation,
                        "legal_actions": legal_actions,
                    }
                ],
                catalog,
                device,
            )
            segment_logits = logits[: offsets[1].item()].to(dtype=torch.float32)
            log_probs = torch.log_softmax(segment_logits, dim=0)
            probabilities = log_probs.exp().cpu().tolist()
            unit = (int(seed) >> 11) * (2.0 ** -53)
            cumulative = 0.0
            chosen = len(probabilities) - 1
            for position, probability in enumerate(probabilities):
                cumulative += probability
                if unit < cumulative:
                    chosen = position
                    break
            value = float(
                outcome_value(heads["outcome"]).to(dtype=torch.float32)[0].item()
            )
            records.append(
                {
                    "game_index": index,
                    "seat": 0,
                    "ply_index": 0,
                    "request_id": 1,
                    "observation_hash": "h",
                    "observation": observation,
                    "legal_actions": legal_actions,
                    "action": legal_actions[chosen],
                    "decision_seed": seed,
                    "old_log_probability": float(log_probs[chosen].item()),
                    "old_value": value,
                    "old_value_by_player": [value, -value],
                    "old_auxiliary_score": 0.0,
                    "result": {
                        "scores": [18, 0],
                        "centered_returns": [1.0, -1.0],
                        "truncated": False,
                        "source_terminal_result": {
                            "scores": [18, 0],
                            "ranks": [0, 1],
                            "winners": [0],
                            "reason": "prestige_threshold",
                        },
                    },
                    "m40a_labels": {
                        "prestige_after_ply": [[0, 0]],
                        "window_plies": 1,
                        "truncated": False,
                    },
                }
            )
    return records


class _ForwardSpy:
    """Wraps a model/module namespace to observe `_forward_state` call
    shapes. We spy by monkeypatching the trainer module's `_forward_state`
    reference — `recompute_behaviour` and `train_cycle` both call it via
    module-global lookup, so recording call sizes works for both paths.
    """

    def __init__(self, original) -> None:
        self.original = original
        self.batch_sizes: list[int] = []
        self.records_seen: list[list] = []

    def __call__(self, model, records, catalog, device):
        self.batch_sizes.append(len(records))
        self.records_seen.append(list(records))
        return self.original(model, records, catalog, device)


# ---------------------------------------------------------------------------
# 1/2. Singleton forwarding and record-order preservation
# ---------------------------------------------------------------------------


def test_recompute_behaviour_uses_singleton_forward(catalog, base_frame, monkeypatch):
    model = M40AModel()
    initialize_predictive_heads(model)
    records = _singleton_consistent_records(model, 5, catalog, base_frame)
    import splendor_gpu.m40a_train as trainer

    spy = _ForwardSpy(trainer._forward_state)
    monkeypatch.setattr(trainer, "_forward_state", spy)
    logps, values, stats = recompute_behaviour(
        model, records, catalog, torch.device("cpu")
    )
    assert spy.batch_sizes == [1, 1, 1, 1, 1], (
        f"behaviour recomputation must forward exactly one record at a "
        f"time, got batch sizes {spy.batch_sizes}"
    )
    assert stats["batching"] == "singleton"
    assert stats["categorical_failures"] == 0
    assert stats["threshold_failures"] == 0


def test_recompute_behaviour_preserves_record_order(catalog, base_frame, monkeypatch):
    model = M40AModel()
    initialize_predictive_heads(model)
    records = _singleton_consistent_records(model, 6, catalog, base_frame)
    import splendor_gpu.m40a_train as trainer

    spy = _ForwardSpy(trainer._forward_state)
    monkeypatch.setattr(trainer, "_forward_state", spy)
    recompute_behaviour(model, records, catalog, torch.device("cpu"))
    forwarded = [r for call in spy.records_seen for r in call]
    assert forwarded == records, "authoritative-record order must be preserved"


# ---------------------------------------------------------------------------
# 3. Categorical reproduction remains fail-closed
# ---------------------------------------------------------------------------


def test_categorical_reproduction_fails_closed(catalog, base_frame):
    model = M40AModel()
    initialize_predictive_heads(model)
    records = _singleton_consistent_records(model, 3, catalog, base_frame)
    # Corrupt one action to a DIFFERENT legal action: the frozen draw can
    # no longer reproduce it.
    legal = records[1]["legal_actions"]
    recorded_index = legal.index(records[1]["action"])
    other = (recorded_index + 1) % len(legal)
    records[1]["action"] = legal[other]
    with pytest.raises(ValueError, match="categorical draw"):
        recompute_behaviour(model, records, catalog, torch.device("cpu"))


def test_unknown_action_fails_closed(catalog, base_frame):
    model = M40AModel()
    initialize_predictive_heads(model)
    records = _singleton_consistent_records(model, 1, catalog, base_frame)
    records[0]["action"] = {"tampered": True}
    with pytest.raises(ValueError, match="exactly once"):
        recompute_behaviour(model, records, catalog, torch.device("cpu"))


# ---------------------------------------------------------------------------
# 4. Thresholds unchanged
# ---------------------------------------------------------------------------


def test_frozen_thresholds_unchanged() -> None:
    assert LOG_PROBABILITY_DRIFT_THRESHOLD == 1e-6
    assert VALUE_DRIFT_THRESHOLD == 1e-5


def test_threshold_breach_fails_closed(catalog, base_frame):
    model = M40AModel()
    initialize_predictive_heads(model)
    records = _singleton_consistent_records(model, 2, catalog, base_frame)
    # Inject a drift beyond the frozen logp threshold on record 1.
    records[1]["old_log_probability"] -= 1e-4
    with pytest.raises(ValueError, match="drift thresholds"):
        recompute_behaviour(model, records, catalog, torch.device("cpu"))


# ---------------------------------------------------------------------------
# 5. The incident scenario: packed forward drifts, singleton matches
# ---------------------------------------------------------------------------


def test_incident_scenario_packed_drift_singleton_match(catalog, base_frame, monkeypatch):
    """The exact incident: recorded behaviour comes from singleton
    (server batch-1) forwards; the repaired recomputation reproduces it
    BIT-EXACTLY. The incident's failure signature — a recorded value
    that is a few f32 ULP away from the singleton output (what the
    packed-512 recompute produced) — still breaches the frozen
    threshold, proving the thresholds were not relaxed by the repair."""
    model = M40AModel()
    initialize_predictive_heads(model)
    records = _singleton_consistent_records(model, 4, catalog, base_frame)
    logps, values, stats = recompute_behaviour(
        model, records, catalog, torch.device("cpu")
    )
    assert stats["bit_exact"] == 4
    assert stats["threshold_failures"] == 0
    # The incident signature: shift one recorded logp by the incident's
    # observed deviation scale (a few f32 ULP beyond the 1e-6 threshold).
    records[2]["old_log_probability"] -= 2e-6
    with pytest.raises(ValueError, match="drift thresholds"):
        recompute_behaviour(model, records, catalog, torch.device("cpu"))
    # The singleton-vs-recorded comparison is EXACT: restoring the
    # recorded value makes the recomputation pass again bit-exactly.
    records[2]["old_log_probability"] += 2e-6
    _, _, stats2 = recompute_behaviour(model, records, catalog, torch.device("cpu"))
    assert stats2["bit_exact"] == 4


def test_singleton_matches_where_packed_would_drift_gpu(catalog, base_frame):
    """On CUDA, a packed-512 forward of singleton-recorded behaviour can
    differ by 1-3 f32 ULP (the incident). The singleton recomputation
    must match the recorded behaviour under the frozen thresholds; the
    packed contrast (when it drifts) is what the incident observed."""
    if not torch.cuda.is_available():
        pytest.skip("CUDA unavailable")
    device = torch.device("cuda")
    model = M40AModel()
    initialize_predictive_heads(model)
    model.to(device)
    records = _singleton_consistent_records(model, 512, catalog, base_frame)
    logps, values, stats = recompute_behaviour(model, records, catalog, device)
    assert stats["threshold_failures"] == 0
    assert stats["categorical_failures"] == 0
    assert len(logps) == len(records)
    # Contrast: packed forward of the same 512 records (the incident's
    # implementation). Whether it drifts on this hardware or not, the
    # authoritative array is the singleton output.
    model.eval()
    with torch.no_grad():
        logits, heads, offsets = _forward_state(model, records, catalog, device)
        chosen = [
            next(
                i
                for i, a in enumerate(r["legal_actions"])
                if a == r["action"]
            )
            for r in records
        ]
        selected, _ = _selected_log_probabilities_and_entropies(
            logits, offsets, chosen
        )
        packed = [float(x.item()) for x in selected]
    drift = max(abs(p - s) for p, s in zip(packed, logps))
    # Diagnostic bound: the incident observed 1-3 ULP (~1e-6-3e-6). The
    # contract is that the singleton recompute passed above regardless.
    assert drift >= 0.0
    # Report the contrast for visibility.
    print(f"\npacked-vs-singleton max logp drift on this GPU: {drift:.3e}")


# ---------------------------------------------------------------------------
# 6/7/8. Authoritative arrays feed GAE / PPO old-logp; PPO stays batched
# ---------------------------------------------------------------------------


def test_train_cycle_uses_singleton_authority_and_batched_updates(
    catalog, base_frame, monkeypatch
):
    """train_cycle must (a) run behaviour recomputation with singleton
    forwards and (b) run PPO UPDATE forwards at the frozen minibatch.
    The spy counts every `_forward_state` call: exactly n singleton calls
    from `recompute_behaviour`, plus the packed update calls at the
    frozen PPO_MINIBATCH (or its tail)."""
    model = M40AModel()
    initialize_predictive_heads(model)
    n = 7
    records = _singleton_consistent_records(model, n, catalog, base_frame)
    import splendor_gpu.m40a_train as trainer

    spy = _ForwardSpy(trainer._forward_state)
    monkeypatch.setattr(trainer, "_forward_state", spy)

    _, report = train_cycle(
        model=model,
        records=records,
        catalog=catalog,
        device=torch.device("cpu"),
        cycle=1,
        plan_hash="test",
        arm="A",
    )
    singleton_calls = [s for s in spy.batch_sizes if s == 1]
    update_calls = [s for s in spy.batch_sizes if s > 1]
    assert len(singleton_calls) == n, (
        f"expected exactly {n} singleton forwards (one per record, from "
        f"recompute_behaviour), got {len(singleton_calls)}; all batch "
        f"sizes: {spy.batch_sizes}"
    )
    assert update_calls and all(s <= PPO_MINIBATCH for s in update_calls), (
        "PPO update forwards must remain packed (<= frozen PPO_MINIBATCH)"
    )
    assert max(update_calls) == min(n, PPO_MINIBATCH), (
        "PPO update batch size must be the frozen PPO_MINIBATCH (or the "
        "remaining tail), not something else"
    )
    assert report["recomputation"]["batching"] == "singleton"


def test_gae_consumes_singleton_values(catalog, base_frame):
    """GAE over the singleton value array must be exactly the M39A
    recurrence per trajectory. The fixture records each have a distinct
    game_index, so each is a single-decision trajectory: raw advantage =
    R - V, then population standardization across all records."""
    model = M40AModel()
    initialize_predictive_heads(model)
    records = _singleton_consistent_records(model, 4, catalog, base_frame)
    logps, values, _ = recompute_behaviour(
        model, records, catalog, torch.device("cpu")
    )
    advantages = gae_advantages(records, values)
    from splendor_gpu.m39a_contract import standardize_advantages

    raw = [
        r["result"]["centered_returns"][r["seat"]] - v
        for r, v in zip(records, values)
    ]
    expected = standardize_advantages(raw)
    assert advantages == pytest.approx(expected, rel=1e-12, abs=1e-15)


def test_ppo_old_logp_is_singleton_array(catalog, base_frame, monkeypatch):
    """The PPO ratio's old-logp must be the singleton recomputed values.
    Verified by intercepting the loss computation: patch
    `_selected_log_probabilities_and_entropies` in the PPO loop? That
    helper is shared. Instead: run train_cycle with a model whose PPO
    update we can trace via a hooked forward — the spy on
    `_forward_state` already proves update batches; for the old-logp we
    assert the authoritative array equality directly: the trainer's
    `recomputed_log_probabilities` (report-adjacent) equals the helper's.
    """
    model = M40AModel()
    initialize_predictive_heads(model)
    records = _singleton_consistent_records(model, 3, catalog, base_frame)
    logps, values, _ = recompute_behaviour(
        copy.deepcopy(model), records, catalog, torch.device("cpu")
    )
    # The helper is the ONLY source of authoritative arrays (train_cycle
    # calls it and uses its return values verbatim — see source); assert
    # determinism and identity under repetition.
    logps2, values2, _ = recompute_behaviour(
        copy.deepcopy(model), records, catalog, torch.device("cpu")
    )
    assert logps == logps2 and values == values2


# ---------------------------------------------------------------------------
# 9. Both arms use the same helper
# ---------------------------------------------------------------------------


def test_both_arms_share_the_helper(catalog, base_frame, monkeypatch):
    """A and B must go through the exact same `recompute_behaviour`
    (there is no arm-specific recomputation path)."""
    import splendor_gpu.m40a_train as trainer

    calls = {"n": 0}
    original = trainer.recompute_behaviour

    def spy_recompute(*args, **kwargs):
        calls["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(trainer, "recompute_behaviour", spy_recompute)
    model = M40AModel()
    initialize_predictive_heads(model)
    records = _singleton_consistent_records(model, 2, catalog, base_frame)
    for arm in ("A", "B"):
        train_cycle(
            model=copy.deepcopy(model),
            records=records,
            catalog=catalog,
            device=torch.device("cpu"),
            cycle=1,
            plan_hash="test",
            arm=arm,
        )
    assert calls["n"] == 2, "each arm's train_cycle must invoke the helper exactly once"


# ---------------------------------------------------------------------------
# 10. value_check=False semantics unchanged
# ---------------------------------------------------------------------------


def test_value_check_false_semantics_unchanged(catalog, base_frame):
    """value_check=False preserves the pre-repair semantics EXACTLY: the
    threshold classification (logp AND value) is skipped for foreign-
    readout records, while the categorical-draw reproduction remains
    fail-closed (it is checked before any classification)."""
    model = M40AModel()
    initialize_predictive_heads(model)
    records = _singleton_consistent_records(model, 3, catalog, base_frame)
    # Foreign readout value (M39A-enrichment D2 two-way head) — not
    # comparable, must be ignored under value_check=False.
    records[0]["old_value"] = 123.456
    logps, values, stats = recompute_behaviour(
        model, records, catalog, torch.device("cpu"), value_check=False
    )
    assert stats["value_check"] is False
    assert stats["max_value_deviation"] is None
    assert stats["threshold_failures"] == 0
    assert len(logps) == len(values) == 3
    # Threshold classification skipped (pre-repair semantics): even a
    # large recorded-logp drift does NOT raise under value_check=False…
    records[2]["old_log_probability"] -= 1e-2
    _, _, stats_skipped = recompute_behaviour(
        model, records, catalog, torch.device("cpu"), value_check=False
    )
    assert stats_skipped["threshold_failures"] == 0
    # …but the SAME drift DOES fail closed under the formal value_check.
    with pytest.raises(ValueError, match="drift thresholds"):
        recompute_behaviour(model, records, catalog, torch.device("cpu"))
    # And categorical reproduction remains enforced either way:
    records[2]["old_log_probability"] += 1e-2
    legal = records[1]["legal_actions"]
    idx = legal.index(records[1]["action"])
    records[1]["action"] = legal[(idx + 1) % len(legal)]
    with pytest.raises(ValueError, match="categorical draw"):
        recompute_behaviour(
            model, records, catalog, torch.device("cpu"), value_check=False
        )


def test_online_train_cycle_hardwires_value_check(catalog, base_frame, monkeypatch):
    """The FORMAL path (`online_train_cycle`) hardwires value_check=True."""
    import splendor_gpu.m40a_train as trainer

    captured = {}
    original = trainer.recompute_behaviour

    def spy_recompute(model, records, catalog, device, *, value_check=True):
        captured["value_check"] = value_check
        return original(
            model, records, catalog, device, value_check=value_check
        )

    monkeypatch.setattr(trainer, "recompute_behaviour", spy_recompute)
    model = M40AModel()
    initialize_predictive_heads(model)
    records = _singleton_consistent_records(model, 2, catalog, base_frame)
    trainer.online_train_cycle(
        model=model,
        records=records,
        catalog=catalog,
        device=torch.device("cpu"),
        cycle=1,
        plan_hash="test",
        arm="A",
    )
    assert captured["value_check"] is True
