"""Strict player-view encoders shared by M17 training and Arena inference."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import torch

ENTITY_SLOTS = 31
ENTITY_FEATURES = 32
GLOBAL_FEATURES = 40
ACTION_FEATURES = 36
MAX_PLAYERS = 4

GEMS = ("white", "blue", "green", "red", "black", "gold")
COLORS = ("white", "blue", "green", "red", "black")
TIERS = ("One", "Two", "Three")


@dataclass(frozen=True)
class EncodedObservation:
    entities: torch.Tensor
    mask: torch.Tensor
    global_features: torch.Tensor


def one_hot(index: int, width: int) -> list[float]:
    if not 0 <= index < width:
        raise ValueError(f"one-hot index {index} outside width {width}")
    return [1.0 if index == i else 0.0 for i in range(width)]


def gems(value: dict[str, Any], scale: float) -> list[float]:
    return [float(value[key]) / scale for key in GEMS]


def _card_entity(card_id: int, catalog: dict[str, Any], role: int, owner: int = 0) -> list[float]:
    card = catalog["cards"].get(card_id)
    if card is None:
        raise ValueError(f"unknown card id {card_id}")
    out = one_hot(0, 4) + one_hot(role, 7) + one_hot(owner, 4)
    out += one_hot(tuple(value.lower() for value in TIERS).index(str(card["tier"]).lower()), 3)
    out += one_hot(COLORS.index(str(card["bonus"]).lower()), 5)
    out += [card["prestige"] / 5.0]
    out += [cost / 7.0 for cost in card["cost"]]
    return (out + [0.0] * ENTITY_FEATURES)[:ENTITY_FEATURES]


def _player_entity(player: dict[str, Any], viewer: int, player_count: int) -> list[float]:
    relative = (int(player["id"]) + player_count - viewer) % player_count
    out = one_hot(1, 4) + one_hot(3, 7) + one_hot(relative, 4)
    out += gems(player["tokens"], 10.0)
    out += [float(x) / 15.0 for x in player["bonuses"]]
    out += [player["prestige"] / 30.0, player["reserved_count"] / 3.0]
    return (out + [0.0] * ENTITY_FEATURES)[:ENTITY_FEATURES]


def _noble_entity(noble_id: int, catalog: dict[str, Any], role: int) -> list[float]:
    noble = catalog["nobles"].get(noble_id)
    if noble is None:
        raise ValueError(f"unknown noble id {noble_id}")
    out = one_hot(2, 4) + one_hot(role, 7) + one_hot(0, 4)
    out += [noble["prestige"] / 3.0]
    out += [x / 4.0 for x in noble["requirements"]]
    return (out + [0.0] * ENTITY_FEATURES)[:ENTITY_FEATURES]


def catalog_from_trace_catalog(cards: list[dict[str, Any]], nobles: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "cards": {int(card["id"]): card for card in cards},
        "nobles": {int(noble["id"]): noble for noble in nobles},
    }


def encode_observation(observation: dict[str, Any], catalog: dict[str, Any]) -> EncodedObservation:
    public = observation["public"]
    viewer = int(observation["viewer"])
    player_count = int(public["player_count"])
    if player_count != 2:
        raise ValueError("M17 v1 is explicitly 1v1; player_count must be 2")
    if viewer not in (0, 1) or len(public["players"]) != 2:
        raise ValueError("invalid 1v1 viewer/player shape")

    rows: list[list[float]] = []
    # Market cards: 12 stable tier/slot entities.
    for tier_index, tier in enumerate(public["market"]):
        if len(tier) != 4:
            raise ValueError("each market tier must contain four slots")
        for card_id in tier:
            if card_id is not None:
                rows.append(_card_entity(int(card_id), catalog, role=tier_index))
            else:
                rows.append([0.0] * ENTITY_FEATURES)

    # Current nobles, players, public reserves, and own private reserves.
    for noble_id in list(public["nobles"])[:5]:
        rows.append(_noble_entity(int(noble_id), catalog, role=4))
    while len(rows) < 17:
        rows.append([0.0] * ENTITY_FEATURES)
    for player in public["players"]:
        rows.append(_player_entity(player, viewer, player_count))
    for player in public["players"]:
        for card_id in list(player["public_reserved"])[:3]:
            rows.append(_card_entity(int(card_id), catalog, role=5, owner=int(player["id"])))
        while len(rows) < 19 + (int(player["id"]) + 1) * 3:
            rows.append([0.0] * ENTITY_FEATURES)
    for reserved in list(observation["private"]["reserved"])[:3]:
        rows.append(_card_entity(int(reserved["card"]), catalog, role=6, owner=viewer))
    while len(rows) < ENTITY_SLOTS:
        rows.append([0.0] * ENTITY_FEATURES)
    if len(rows) != ENTITY_SLOTS:
        raise ValueError(f"entity slot mismatch: {len(rows)}")

    phase = {"main": 0, "choose_noble": 1, "game_over": 2}[public["phase"]]
    relative_current = (int(public["current_player"]) + player_count - viewer) % player_count
    global_features = [1.0] + one_hot(viewer, MAX_PLAYERS) + one_hot(relative_current, MAX_PLAYERS)
    global_features += one_hot(phase, 3) + gems(public["bank"], 7.0)
    global_features += [float(x) / 40.0 for x in public["deck_counts"]]
    global_features += [1.0 if public["end_game_triggered"] else 0.0]
    final_turns = public["turns_remaining_in_final_round"]
    global_features += [1.0 if final_turns is not None else 0.0, 0.0 if final_turns is None else final_turns / 4.0]
    global_features += [public["consecutive_forced_passes"] / 4.0]
    for player in public["players"]:
        global_features += gems(player["tokens"], 10.0)
        global_features += [player["prestige"] / 30.0, player["reserved_count"] / 3.0]
    global_features = (global_features + [0.0] * GLOBAL_FEATURES)[:GLOBAL_FEATURES]

    entity_tensor = torch.tensor(rows, dtype=torch.float32)
    mask = entity_tensor.abs().sum(dim=-1).gt(0)
    return EncodedObservation(entity_tensor, mask, torch.tensor(global_features, dtype=torch.float32))


def encode_action(action: dict[str, Any]) -> torch.Tensor:
    out = [0.0] * ACTION_FEATURES
    kinds = {
        "take_tokens": 0, "buy_market": 1, "buy_reserved": 2,
        "reserve_market": 3, "reserve_deck": 4, "choose_noble": 5, "pass": 6,
    }
    kind = action.get("type")
    if kind not in kinds:
        raise ValueError(f"unknown action type {kind!r}")
    out[kinds[kind]] = 1.0
    if kind == "take_tokens":
        for i, key in enumerate(GEMS): out[7 + i] = action["take"][key] / 3.0
    returned = action.get("return")
    if returned is not None:
        for i, key in enumerate(GEMS): out[13 + i] = returned[key] / 10.0
    if "tier" in action: out[19 + TIERS.index(action["tier"])] = 1.0
    if "slot" in action:
        slot = int(action["slot"])
        if not 0 <= slot < 4: raise ValueError("action slot outside 0..3")
        out[22 + slot] = 1.0
    if "noble" in action:
        noble = int(action["noble"])
        if not 0 <= noble < 10: raise ValueError("noble id outside 0..9")
        out[26 + noble] = 1.0
    return torch.tensor(out, dtype=torch.float32)


def action_key(action: dict[str, Any]) -> str:
    import json
    return json.dumps(action, sort_keys=True, separators=(",", ":"))
