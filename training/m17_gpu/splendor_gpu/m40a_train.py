"""M40A PPO trainer: the frozen 4-cycle A/B contract.

Both arms run this trainer verbatim. Differences from the M39A trainer
are exactly those the frozen design specifies:

- the value source is `V = p_win − p_loss` from the outcome head;
- Outcome CE (completed only) + value MSE split the 0.500 family;
- VP-distribution CE / normalized VP-difference MSE / timing BCE are
  auxiliary families at 1/12 each (coefficient budget 0.250);
- truncated records are masked from every predictive family and
  supervise value MSE against the frozen cap-return only;
- 4 cycles with the frozen recomputed cosine waypoints.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

import torch
from torch import nn

from .m39a_contract import file_sha256
from .m40a_constants import (
    ADVANTAGE_EPSILON,
    AUX_FAMILY_COEFFICIENT,
    DESIGN_SHA,
    ENTROPY_COEFFICIENT,
    GAE_LAMBDA,
    GRAD_CLIP_NORM,
    LR_WAYPOINTS,
    PPO_CLIP_EPSILON,
    PPO_CYCLES,
    PPO_EPOCHS_PER_CYCLE,
    PPO_MINIBATCH,
    VALUE_COEFFICIENT,
    WEIGHT_DECAY,
)
from .m40a_dataset import (
    _labels_for_batch,
)
from .m40a_model import M40AModel, outcome_value

REPORT_FORMAT = "effective-splendor-m40a-training-report"
REPORT_VERSION = 1


def _forward_state(model: M40AModel, records, catalog, device):
    from .m39a_model import encode_decisions, move_encoded

    observations = [record["observation"] for record in records]
    legal_sets = [record["legal_actions"] for record in records]
    encoded = move_encoded(encode_decisions(observations, legal_sets, catalog), device)
    state = model.state_embedding(
        encoded["entities"], encoded["mask"], encoded["global_features"]
    )
    heads = model.heads(state)
    expanded = torch.repeat_interleave(
        state, encoded["action_offsets"][1:] - encoded["action_offsets"][:-1], dim=0
    )
    action = model.action_encoder(encoded["actions"])
    logits = model.policy(
        torch.cat([expanded, action, expanded * action], dim=-1)
    ).squeeze(-1)
    return logits, heads, encoded["action_offsets"]



def _selected_log_probabilities_and_entropies(
    logits: torch.Tensor,
    offsets: torch.Tensor,
    chosen_indices: list[int],
) -> tuple[torch.Tensor, torch.Tensor]:
    """Per-decision selected log-probability and entropy, segmenting the
    flattened action logits by the packed offsets (M39A semantics)."""
    selected = []
    entropies = []
    boundaries = offsets.detach().cpu().tolist()
    for batch_index, chosen in enumerate(chosen_indices):
        start, end = boundaries[batch_index], boundaries[batch_index + 1]
        log_probs = torch.log_softmax(logits[start:end], dim=0)
        probabilities = log_probs.exp()
        selected.append(log_probs[int(chosen)])
        entropies.append(-(probabilities * log_probs).sum())
    return torch.stack(selected), torch.stack(entropies)


def _selected_log_probabilities_and_entropies(
    logits: torch.Tensor,
    offsets: torch.Tensor,
    chosen_indices: list[int],
) -> tuple[torch.Tensor, torch.Tensor]:
    """Per-decision selected log-probability and entropy, segmenting the
    flattened action logits by the packed offsets (M39A semantics)."""
    selected = []
    entropies = []
    boundaries = offsets.detach().cpu().tolist()
    for batch_index, chosen in enumerate(chosen_indices):
        start, end = boundaries[batch_index], boundaries[batch_index + 1]
        log_probs = torch.log_softmax(logits[start:end], dim=0)
        probabilities = log_probs.exp()
        selected.append(log_probs[int(chosen)])
        entropies.append(-(probabilities * log_probs).sum())
    return torch.stack(selected), torch.stack(entropies)


def _action_index(record: dict[str, Any]) -> int:
    return next(
        index
        for index, action in enumerate(record["legal_actions"])
        if action == record["action"]
    )


def gae_advantages(
    records: list[dict[str, Any]],
    values: list[float],
    *,
    gamma: float = 1.0,
    gae_lambda: float = GAE_LAMBDA,
    epsilon: float = ADVANTAGE_EPSILON,
) -> list[float]:
    """M40A advantages = the accepted M39A GAE, applied per
    (game_index, seat) trajectory, then population-standardized.

    The recurrence is EXACTLY `m39a_contract.gae_for_trajectory`:
    intermediate rewards are zero (`delta = gamma*V_{t+1} - V_t`); the
    LAST learner decision gets `delta = terminal_or_cap_return - V_t`.
    No terminal return is ever injected at an intermediate decision.
    """
    from .m39a_contract import (
        gae_for_trajectory,
        standardize_advantages,
    )

    by_trajectory: dict[tuple[int, int], list[int]] = {}
    for index, record in enumerate(records):
        by_trajectory.setdefault(
            (int(record["game_index"]), int(record["seat"])), []
        ).append(index)
    raw = [0.0] * len(records)
    for trajectory_indices in by_trajectory.values():
        trajectory_values = [values[index] for index in trajectory_indices]
        terminal_return = records[trajectory_indices[-1]]["result"][
            "centered_returns"
        ][int(records[trajectory_indices[-1]]["seat"])]
        trajectory_advantages = gae_for_trajectory(
            trajectory_values, terminal_return, gamma=gamma, gae_lambda=gae_lambda
        )
        for index, advantage in zip(trajectory_indices, trajectory_advantages):
            raw[index] = advantage
    return standardize_advantages(raw, epsilon=epsilon)


def train_cycle(
    *,
    model: M40AModel,
    records: list[dict[str, Any]],
    catalog: dict[str, Any],
    device: torch.device,
    cycle: int,
    plan_hash: str,
    arm: str,
    value_check: bool = True,
    parent_optimizer_state: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """One frozen PPO cycle over the arm's collected batch.

    `value_check=True` (the formal path) validates the recorded
    `old_value`/`old_log_probability` against the checkpoint's forward
    pass under the frozen drift thresholds. It requires records whose
    behaviour values were produced by the M40A readout
    (V = p_win − p_loss). M39A-derived enrichment (whose sidecars carry
    the D2 two-way value head) must pass `value_check=False` — the
    recomputed values remain authoritative for PPO either way."""
    labels = _labels_for_batch(records)

    # --- Behaviour recomputation (join check 6 semantics, M39A style):
    # the server-recorded values are validated against the checkpoint's
    # own forward pass; the RECOMPUTED values are authoritative.
    model.eval()
    with torch.no_grad():
        recomputed_log_probabilities = []
        recomputed_values = []
        max_logp_deviation = 0.0
        max_value_deviation = 0.0
        bit_exact = 0
        benign = 0
        for start in range(0, len(records), PPO_MINIBATCH):
            batch_records = records[start : start + PPO_MINIBATCH]
            logits, heads, offsets = _forward_state(model, batch_records, catalog, device)
            # Behaviour reproduction, M39A fail-closed semantics: the
            # recorded action must occur EXACTLY ONCE in the ordered
            # legal set, and the frozen categorical draw (recomputed
            # decision seed + cumulative walk over the checkpoint's
            # masked softmax) must reproduce it.
            from .m39a_contract import action_index, decision_seed

            chosen = []
            for record in batch_records:
                chosen.append(
                    action_index(record["legal_actions"], record["action"])
                )
            selected, _ = _selected_log_probabilities_and_entropies(
                logits, offsets, chosen
            )
            values = outcome_value(heads["outcome"]).to(dtype=torch.float32)
            boundaries = offsets.detach().cpu().tolist()
            for row, record in enumerate(batch_records):
                # Frozen categorical draw reproduction: re-derive the
                # decision seed and walk the checkpoint's probabilities.
                seed = decision_seed(
                    int(record["game_index"]),
                    int(record["seat"]),
                    int(record["request_id"]),
                )
                start_ply, end_ply = boundaries[row], boundaries[row + 1]
                segment_logits = logits[start_ply:end_ply].to(dtype=torch.float32)
                segment_log_probs = torch.log_softmax(segment_logits, dim=0)
                probabilities = segment_log_probs.exp().cpu().tolist()
                unit = (int(seed) >> 11) * (2.0 ** -53)
                cumulative = 0.0
                reproduced = len(probabilities) - 1
                for index, probability in enumerate(probabilities):
                    cumulative += probability
                    if unit < cumulative:
                        reproduced = index
                        break
                if reproduced != chosen[row]:
                    raise ValueError(
                        f"game {record['game_index']} ply {record['ply_index']}: "
                        f"checkpoint categorical draw selected {reproduced} but the "
                        f"recorded action is at index {chosen[row]}"
                    )
                recomputed_log_probabilities.append(float(selected[row].item()))
                recomputed_values.append(float(values[row].item()))
                logp_deviation = abs(
                    float(selected[row].item()) - float(record["old_log_probability"])
                )
                if value_check:
                    value_deviation = abs(
                        float(values[row].item()) - float(record["old_value"])
                    )
                else:
                    value_deviation = float("nan")  # not comparable (foreign readout)
                max_logp_deviation = max(max_logp_deviation, logp_deviation)
                if value_check:
                    max_value_deviation = max(max_value_deviation, value_deviation)
                if not value_check:
                    continue
                if logp_deviation == 0.0 and value_deviation == 0.0:
                    bit_exact += 1
                elif logp_deviation <= 1e-6 and value_deviation <= 1e-5:
                    benign += 1
                else:
                    raise ValueError(
                        f"behaviour recomputation exceeds frozen drift thresholds: "
                        f"logp={logp_deviation}, value={value_deviation}"
                    )

    advantages = gae_advantages(records, recomputed_values)

    # --- PPO updates.
    learning_rate = LR_WAYPOINTS[cycle - 1]
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=learning_rate,
        betas=(0.9, 0.999),
        eps=1e-8,
        weight_decay=WEIGHT_DECAY,
        amsgrad=False,
        foreach=False,
        fused=False,
        maximize=False,
        capturable=False,
        differentiable=False,
    )
    if parent_optimizer_state is not None:
        # M39A progression semantics: restore the parent cycle's AdamW
        # state and overwrite ONLY the learning rate with this cycle's
        # frozen waypoint. Cycle 1 (parent None) starts fresh — for BOTH
        # arms: B's offline-pretrain AdamW state is never carried in.
        optimizer.load_state_dict(parent_optimizer_state)
        for group in optimizer.param_groups:
            group["lr"] = learning_rate

    model.train()
    history: list[dict[str, float]] = []
    started = time.perf_counter()
    count = len(records)
    for epoch in range(1, PPO_EPOCHS_PER_CYCLE + 1):
        from .m39a_contract import shuffled_indices

        order = shuffled_indices(count, cycle, epoch)
        totals = {
            "loss": 0.0,
            "policy": 0.0,
            "entropy": 0.0,
            "outcome_ce": 0.0,
            "value_mse": 0.0,
            "vp_dist_ce": 0.0,
            "vp_diff_mse": 0.0,
            "timing_bce": 0.0,
        }
        batches = 0
        for start in range(0, count, PPO_MINIBATCH):
            indices = order[start : start + PPO_MINIBATCH]
            batch_records = [records[i] for i in indices]
            batch_labels = {
                family: [labels[family][i] for i in indices] for family in labels
            }
            batch_advantages = torch.tensor(
                [advantages[i] for i in indices],
                dtype=torch.float32,
                device=device,
            )
            batch_old_logp = torch.tensor(
                [recomputed_log_probabilities[i] for i in indices],
                dtype=torch.float32,
                device=device,
            )

            logits, heads, offsets = _forward_state(
                model, batch_records, catalog, device
            )
            from .m39a_contract import action_index as _strict_action_index

            chosen = [
                _strict_action_index(record["legal_actions"], record["action"])
                for record in batch_records
            ]
            selected_logp, entropies = _selected_log_probabilities_and_entropies(
                logits, offsets, chosen
            )

            # --- Policy (clipped surrogate) ---
            ratio = (selected_logp - batch_old_logp).exp()
            surrogate1 = ratio * batch_advantages
            surrogate2 = (
                torch.clamp(ratio, 1.0 - PPO_CLIP_EPSILON, 1.0 + PPO_CLIP_EPSILON)
                * batch_advantages
            )
            policy_loss = -torch.minimum(surrogate1, surrogate2).mean()

            # --- Entropy bonus ---
            entropy = entropies.mean()

            # --- Outcome CE + value MSE (completed split by truncation) ---
            value_predictions = outcome_value(heads["outcome"]).to(dtype=torch.float32)
            value_targets = torch.tensor(
                batch_labels["value"], dtype=torch.float32, device=device
            )
            value_mse = nn.functional.mse_loss(value_predictions, value_targets)

            completed_rows = [
                row
                for row, label in enumerate(batch_labels["outcome"])
                if label is not None
            ]
            outcome_ce = torch.zeros((), device=device)
            if completed_rows:
                outcome_targets = torch.tensor(
                    [batch_labels["outcome"][row] for row in completed_rows],
                    dtype=torch.long,
                    device=device,
                )
                outcome_ce = nn.functional.cross_entropy(
                    heads["outcome"][completed_rows].to(dtype=torch.float32),
                    outcome_targets,
                )

            # --- Predictive auxiliary families (completed only) ---
            vp_rows = [
                row for row, label in enumerate(batch_labels["vp_self"]) if label is not None
            ]
            vp_ce = torch.zeros((), device=device)
            if vp_rows:
                vp_ce = 0.5 * (
                    nn.functional.cross_entropy(
                        heads["final_vp_self"][vp_rows].to(dtype=torch.float32),
                        torch.tensor(
                            [batch_labels["vp_self"][row] for row in vp_rows],
                            dtype=torch.long,
                            device=device,
                        ),
                    )
                    + nn.functional.cross_entropy(
                        heads["final_vp_opp"][vp_rows].to(dtype=torch.float32),
                        torch.tensor(
                            [batch_labels["vp_opp"][row] for row in vp_rows],
                            dtype=torch.long,
                            device=device,
                        ),
                    )
                )

            diff_rows = [
                row for row, label in enumerate(batch_labels["vp_diff"]) if label is not None
            ]
            diff_mse = torch.zeros((), device=device)
            if diff_rows:
                diff_mse = nn.functional.mse_loss(
                    heads["vp_difference"][diff_rows].to(dtype=torch.float32),
                    torch.tensor(
                        [batch_labels["vp_diff"][row] for row in diff_rows],
                        dtype=torch.float32,
                        device=device,
                    ),
                )

            timing_rows = [
                row
                for row, label in enumerate(batch_labels["timing"])
                if label is not None
            ]
            timing_bce = torch.zeros((), device=device)
            if timing_rows:
                timing_bce = nn.functional.binary_cross_entropy_with_logits(
                    heads["timing"][timing_rows].to(dtype=torch.float32),
                    torch.tensor(
                        [batch_labels["timing"][row] for row in timing_rows],
                        dtype=torch.float32,
                        device=device,
                    ),
                )

            loss = (
                policy_loss
                - ENTROPY_COEFFICIENT * entropy
                + VALUE_COEFFICIENT * outcome_ce
                + VALUE_COEFFICIENT * value_mse
                + AUX_FAMILY_COEFFICIENT * vp_ce
                + AUX_FAMILY_COEFFICIENT * diff_mse
                + AUX_FAMILY_COEFFICIENT * timing_bce
            )
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), GRAD_CLIP_NORM)
            optimizer.step()

            totals["loss"] += float(loss.item())
            totals["policy"] += float(policy_loss.item())
            totals["entropy"] += float(entropy.item())
            totals["outcome_ce"] += float(outcome_ce.item())
            totals["value_mse"] += float(value_mse.item())
            totals["vp_dist_ce"] += float(vp_ce.item())
            totals["vp_diff_mse"] += float(diff_mse.item())
            totals["timing_bce"] += float(timing_bce.item())
            batches += 1

        history.append({key: value / batches for key, value in totals.items()})

    report = {
        "format": REPORT_FORMAT,
        "version": REPORT_VERSION,
        "design_sha": DESIGN_SHA,
        "arm": arm,
        "cycle": cycle,
        "plan_hash": plan_hash,
        "records": len(records),
        "recomputation": {
            "bit_exact": bit_exact,
            "benign_runtime_drift": benign,
            "max_log_probability_deviation": max_logp_deviation,
            "max_value_deviation": max_value_deviation if value_check else None,
            "value_check": value_check,
        },
        "learning_rate": learning_rate,
        "elapsed_seconds": time.perf_counter() - started,
        "history": history,
        "optimizer_state_dict": optimizer.state_dict(),
    }
    return {}, report

def online_train_cycle(
    *,
    model: M40AModel,
    records: list[dict[str, Any]],
    catalog: dict[str, Any],
    device: torch.device,
    cycle: int,
    plan_hash: str,
    arm: str,
    parent_optimizer_state: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The FORMAL M40A online PPO cycle.

    `value_check` is hardwired True — the formal online runner cannot
    bypass behaviour-reproduction checks. (The `value_check=False`
    escape exists solely for offline M39A-source enrichment smoke, which
    carries the D2 two-way value readout in its sidecars.)
    """
    return train_cycle(
        model=model,
        records=records,
        catalog=catalog,
        device=device,
        cycle=cycle,
        plan_hash=plan_hash,
        arm=arm,
        value_check=True,
        parent_optimizer_state=parent_optimizer_state,
    )
