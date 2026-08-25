"""Exact post-action state delta encoding matching Splendor engine rules."""
import torch
from typing import Any
from splendor_gpu.encoding import GEMS, COLORS, TIERS

def encode_action_delta_v2(observation: dict[str, Any], action: dict[str, Any], catalog: dict[str, Any]) -> list[float]:
    """Compute exact post-action state delta and post-action player state matching engine transition."""
    public = observation["public"]
    viewer = int(observation["viewer"])
    player = public["players"][viewer]
    tokens = {k: int(player["tokens"][k]) for k in GEMS}
    bonuses = list(player["bonuses"])
    prestige = int(player["prestige"])

    delta_vp = 0.0
    delta_bonuses = [0.0] * 5
    delta_tokens = [0.0] * 6
    card_cost = [0.0] * 5
    card_prestige = 0.0
    gold_spent = 0.0
    noble_delta = 0.0

    kind = action.get("type")
    if kind == "take_tokens":
        take = action.get("take", {})
        ret = action.get("return", {})
        for i, g in enumerate(GEMS):
            delta_tokens[i] = (take.get(g, 0) - ret.get(g, 0)) / 10.0

    elif kind in ("buy_market", "buy_reserved"):
        card = None
        if kind == "buy_market":
            tier = TIERS.index(action["tier"])
            slot = int(action["slot"])
            card_id = public["market"][tier][slot]
            if card_id is not None:
                card = catalog["cards"].get(int(card_id))
        else:
            slot = int(action["slot"])
            reserved = observation["private"]["reserved"]
            if slot < len(reserved):
                card_id = int(reserved[slot]["card"])
                card = catalog["cards"].get(card_id)

        if card is not None:
            card_prestige = card["prestige"] / 5.0
            delta_vp = card["prestige"] / 5.0
            color_idx = COLORS.index(str(card["bonus"]).lower())
            delta_bonuses[color_idx] = 1.0
            for i, c in enumerate(card["cost"]):
                card_cost[i] = c / 7.0

            total_gold_paid = 0
            for i, c in enumerate(COLORS):
                needed = max(0, card["cost"][i] - bonuses[i])
                paid = min(tokens[c], needed)
                deficit = needed - paid
                total_gold_paid += deficit
                delta_tokens[i] = -paid / 10.0
            delta_tokens[5] = -total_gold_paid / 10.0
            gold_spent = total_gold_paid / 5.0

            # Noble visits:
            # Check newly qualifying nobles.
            # If exactly 1 noble qualifies, the engine immediately awards it (+3 VP, noble_delta=1).
            # If multiple nobles qualify (>1), the engine transitions to choose_noble phase, so VP is NOT immediately awarded yet, but noble_delta=1 (noble opportunity unlocked).
            visible_nobles = [catalog["nobles"][int(nid)] for nid in public["nobles"] if int(nid) in catalog["nobles"]]
            new_bonuses = [b + (1 if c == color_idx else 0) for c, b in enumerate(bonuses)]

            qualifying_nobles = []
            for n in visible_nobles:
                # Did not qualify before, but qualifies now
                cur_met = all(bonuses[c] >= n["requirements"][c] for c in range(5))
                new_met = all(new_bonuses[c] >= n["requirements"][c] for c in range(5))
                if not cur_met and new_met:
                    qualifying_nobles.append(n)

            if len(qualifying_nobles) == 1:
                delta_vp += 3.0 / 5.0
                noble_delta = 1.0
            elif len(qualifying_nobles) > 1:
                # Multiple nobles qualify -> phase becomes choose_noble; VP not added yet
                noble_delta = 1.0

    elif kind == "reserve_market":
        tier = TIERS.index(action["tier"])
        slot = int(action["slot"])
        card_id = public["market"][tier][slot]
        if card_id is not None:
            card = catalog["cards"].get(int(card_id))
            if card is not None:
                card_prestige = card["prestige"] / 5.0
                for i, c in enumerate(card["cost"]):
                    card_cost[i] = c / 7.0

        ret = action.get("return", {})
        # Engine rule: player always receives 1 gold if bank has gold > 0, regardless of current token count (even if 10 tokens), and returns excess tokens via action['return']
        gold_taken = 1 if public["bank"].get("gold", 0) > 0 else 0

        for i, g in enumerate(GEMS):
            taken = gold_taken if g == "gold" else 0
            returned = ret.get(g, 0)
            delta_tokens[i] = (taken - returned) / 10.0

    elif kind == "reserve_deck":
        ret = action.get("return", {})
        gold_taken = 1 if public["bank"].get("gold", 0) > 0 else 0

        for i, g in enumerate(GEMS):
            taken = gold_taken if g == "gold" else 0
            returned = ret.get(g, 0)
            delta_tokens[i] = (taken - returned) / 10.0

    elif kind == "choose_noble":
        delta_vp = 3.0 / 5.0
        noble_delta = 1.0

    post_vp = (prestige + delta_vp * 5.0) / 15.0
    dist_15 = max(0.0, 15.0 - (prestige + delta_vp * 5.0)) / 15.0
    post_tokens = (sum(tokens.values()) + sum(delta_tokens) * 10.0) / 10.0

    delta_vec = [
        delta_vp, post_vp, dist_15,
        *delta_bonuses,
        *delta_tokens,
        post_tokens,
        *card_cost,
        card_prestige,
        gold_spent,
        noble_delta,
    ]
    return delta_vec
