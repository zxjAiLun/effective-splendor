"""TypeSafe Jev Splendor agent: stdio protocol v0.5, no referee access.

Run from the repository root with `python -u jev/agent.py`. Stdout is NDJSON ONLY.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
API_URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
PROTOCOL = "0.5"
COLORS = ("white", "blue", "green", "red", "black")
MAX_OPTIONS = 80  # Explicit bounded subset of the 255-option Choice API ceiling.
TERM_NAMES = ("category_base", "prestige", "noble_gain", "noble_direct", "bonus_usefulness",
              "cost_efficiency", "deficit_reduction", "new_target", "return_penalty", "gold_value",
              "reserve_proximity", "reserve_gold", "reserve_blind_gold")
FAMILIES = {
    "buy": ("buy_market", "buy_reserved"), "take_tokens": ("take_tokens",),
    "reserve": ("reserve_market", "reserve_deck"), "choose_noble": ("choose_noble",), "pass": ("pass",),
}
FAMILY_NAMES = {"buy": "Buy a development card", "take_tokens": "Take gems (resource collection)",
                "reserve": "Reserve a card (visible or blind)", "choose_noble": "Claim a noble",
                "pass": "Pass (forced only)"}
ACTION_TERMS = {
    "buy_market": "Buy a face-up Development Card from the market",
    "buy_reserved": "Buy a Development Card from your own reserved row",
    "take_tokens": "Take gem tokens from the bank (resource collection)",
    "reserve_market": "Reserve a face-up Development Card; gain a Gold Joker if available",
    "reserve_deck": "Reserve an unknown top card from a tier deck; gain a Gold Joker if available",
    "choose_noble": "Claim one eligible Noble tile for prestige points",
    "pass": "Pass only when the rules leave no productive move",
}
TERM_GLOSSARY = {
    "category_base": "fixed heuristic preference for an action family; not outcome evidence",
    "prestige": "heuristic weight for immediate prestige points gained from a card",
    "noble_gain": "heuristic weight for a newly qualifying noble after a purchase",
    "noble_direct": "heuristic weight for choosing a noble now",
    "bonus_usefulness": "heuristic estimate of how a permanent color discount helps visible card targets",
    "cost_efficiency": "heuristic penalty proportional to card gem cost",
    "deficit_reduction": "heuristic value of reducing missing gems for current visible targets",
    "new_target": "heuristic value for making a visible card affordable",
    "return_penalty": "heuristic penalty for returning gems to the bank",
    "gold_value": "heuristic value for gaining wild gold",
    "reserve_proximity": "heuristic value for reserving a visible card near affordability",
    "reserve_gold": "heuristic value of gold granted by reserving a visible card",
    "reserve_blind_gold": "heuristic value of gold granted by blind-reserving a deck card",
}


class AgentFault(Exception):
    """Safe, credential-free diagnostic suitable for stderr."""


def credential() -> str:
    value = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not value:
        key_file = Path(os.environ.get("TYPESAFE_API_KEY_FILE", str(HERE.parent / "TYPESAFE_API_KEY")))
        try:
            value = key_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise AgentFault("TypeSafe credential file unavailable") from exc
    if not value or any(ch.isspace() for ch in value):
        raise AgentFault("TypeSafe credential invalid")
    return value


def load_catalog() -> dict:
    data = json.loads((HERE / "catalog.json").read_text(encoding="utf-8"))
    if data["catalog_version"] != "0.1.0" or len(data["cards"]) != 90 or len(data["nobles"]) != 10:
        raise AgentFault("catalog snapshot incompatible")
    return data


def card_info(cards: list[dict], card_id: int) -> dict:
    card = cards[card_id]
    if card["id"] != card_id:
        raise AgentFault("catalog card id mismatch")
    return {**card, "cost_by_color": dict(zip(COLORS, card["cost"], strict=True))}


def public_state(obs: dict, catalog: dict) -> dict:
    """Allowlist fields; never forward arbitrary server fields to external service."""
    board = obs["public"]
    viewer = obs["viewer"]
    cards = catalog["cards"]
    market = [[card_info(cards, cid) if cid is not None else None for cid in row] for row in board["market"]]
    reserved = [dict(slot=r["slot"], card=card_info(cards, r["card"])) for r in obs["private"]["reserved"]]
    players = [dict(seat=p["id"], prestige=p["prestige"], tokens=p["tokens"], bonuses=p["bonuses"],
                    reserved_count=p["reserved_count"], purchased_count=len(p["purchased"]), nobles=p["nobles"])
               for p in board["players"]]
    return dict(goal="Win base-game Splendor: 15 prestige; most points at end of final round.",
                viewer=viewer, phase=board["phase"], bank=board["bank"], market=market,
                deck_counts=board["deck_counts"], nobles=[catalog["nobles"][i] for i in board["nobles"]],
                players=players, own_reserved=reserved, final_round=board["end_game_triggered"],
                turns_remaining_in_final_round=board["turns_remaining_in_final_round"])


def description(action: dict, obs: dict, catalog: dict) -> dict:
    kind = action["type"]
    board = obs["public"]
    cards = catalog["cards"]
    standard_name = ACTION_TERMS[kind]
    if kind in ("buy_market", "reserve_market"):
        tier = {"One": 0, "Two": 1, "Three": 2}[action["tier"]]
        cid = board["market"][tier][action["slot"]]
        label = {"action": kind, "standard_term": standard_name, "card": card_info(cards, cid)}
        if kind == "reserve_market":
            label["return_tokens"] = action.get("return", {})
        return label
    if kind == "buy_reserved":
        cid = obs["private"]["reserved"][action["slot"]]["card"]
        return {"action": kind, "standard_term": standard_name, "card": card_info(cards, cid)}
    if kind == "take_tokens":
        return {"action": kind, "standard_term": standard_name, "take": action["take"], "return_tokens": action.get("return", {})}
    if kind == "reserve_deck":
        return {"action": kind, "standard_term": standard_name, "tier": action["tier"], "unknown_card": True,
                "return_tokens": action.get("return", {})}
    if kind == "choose_noble":
        noble = catalog["nobles"][action["noble"]]
        return {"action": kind, "standard_term": standard_name, "noble": {**noble, "requirements_by_color": dict(zip(COLORS, noble["requirements"], strict=True))}}
    if kind == "pass":
        return {"action": kind, "standard_term": standard_name}
    raise AgentFault("unknown legal action type")


def heuristic_terms(obs: dict, legal: list[dict], timeout: float = 5.0) -> list[dict]:
    """Get the exact existing Rust heuristic decomposition; do not reimplement it in Python."""
    configured = os.environ.get("JEV_SPLENDOR_BINARY")
    binary = Path(configured) if configured else next(
        (p for p in (HERE.parent / "target/release/splendor.exe", HERE.parent / "target/release/splendor",
                     HERE.parent / "target/debug/splendor.exe", HERE.parent / "target/debug/splendor") if p.is_file()), None)
    if binary is None or not binary.is_file():
        raise AgentFault("local heuristic term helper unavailable; build splendor-cli")
    request = json.dumps({"observation": obs, "legal_actions": legal}, separators=(",", ":"))
    try:
        result = subprocess.run([str(binary), "agent-heuristic-terms"], input=request + "\n", text=True,
                                capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AgentFault("local heuristic term helper failed") from exc
    if result.returncode != 0:
        raise AgentFault("local heuristic term helper rejected state")
    try:
        terms = json.loads(result.stdout)["terms"]
        if len(terms) != len(legal) or any(set(t) != set(TERM_NAMES) for t in terms):
            raise ValueError("term schema mismatch")
        if any(type(value) is not int for t in terms for value in t.values()):
            raise ValueError("term value schema mismatch")
        return terms
    except (ValueError, KeyError, TypeError) as exc:
        raise AgentFault("local heuristic term helper returned invalid terms") from exc


def action_family(action: dict) -> str:
    for family, kinds in FAMILIES.items():
        if action["type"] in kinds:
            return family
    raise AgentFault("unknown legal action type")


def candidate_indices(legal: list[dict]) -> list[int]:
    indices = [i for i, a in enumerate(legal) if a["type"] != "take_tokens" or a["take"] != a.get("return")]
    return indices or list(range(len(legal)))


def _term_view(terms: dict) -> dict:
    result = dict(terms)
    result["heuristic_total"] = sum(terms[name] for name in TERM_NAMES)
    return result


def family_question(obs: dict, legal: list[dict], indices: list[int], terms: list[dict], catalog: dict) -> dict:
    grouped = {}
    for i in indices:
        grouped.setdefault(action_family(legal[i]), []).append(i)
    criteria = {}
    for family, members in grouped.items():
        strongest = max(members, key=lambda i: sum(terms[i][name] for name in TERM_NAMES if name != "category_base"))
        criteria[family] = {
            "family": FAMILY_NAMES[family], "available_legal_move_count": len(members),
            "best_existing_heuristic_total_excluding_family_prior": sum(terms[strongest][name] for name in TERM_NAMES if name != "category_base"),
            "best_move_example": description(legal[strongest], obs, catalog),
            "best_move_heuristic_terms": _term_view(terms[strongest]),
        }
    return {"state": public_state(obs, catalog), "model": MODEL,
            "questions": {"family": {"type": "choice", "instructions":
                "Stage 1 of 2: choose the move family most likely to help the viewer win Splendor. You will next choose one exact legal move in that family. Consider board, targets, engine building and opponent threat. The family prior category_base is omitted from the comparison value because it is a fixed cross-family bias. Other existing heuristic terms are named baseline signals, not ground truth.",
                "criteria": criteria}}}


def move_question(obs: dict, legal: list[dict], indices: list[int], terms: list[dict], catalog: dict, family: str) -> tuple[dict, list[int]]:
    if len(indices) > MAX_OPTIONS:
        indices = sorted(indices, key=lambda i: (-sum(terms[i][name] for name in TERM_NAMES), i))[:MAX_OPTIONS]
    criteria = {f"a{j}": {"standard_action": description(legal[i], obs, catalog),
                            "existing_heuristic_terms": _term_view(terms[i])}
                for j, i in enumerate(indices)}
    instructions = (
        f"Stage 2 of 2: select the single best legal move from the {FAMILY_NAMES[family]} family. "
        "Standard Splendor terms: Development Card means a purchased engine card; Prestige Points (VP) are victory points; "
        "Bonus is its permanent one-gem discount; Noble is a 3-point tile claimed when its color requirements are met; "
        "Gold Joker can substitute for any colored gem; market refill/deck draws are unknown. "
        "Use the board and these canonical heuristic term definitions: " + json.dumps(TERM_GLOSSARY, ensure_ascii=False) +
        " Each numeric field is the current project heuristic's weighted additive term, not probability, points, "
        "or truth; the total is only an advisory baseline. You may disagree with it. Respect the exact action and do not invent parameters."
    )
    return {"state": public_state(obs, catalog), "model": MODEL,
            "questions": {"move": {"type": "choice", "instructions": instructions, "criteria": criteria}}}, indices


def evaluate(payload: dict, timeout: float = 18.0) -> dict:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(API_URL, data=body, method="POST", headers={
        "Authorization": "Bearer " + credential(), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status != 200:
                raise AgentFault(f"TypeSafe HTTP {response.status}")
            raw = response.read(256_001)
            if len(raw) > 256_000:
                raise AgentFault("TypeSafe response too large")
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        raise AgentFault(f"TypeSafe HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise AgentFault("TypeSafe transport failed") from exc
    except (ValueError, UnicodeDecodeError) as exc:
        raise AgentFault("TypeSafe returned invalid JSON") from exc


def _choice(response: dict, question_id: str, allowed: set[str]) -> tuple[str, dict]:
    try:
        answer = response["answers"][question_id]
        choice = answer["choice"]
        if answer["type"] != "choice" or not isinstance(choice, str) or choice not in allowed:
            raise AgentFault("TypeSafe returned non-candidate Choice")
        usage = response.get("usage", {})
        if not isinstance(usage, dict):
            raise AgentFault("TypeSafe usage malformed")
        return choice, usage
    except (KeyError, TypeError, IndexError, ValueError) as exc:
        raise AgentFault("TypeSafe Choice response malformed") from exc


def pick(obs: dict, legal: list[dict], catalog: dict, call: Callable[[dict], dict] = evaluate,
         term_provider: Callable[[dict, list[dict]], list[dict]] = heuristic_terms) -> tuple[dict, dict | None, int, int]:
    if not legal:
        raise AgentFault("empty legal actions")
    if len(legal) == 1:
        return legal[0], None, 1, 0
    terms = term_provider(obs, legal)
    if len(terms) != len(legal):
        raise AgentFault("heuristic term count does not match legal action count")
    indices = candidate_indices(legal)
    families = sorted({action_family(legal[i]) for i in indices})
    family_choice = families[0]
    usages = []
    calls = 0
    if len(families) > 1:
        stage1 = family_question(obs, legal, indices, terms, catalog)
        family_choice, usage = _choice(call(stage1), "family", set(families))
        usages.append(usage)
        calls += 1
    scoped = [i for i in indices if action_family(legal[i]) == family_choice]
    stage2, offered = move_question(obs, legal, scoped, terms, catalog, family_choice)
    option = next(iter(stage2["questions"]["move"]["criteria"]))
    if len(offered) > 1:
        option, usage = _choice(call(stage2), "move", set(stage2["questions"]["move"]["criteria"]))
        usages.append(usage)
        calls += 1
    selected = legal[offered[int(option[1:])]]
    if selected not in legal or action_family(selected) != family_choice:
        raise AgentFault("TypeSafe selection not legal in chosen family")
    combined = {key: sum(u.get(key, 0) for u in usages if type(u.get(key, 0)) is int)
                for key in ("input_tokens", "output_tokens")}
    return selected, combined if calls else None, len(offered), calls


def send(message: dict) -> None:
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def run(lines, call: Callable[[dict], dict] = evaluate,
        term_provider: Callable[[dict, list[dict]], list[dict]] = heuristic_terms) -> dict:
    catalog = load_catalog()
    game_id = None
    seat = None
    obs = None
    obs_hash = None
    last_request = -1
    max_calls = int(os.environ.get("JEV_MAX_API_CALLS", "100"))
    if max_calls < 1:
        raise AgentFault("JEV_MAX_API_CALLS must be positive")
    metrics = {"api_calls": 0, "stage1_calls": 0, "stage2_calls": 0, "decisions": 0,
               "families_offered": 0, "options_offered": 0, "options_omitted": 0,
               "input_tokens": 0, "output_tokens": 0, "model": MODEL, "model_version": None}
    def capture_call(payload: dict) -> dict:
        if metrics["api_calls"] >= max_calls:
            raise AgentFault("Jev API call budget exhausted")
        metrics["api_calls"] += 1
        stage = "stage1_calls" if "family" in payload.get("questions", {}) else "stage2_calls"
        metrics[stage] += 1
        response = call(payload)
        if isinstance(response, dict) and isinstance(response.get("model"), str):
            metrics["model_version"] = response["model"]
        return response
    for line in lines:
        msg = json.loads(line)
        kind = msg.get("type")
        if msg.get("protocol_version") != PROTOCOL:
            raise AgentFault("protocol version mismatch")
        if kind == "hello":
            if game_id is not None:
                raise AgentFault("duplicate hello")
            game_id = msg["game_id"]
            if msg.get("catalog_version") != catalog["catalog_version"]:
                raise AgentFault("catalog version mismatch")
            send({"type": "hello", "protocol_version": PROTOCOL, "game_id": game_id,
                  "agent_name": "typesafe-jev-choice", "agent_version": "0.1.0"})
            continue
        if game_id is None or msg.get("game_id") != game_id:
            raise AgentFault("game id mismatch or missing hello")
        if kind == "game_start":
            if seat is not None:
                raise AgentFault("duplicate game_start")
            seat = msg["recipient_player_id"]
        elif kind == "observation":
            if seat is None or msg["recipient_player_id"] != seat:
                raise AgentFault("observation recipient mismatch")
            obs = msg["observation"]
            if obs["viewer"] != seat:
                raise AgentFault("observation viewer mismatch")
            obs_hash = msg["observation_hash"]
        elif kind == "request_action":
            if seat is None or msg["recipient_player_id"] != seat or obs is None or msg["observation_hash"] != obs_hash:
                raise AgentFault("request observation/recipient mismatch")
            rid = msg["request_id"]
            if type(rid) is not int or rid <= last_request:
                raise AgentFault("request id not increasing")
            last_request = rid
            legal = msg["legal_actions"]
            family_count = len({action_family(legal[i]) for i in candidate_indices(legal)})
            action, usage, offered, _calls = pick(obs, legal, catalog, capture_call, term_provider)
            metrics["decisions"] += 1
            metrics["families_offered"] += family_count
            metrics["options_offered"] += offered
            metrics["options_omitted"] += len(legal) - offered
            if usage is not None:
                for k in ("input_tokens", "output_tokens"):
                    v = usage.get(k, 0)
                    if type(v) is int and v >= 0:
                        metrics[k] += v
            send({"type": "action", "protocol_version": PROTOCOL, "game_id": game_id,
                  "request_id": rid, "action": action})
        elif kind == "ping":
            send({"type": "pong", "protocol_version": PROTOCOL, "game_id": game_id})
        elif kind in ("game_end", "game_truncated"):
            if seat is None or msg["recipient_player_id"] != seat:
                raise AgentFault("terminal recipient mismatch")
            break
        elif kind == "error":
            raise AgentFault("arena reported error")
        elif kind not in ("action_applied", "event"):
            raise AgentFault("unexpected server message")
        if kind in ("action_applied", "event") and (seat is None or msg["recipient_player_id"] != seat):
            raise AgentFault("event recipient mismatch")
    else:
        raise AgentFault("server stream ended before game_end")
    return metrics


if __name__ == "__main__":
    try:
        summary = run(sys.stdin)
        if "JEV_METRICS_FILE" in os.environ:
            Path(os.environ["JEV_METRICS_FILE"]).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    except (AgentFault, KeyError, IndexError, TypeError, ValueError) as exc:
        # Never print exception chains/HTTP bodies/credential or raw state.
        message = str(exc) if isinstance(exc, AgentFault) else "malformed arena message"
        print("jev agent error: " + message, file=sys.stderr)
        sys.exit(1)
