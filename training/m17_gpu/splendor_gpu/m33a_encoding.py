"""M33A Factorized Legal-Action Decomposition Encoders.

Extracts dense structured action-decomposition tensors from legal actions:
1. Action Family Index (0..4): Take (0), Buy (1), Reserve (2), ChooseNoble (3), Pass (4).
2. Take Mode Index (0..3): 1-distinct (0), 2-distinct (1), 3-distinct (2), 2-same (3). None / other -> -1.
3. Selected Colors Presence (5 dims): binary indicator for [white, blue, green, red, black].
4. Returned Colors Count (6 dims): counts for [white, blue, green, red, black, gold].
5. Target Entity Slot (0..30):
   - Market cards: tier 0..2, slot 0..3 -> slot = tier * 4 + slot (0..11)
   - Own private reserved: slot 0..2 -> 28 + slot (28..30)
   - Nobles: noble_id matches obs["public"]["nobles"] index -> 12 + idx (12..16)
   - None / Other -> -1
6. Target Deck Tier (0..2): Tier 1 (0), Tier 2 (1), Tier 3 (2). None / Other -> -1.
"""
from typing import Any
import torch
from splendor_gpu.encoding import GEMS, TIERS

ACTION_FAMILIES = ["take", "buy", "reserve", "choose_noble", "pass"]
TAKE_MODES = ["one_distinct", "two_distinct", "three_distinct", "two_same"]
ALL_GEMS_WITH_GOLD = ["white", "blue", "green", "red", "black", "gold"]

def decompose_legal_action(obs_raw: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    """Decompose a single legal action into structured factor components."""
    atype = action.get("type")
    
    # 1. Action family
    if atype == "take_tokens":
        family_idx = 0
    elif atype in ("buy_market", "buy_reserved"):
        family_idx = 1
    elif atype in ("reserve_market", "reserve_deck"):
        family_idx = 2
    elif atype == "choose_noble":
        family_idx = 3
    elif atype == "pass":
        family_idx = 4
    else:
        raise ValueError(f"Unknown action type: {atype}")

    # 2. Take mode & color selection
    take_mode_idx = -1
    selected_colors = [0.0] * 5
    if atype == "take_tokens":
        take = action.get("take", {})
        counts = [take.get(g, 0) for g in GEMS]
        distinct_count = sum(1 for c in counts if c > 0)
        max_count = max(counts) if counts else 0
        for i, c in enumerate(counts):
            if c > 0:
                selected_colors[i] = 1.0
        
        if max_count == 2:
            take_mode_idx = 3  # two_same
        elif distinct_count == 3:
            take_mode_idx = 2  # three_distinct
        elif distinct_count == 2:
            take_mode_idx = 1  # two_distinct (bank depleted)
        elif distinct_count == 1:
            take_mode_idx = 0  # one_distinct (bank depleted)
        else:
            raise ValueError(f"Invalid take_tokens counts: {counts}")

    # 3. Returned colors (6 dims: 5 standard gems + gold)
    returned_colors = [0.0] * 6
    ret = action.get("return")
    if ret is not None:
        for i, g in enumerate(ALL_GEMS_WITH_GOLD):
            returned_colors[i] = float(ret.get(g, 0))

    # 4. Target entity slot (0..30)
    target_entity_slot = -1
    if atype in ("buy_market", "reserve_market"):
        tier_idx = TIERS.index(action["tier"])
        slot_idx = int(action["slot"])
        target_entity_slot = tier_idx * 4 + slot_idx  # 0..11
    elif atype == "buy_reserved":
        # Own private reserved card slots 0..2 map to entity slots 25..27
        res_slot = int(action["slot"])
        target_entity_slot = 25 + res_slot  # 25..27
    elif atype == "choose_noble":
        noble_id = int(action["noble"])
        public_nobles = obs_raw["public"]["nobles"]
        if noble_id in public_nobles:
            noble_idx = public_nobles.index(noble_id)
            target_entity_slot = 12 + noble_idx  # 12..16
        else:
            raise ValueError(f"Noble id {noble_id} not found in public nobles: {public_nobles}")

    # 5. Target deck tier (0..2 for reserve_deck)
    target_deck_tier = -1
    if atype == "reserve_deck":
        target_deck_tier = TIERS.index(action["tier"])

    return {
        "family_idx": family_idx,
        "take_mode_idx": take_mode_idx,
        "selected_colors": selected_colors,
        "returned_colors": returned_colors,
        "target_entity_slot": target_entity_slot,
        "target_deck_tier": target_deck_tier,
    }
