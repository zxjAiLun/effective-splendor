"""M34A Hierarchical Action Decomposition & Pattern Vocabulary.

Encodes exact hierarchical components:
1. Action Family (5 classes): Take (0), Buy (1), Reserve (2), ChooseNoble (3), Pass (4).
2. Take Pattern Index (0..29 for valid take patterns, -1 for non-take):
   - 3-distinct (10 patterns: indices 0..9)
   - 2-same (5 patterns: indices 10..14)
   - 2-distinct (10 patterns: indices 15..24)
   - 1-distinct (5 patterns: indices 25..29)
3. Return Gem Vector (6 dims: white, blue, green, red, black, gold).
"""
from typing import Any

GEMS_5 = ["white", "blue", "green", "red", "black"]
GEMS_6 = ["white", "blue", "green", "red", "black", "gold"]

# Generate all 30 semantic take patterns in canonical deterministic order
TAKE_PATTERNS: list[tuple[int, ...]] = []

# 1. 3-distinct (10)
for i in range(5):
    for j in range(i + 1, 5):
        for k in range(j + 1, 5):
            t = [0] * 5
            t[i] = 1; t[j] = 1; t[k] = 1
            TAKE_PATTERNS.append(tuple(t))

# 2. 2-same (5)
for i in range(5):
    t = [0] * 5
    t[i] = 2
    TAKE_PATTERNS.append(tuple(t))

# 3. 2-distinct (10)
for i in range(5):
    for j in range(i + 1, 5):
        t = [0] * 5
        t[i] = 1; t[j] = 1
        TAKE_PATTERNS.append(tuple(t))

# 4. 1-distinct (5)
for i in range(5):
    t = [0] * 5
    t[i] = 1
    TAKE_PATTERNS.append(tuple(t))

assert len(TAKE_PATTERNS) == 30, f"Expected 30 take patterns, got {len(TAKE_PATTERNS)}"
PATTERN_TO_ID: dict[tuple[int, ...], int] = {p: i for i, p in enumerate(TAKE_PATTERNS)}

def get_action_family(action: dict[str, Any]) -> int:
    atype = action.get("type")
    if atype == "take_tokens":
        return 0
    elif atype in ("buy_market", "buy_reserved"):
        return 1
    elif atype in ("reserve_market", "reserve_deck"):
        return 2
    elif atype == "choose_noble":
        return 3
    elif atype == "pass":
        return 4
    raise ValueError(f"Unknown action type: {atype}")

def get_take_pattern_id(action: dict[str, Any]) -> int:
    if action.get("type") != "take_tokens":
        return -1
    take = action.get("take", {})
    t = tuple(int(take.get(g, 0)) for g in GEMS_5)
    if t not in PATTERN_TO_ID:
        raise ValueError(f"Unknown take token combination: {t}")
    return PATTERN_TO_ID[t]

def get_return_vector_6d(action: dict[str, Any]) -> list[float]:
    ret = action.get("return", {})
    return [float(ret.get(g, 0)) for g in GEMS_6]
