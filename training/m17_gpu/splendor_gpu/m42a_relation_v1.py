"""M42A: Rule-exact player-view visible action-entity relation tensor encoder.

Computes R(o, a, e_i) in R^28 for all 31 entity slots strictly from
(Observation, Action, Catalog). Zero access to FullState, hidden decks,
replacement cards, or opponent private reserves.
"""

from __future__ import annotations

from typing import Any
import torch

from .encoding import COLORS, ENTITY_SLOTS, GEMS, TIERS

RELATION_DIM = 28


def compute_action_visible_relation_tensor(
    observation: dict[str, Any],
    action: dict[str, Any],
    catalog: dict[str, Any],
) -> torch.Tensor:
    """Compute R(o, a, e_i) of shape (31, 28) for one legal action."""
    public = observation["public"]
    viewer = int(observation["viewer"])
    player = public["players"][viewer]

    tokens_before = {k: int(player["tokens"][k]) for k in GEMS}
    bonuses_before = list(player["bonuses"])
    gold_before = tokens_before["gold"]

    # 1. Compute post-action tokens and bonuses strictly from player-view consequence.
    kind = action.get("type")
    tokens_after = dict(tokens_before)
    bonuses_after = list(bonuses_before)

    target_entity_slot: int | None = None
    action_buys = False
    action_reserves = False
    action_claims = False

    if kind == "take_tokens":
        take = action.get("take", {})
        ret = action.get("return", {})
        for g in GEMS:
            tokens_after[g] = tokens_before[g] + take.get(g, 0) - ret.get(g, 0)

    elif kind in ("buy_market", "buy_reserved"):
        action_buys = True
        card = None
        if kind == "buy_market":
            tier_idx = TIERS.index(action["tier"])
            slot_idx = int(action["slot"])
            target_entity_slot = tier_idx * 4 + slot_idx
            card_id = public["market"][tier_idx][slot_idx]
            if card_id is not None:
                card = catalog["cards"].get(int(card_id))
        else:
            slot_idx = int(action["slot"])
            target_entity_slot = 25 + slot_idx
            reserved = observation["private"]["reserved"]
            if slot_idx < len(reserved):
                card_id = int(reserved[slot_idx]["card"])
                card = catalog["cards"].get(card_id)

        if card is not None:
            gold_spent = 0
            for i, c in enumerate(COLORS):
                needed = max(0, card["cost"][i] - bonuses_before[i])
                paid = min(tokens_before[c], needed)
                deficit = needed - paid
                gold_spent += deficit
                tokens_after[c] = tokens_before[c] - paid
            tokens_after["gold"] = tokens_before["gold"] - gold_spent
            bonus_color = COLORS.index(str(card["bonus"]).lower())
            bonuses_after[bonus_color] += 1

    elif kind in ("reserve_market", "reserve_deck"):
        action_reserves = (kind == "reserve_market")
        if kind == "reserve_market":
            tier_idx = TIERS.index(action["tier"])
            slot_idx = int(action["slot"])
            target_entity_slot = tier_idx * 4 + slot_idx

        gold_available = 1 if public["bank"].get("gold", 0) > 0 else 0
        ret = action.get("return", {})
        for g in GEMS:
            tokens_after[g] = tokens_before[g] - ret.get(g, 0)
        tokens_after["gold"] = tokens_before["gold"] + gold_available - ret.get("gold", 0)

    elif kind == "choose_noble":
        action_claims = True
        noble_id = int(action["noble"])
        for i, nid in enumerate(list(public["nobles"])[:5]):
            if int(nid) == noble_id:
                target_entity_slot = 12 + i
                break

    gold_after = tokens_after["gold"]

    # 2. Build 31 x 28 relation tensor
    rows = [[0.0] * RELATION_DIM for _ in range(ENTITY_SLOTS)]

    def fill_card_row(slot_idx: int, card_id: int, can_buy: bool) -> None:
        card = catalog["cards"].get(card_id)
        if card is None:
            return
        r = rows[slot_idx]
        r[0] = 1.0  # is_card

        is_target = (target_entity_slot == slot_idx)
        if is_target:
            r[2] = 1.0  # action_targets_entity
            if action_buys:
                r[3] = 1.0  # action_buys_entity
                r[6] = 1.0  # entity_consumed_or_relocated
            elif action_reserves:
                r[4] = 1.0  # action_reserves_entity
                r[6] = 1.0  # entity_consumed_or_relocated

        # Deficits before
        raw_d_before = [
            max(0, card["cost"][c] - bonuses_before[c] - tokens_before[COLORS[c]])
            for c in range(5)
        ]
        sum_d_before = sum(raw_d_before)
        for c in range(5):
            r[7 + c] = raw_d_before[c] / 7.0
        r[22] = sum_d_before / 35.0
        feasible_before = can_buy and (sum_d_before <= gold_before)
        r[25] = 1.0 if feasible_before else 0.0

        # Deficits after
        if is_target and action_buys:
            # Consumed target card has 0 deficit after
            r[23] = 0.0
            r[26] = 1.0  # feasible_after = 1.0
        else:
            raw_d_after = [
                max(0, card["cost"][c] - bonuses_after[c] - tokens_after[COLORS[c]])
                for c in range(5)
            ]
            sum_d_after = sum(raw_d_after)
            for c in range(5):
                r[12 + c] = raw_d_after[c] / 7.0
            r[23] = sum_d_after / 35.0
            feasible_after = can_buy and (sum_d_after <= gold_after)
            r[26] = 1.0 if feasible_after else 0.0

        # Reductions
        for c in range(5):
            r[17 + c] = r[7 + c] - r[12 + c]
        r[24] = r[22] - r[23]
        r[27] = 1.0 if (not feasible_before and r[26] == 1.0) else 0.0

    def fill_noble_row(slot_idx: int, noble_id: int) -> None:
        noble = catalog["nobles"].get(noble_id)
        if noble is None:
            return
        r = rows[slot_idx]
        r[1] = 1.0  # is_noble

        is_target = (target_entity_slot == slot_idx)
        if is_target:
            r[2] = 1.0  # action_targets_entity
            if action_claims:
                r[5] = 1.0  # action_claims_entity
                r[6] = 1.0  # entity_consumed_or_relocated

        raw_d_before = [
            max(0, noble["requirements"][c] - bonuses_before[c])
            for c in range(5)
        ]
        sum_d_before = sum(raw_d_before)
        for c in range(5):
            r[7 + c] = raw_d_before[c] / 7.0
        r[22] = sum_d_before / 35.0
        feasible_before = (sum_d_before == 0)
        r[25] = 1.0 if feasible_before else 0.0

        if is_target and action_claims:
            r[23] = 0.0
            r[26] = 1.0
        else:
            raw_d_after = [
                max(0, noble["requirements"][c] - bonuses_after[c])
                for c in range(5)
            ]
            sum_d_after = sum(raw_d_after)
            for c in range(5):
                r[12 + c] = raw_d_after[c] / 7.0
            r[23] = sum_d_after / 35.0
            feasible_after = (sum_d_after == 0)
            r[26] = 1.0 if feasible_after else 0.0

        for c in range(5):
            r[17 + c] = r[7 + c] - r[12 + c]
        r[24] = r[22] - r[23]
        r[27] = 1.0 if (not feasible_before and r[26] == 1.0) else 0.0

    # 1. Market cards: slots 0..11
    for tier_idx, tier in enumerate(public["market"]):
        for slot_idx, card_id in enumerate(tier):
            if card_id is not None:
                fill_card_row(tier_idx * 4 + slot_idx, int(card_id), can_buy=True)

    # 2. Nobles: slots 12..16
    for i, noble_id in enumerate(list(public["nobles"])[:5]):
        if noble_id is not None:
            fill_noble_row(12 + i, int(noble_id))

    # 3. Players: slots 17..18 (all zeros, already initialized to 0.0)

    # 4. Public reserves: slots 19..21 (p0), 22..24 (p1)
    for p_idx, p in enumerate(public["players"]):
        base_slot = 19 + p_idx * 3
        can_buy_reserved = (int(p["id"]) == viewer)
        for i, card_id in enumerate(list(p["public_reserved"])[:3]):
            if card_id is not None:
                fill_card_row(base_slot + i, int(card_id), can_buy=can_buy_reserved)

    # 5. Private reserves: slots 25..27 (own private reserves)
    for i, res in enumerate(list(observation["private"]["reserved"])[:3]):
        card_id = res.get("card")
        if card_id is not None:
            fill_card_row(25 + i, int(card_id), can_buy=True)

    # 6. Padding: slots 28..30 (all zeros)

    return torch.tensor(rows, dtype=torch.float32)


def compute_observation_relation_tensors(
    observation: dict[str, Any],
    legal_actions: list[dict[str, Any]],
    catalog: dict[str, Any],
) -> torch.Tensor:
    """Compute R(o, a, e_i) for all legal actions of an observation.
    
    Returns tensor of shape (len(legal_actions), 31, 28).
    """
    tensors = [
        compute_action_visible_relation_tensor(observation, a, catalog)
        for a in legal_actions
    ]
    return torch.stack(tensors, dim=0)
