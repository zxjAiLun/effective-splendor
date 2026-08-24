"""Targeted unit tests for exact-transition logic across all action types and legal boundaries."""
import pytest
from pathlib import Path
from splendor_gpu.data import load_catalog
from splendor_gpu.encoding import GEMS, COLORS, TIERS
from splendor_gpu.m25_delta_v2 import encode_action_delta_v2

@pytest.fixture
def catalog():
    cat_path = Path("apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json")
    return load_catalog(cat_path)

@pytest.fixture
def base_obs():
    return {
        "viewer": 0,
        "public": {
            "player_count": 2,
            "players": [
                {
                    "id": 0,
                    "tokens": {"white": 2, "blue": 1, "green": 0, "red": 3, "black": 0, "gold": 1},
                    "bonuses": [1, 2, 0, 0, 1], # white:1, blue:2, green:0, red:0, black:1
                    "prestige": 4,
                    "reserved_count": 1,
                },
                {
                    "id": 1,
                    "tokens": {"white": 0, "blue": 0, "green": 0, "red": 0, "black": 0, "gold": 0},
                    "bonuses": [0, 0, 0, 0, 0],
                    "prestige": 0,
                    "reserved_count": 0,
                }
            ],
            "market": [
                [0, 1, 2, 3],
                [40, 41, 42, 43],
                [70, 71, 72, 73],
            ],
            "nobles": [0, 1, 2],
            "bank": {"white": 4, "blue": 4, "green": 4, "red": 4, "black": 4, "gold": 5},
        },
        "private": {
            "reserved": [{"card": 4, "is_revealed": True}]
        }
    }

def test_take_tokens_with_return(catalog, base_obs):
    # Take 3 tokens (white, blue, green), return 1 red (when at 8 tokens -> 11 -> 10)
    base_obs["public"]["players"][0]["tokens"] = {"white": 2, "blue": 2, "green": 2, "red": 1, "black": 1, "gold": 0} # sum 8
    action = {
        "type": "take_tokens",
        "take": {"white": 1, "blue": 1, "green": 1, "red": 0, "black": 0, "gold": 0},
        "return": {"white": 0, "blue": 0, "green": 0, "red": 1, "black": 0, "gold": 0},
    }
    vec = encode_action_delta_v2(base_obs, action, catalog)
    assert len(vec) == 23
    delta_vp, post_vp, dist_15 = vec[0], vec[1], vec[2]
    delta_bonuses = vec[3:8]
    delta_tokens = vec[8:14]
    post_tokens = vec[14]
    
    assert delta_vp == 0.0
    assert post_vp == pytest.approx(4.0 / 15.0)
    assert dist_15 == pytest.approx(11.0 / 15.0)
    assert delta_bonuses == [0.0, 0.0, 0.0, 0.0, 0.0]
    
    # White +1, Blue +1, Green +1, Red -1, Black 0, Gold 0
    expected_delta_tokens = [0.1, 0.1, 0.1, -0.1, 0.0, 0.0]
    assert [pytest.approx(x) for x in delta_tokens] == expected_delta_tokens
    # Initial 8 + 3 - 1 = 10 -> 1.0
    assert post_tokens == pytest.approx(1.0)

def test_reserve_market_9_tokens_no_return_needed(catalog, base_obs):
    # Case 1: Player has 9 tokens, bank has gold. Player takes 1 gold, total becomes 10, return is empty.
    base_obs["public"]["players"][0]["tokens"] = {"white": 2, "blue": 2, "green": 2, "red": 2, "black": 1, "gold": 0} # 9 tokens
    action = {
        "type": "reserve_market",
        "tier": "One",
        "slot": 0,
        "return": {"white": 0, "blue": 0, "green": 0, "red": 0, "black": 0, "gold": 0},
    }
    vec = encode_action_delta_v2(base_obs, action, catalog)
    delta_bonuses = vec[3:8]
    delta_tokens = vec[8:14]
    post_tokens = vec[14]
    
    assert delta_bonuses == [0.0, 0.0, 0.0, 0.0, 0.0]
    # Gold +1 (0.1), all others 0.0
    assert [pytest.approx(x) for x in delta_tokens] == [0.0, 0.0, 0.0, 0.0, 0.0, 0.1]
    assert post_tokens == pytest.approx(1.0)

