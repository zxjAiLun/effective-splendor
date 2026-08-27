"""M32A Real-time Belief Tracker: Reconstructs 212-dim features from live NDJSON events."""

from __future__ import annotations

from typing import Any
import torch

BELIEF_FEATURE_DIM = 212
CARD_COUNT = 90
TIERS = 3
MAX_PLAYERS = 2
MAX_RESERVED_SLOTS = 3


def parse_tier(v: Any) -> int:
    if isinstance(v, int):
        if 0 <= v <= 2:
            return v
        if 1 <= v <= 3:
            return v - 1
    if isinstance(v, str):
        low = v.lower()
        if "1" in low or "one" in low:
            return 0
        if "2" in low or "two" in low:
            return 1
        if "3" in low or "three" in low:
            return 2
    raise ValueError(f"Unrecognized tier: {v}")


class LiveBeliefTracker:
    """Reconstructs player-visible history and projects 212-dim belief features on the fly."""

    def __init__(self, viewer: int, player_count: int = 2) -> None:
        self.viewer = int(viewer)
        self.player_count = int(player_count)
        # slots[player_idx] = list of slot dicts
        self.slots: list[list[dict[str, Any]]] = [[] for _ in range(self.player_count)]

    def reset(self, viewer: int, player_count: int = 2) -> None:
        self.viewer = int(viewer)
        self.player_count = int(player_count)
        self.slots = [[] for _ in range(self.player_count)]

    def handle_event(self, event: dict[str, Any]) -> None:
        etype = event.get("type")
        if etype == "game_started":
            pcount = event.get("player_count", 2)
            self.player_count = int(pcount)
            self.slots = [[] for _ in range(self.player_count)]
        elif etype == "card_reserved":
            player = int(event["player"])
            raw_card = event.get("card")
            card_id = int(raw_card) if raw_card is not None else None
            source_info = event.get("from")
            public_id = bool(event.get("public_identity", False))

            # Determine whether reserved from market or deck
            if isinstance(source_info, dict):
                if "market" in source_info:
                    tier = parse_tier(source_info["market"].get("tier", 0))
                    is_market = True
                elif "deck" in source_info:
                    tier = parse_tier(source_info["deck"].get("tier", 0))
                    is_market = False
                elif "tier" in source_info:
                    tier = parse_tier(source_info["tier"])
                    is_market = (card_id is not None)
                else:
                    is_market = (card_id is not None)
                    tier = 0
            elif isinstance(source_info, str):
                is_market = (source_info == "market")
                tier = 0
            else:
                is_market = (card_id is not None)
                tier = 0

            if is_market:
                if card_id is None:
                    raise ValueError("Market reserve must carry a card ID")
                self.slots[player].append({
                    "kind": "known",
                    "card": card_id,
                    "from_deck": False,
                })
            else:
                # Blind reserve from deck
                if player == self.viewer:
                    if card_id is None:
                        raise ValueError("Viewer blind reserve must carry a card ID")
                    self.slots[player].append({
                        "kind": "known",
                        "card": card_id,
                        "from_deck": True,
                    })
                else:
                    self.slots[player].append({
                        "kind": "hidden",
                        "tier": tier,
                    })

        elif etype == "card_purchased":
            player = int(event["player"])
            source_info = event.get("from")
            if isinstance(source_info, dict) and "reserved" in source_info:
                slot_idx = int(source_info["reserved"]["slot"])
                if 0 <= slot_idx < len(self.slots[player]):
                    self.slots[player].pop(slot_idx)
                else:
                    raise ValueError(f"Reserved purchase slot {slot_idx} out of range for player {player}")

    def project_features(self, observation: dict[str, Any], catalog: dict[str, Any]) -> list[float]:
        """Projects exact 212-dim belief feature vector."""
        features: list[float] = []

        # Card catalog lookup helper
        cards_by_id = catalog["cards"] if isinstance(catalog["cards"], dict) else {int(c["id"]): c for c in catalog["cards"]}

        # 1. Compute Known Cards
        known_card_set: set[int] = set()
        public = observation.get("public", observation)
        market = public.get("market", [])
        for tier_row in market:
            for card in tier_row:
                if card is not None:
                    known_card_set.add(int(card))

        players = public.get("players", [])
        for p in players:
            for card in p.get("purchased", []):
                known_card_set.add(int(card))

        for p_slots in self.slots:
            for s in p_slots:
                if s["kind"] == "known":
                    known_card_set.add(int(s["card"]))

        # Part A: unseen_card_mask (90 dims, card 0..89)
        unseen_mask = [
            1.0 if cid not in known_card_set else 0.0
            for cid in range(CARD_COUNT)
        ]
        features.extend(unseen_mask)

        # Part B: reserved_knowledge (2 players * 3 slots * 20 dims = 120 dims)
        # Order: viewer slots first (rel_player=0), then opponent slots (rel_player=1)
        for rel_player in range(2):
            actual_player_id = (self.viewer + rel_player) % 2
            p_slots = self.slots[actual_player_id] if actual_player_id < len(self.slots) else []

            for slot_idx in range(MAX_RESERVED_SLOTS):
                slot_features = [0.0] * 20
                if slot_idx < len(p_slots):
                    slot_data = p_slots[slot_idx]
                    if slot_data["kind"] == "known":
                        cid = int(slot_data["card"])
                        from_deck = bool(slot_data["from_deck"])
                        if from_deck:
                            slot_features[2] = 1.0  # known_private_from_deck
                        else:
                            slot_features[1] = 1.0  # known_public

                        # Card attributes (14 dims)
                        c_def = cards_by_id[cid]
                        c_tier = parse_tier(c_def["tier"])
                        slot_features[6 + c_tier] = 1.0  # tier one-hot (3)

                        # M32A frozen contract color order: W, B, G, R, K
                        # (splendor-catalog GemColor::ALL / splendor_gpu.encoding.COLORS)
                        bonus_color = c_def["bonus"]
                        color_order = ["white", "blue", "green", "red", "black"]
                        b_idx = color_order.index(bonus_color.lower()) if isinstance(bonus_color, str) else int(bonus_color)
                        slot_features[9 + b_idx] = 1.0  # bonus one-hot (5)

                        slot_features[14] = float(c_def["prestige"]) / 5.0  # prestige (1)

                        cost = c_def["cost"]
                        for c_i, color_name in enumerate(color_order):
                            c_cost = cost.get(color_name, 0) if isinstance(cost, dict) else cost[c_i]
                            slot_features[15 + c_i] = float(c_cost) / 7.0  # cost (5)

                    elif slot_data["kind"] == "hidden":
                        tier = int(slot_data["tier"])
                        slot_features[3 + tier] = 1.0  # hidden_tier_1/2/3
                        # Card attributes strictly zero
                else:
                    # Empty slot
                    slot_features[0] = 1.0

                features.extend(slot_features)

        # Part C: purchased_count (2 dims)
        viewer_purchased = len(players[self.viewer].get("purchased", [])) / 20.0 if self.viewer < len(players) else 0.0
        opp_purchased = len(players[1 - self.viewer].get("purchased", [])) / 20.0 if (1 - self.viewer) < len(players) else 0.0
        features.append(float(viewer_purchased))
        features.append(float(opp_purchased))

        if len(features) != BELIEF_FEATURE_DIM:
            raise ValueError(f"Projected belief feature dimension {len(features)} != expected {BELIEF_FEATURE_DIM}")

        return features