def test_reserve_market_10_tokens_receives_gold_and_returns_color_token(catalog, base_obs):
    # Case 2: Player has 10 tokens, bank has gold. Engine gives 1 gold (11 tokens), player returns 1 white token -> net total 10 tokens.
    base_obs["public"]["players"][0]["tokens"] = {"white": 3, "blue": 2, "green": 2, "red": 2, "black": 1, "gold": 0} # 10 tokens
    action = {
        "type": "reserve_market",
        "tier": "One",
        "slot": 0,
        "return": {"white": 1, "blue": 0, "green": 0, "red": 0, "black": 0, "gold": 0},
    }
    vec = encode_action_delta_v2(base_obs, action, catalog)
    delta_bonuses = vec[3:8]
    delta_tokens = vec[8:14]
    post_tokens = vec[14]
    
    assert delta_bonuses == [0.0, 0.0, 0.0, 0.0, 0.0]
    # White -1 (-0.1), Gold +1 (+0.1)
    assert [pytest.approx(x) for x in delta_tokens] == [-0.1, 0.0, 0.0, 0.0, 0.0, 0.1]
    # 10 + 1 (gold) - 1 (white) = 10 -> 1.0
    assert post_tokens == pytest.approx(1.0)

def test_reserve_deck_bank_has_no_gold(catalog, base_obs):
    # Case 3: Bank has 0 gold. Player reserves from deck, receives 0 gold, returns 0.
    base_obs["public"]["bank"]["gold"] = 0
    action = {
        "type": "reserve_deck",
        "tier": "Two",
        "return": {"white": 0, "blue": 0, "green": 0, "red": 0, "black": 0, "gold": 0},
    }
    vec = encode_action_delta_v2(base_obs, action, catalog)
    delta_tokens = vec[8:14]
    post_tokens = vec[14]
    
    assert [pytest.approx(x) for x in delta_tokens] == [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    # 7 tokens initially -> 0.7
    assert post_tokens == pytest.approx(0.7)

def test_buy_market_single_qualifying_noble_immediate_vp(catalog, base_obs):
    # Noble 0 requirement: check catalog
    n0 = catalog["nobles"][0]
    # Configure bonuses so adding this card satisfies exactly Noble 0 and not Noble 1 or 2
    req = list(n0["requirements"]) # e.g. [0, 0, 4, 4, 0]
    # Set bonuses to be 1 away in green (index 2)
    base_obs["public"]["players"][0]["bonuses"] = [req[0], req[1], max(0, req[2] - 1), req[3], req[4]]
    # Ensure other nobles do not qualify
    base_obs["public"]["nobles"] = [0]
    
    # Mock card 0 bonus to green
    card = catalog["cards"][0]
    # Find a card in catalog that gives green bonus
    green_card_id = None
    for cid, cdata in catalog["cards"].items():
        if str(cdata["bonus"]).lower() == "green":
            green_card_id = cid
            break
    base_obs["public"]["market"][0][0] = green_card_id
    
    action = {"type": "buy_market", "tier": "One", "slot": 0}
    vec = encode_action_delta_v2(base_obs, action, catalog)
    card_p = catalog["cards"][green_card_id]["prestige"]
    # Single noble qualified -> +3 VP immediately added
    assert vec[0] == pytest.approx((card_p + 3.0) / 5.0)
    assert vec[22] == 1.0 # noble_delta

def test_buy_market_multiple_qualifying_nobles_does_not_add_immediate_vp(catalog, base_obs):
    # Construct case where two nobles qualify simultaneously
    # e.g., Noble 0 and Noble 1 both need white >= 3, and current white is 2. Card gives white.
    # We mock noble requirements
    catalog_mock = {
        "cards": {
            0: {"tier": "One", "bonus": "white", "prestige": 1, "cost": [0, 0, 0, 0, 0]}
        },
        "nobles": {
            0: {"prestige": 3, "requirements": [3, 0, 0, 0, 0]},
            1: {"prestige": 3, "requirements": [3, 0, 0, 0, 0]},
        }
    }
    base_obs["public"]["players"][0]["bonuses"] = [2, 0, 0, 0, 0]
    base_obs["public"]["nobles"] = [0, 1]
    base_obs["public"]["market"][0][0] = 0
    
    action = {"type": "buy_market", "tier": "One", "slot": 0}
    vec = encode_action_delta_v2(base_obs, action, catalog_mock)
    # Card prestige = 1 (0.2). Multiple nobles qualify -> NO immediate +3 VP in delta_vp
    assert vec[0] == pytest.approx(1.0 / 5.0)
    assert vec[22] == 1.0 # noble_delta still signals noble opportunity

def test_choose_noble(catalog, base_obs):
    action = {"type": "choose_noble", "noble": 0}
    vec = encode_action_delta_v2(base_obs, action, catalog)
    assert vec[0] == pytest.approx(3.0 / 5.0)
    assert vec[22] == 1.0
