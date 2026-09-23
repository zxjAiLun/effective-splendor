"""TypeSafe Jev Splendor agent: stdio protocol v0.5, no referee access.

Run from the repository root with `python -u jev/agent.py`. Stdout is NDJSON ONLY.
"""
from __future__ import annotations

import json
import os
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
    return card


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
    if kind in ("buy_market", "reserve_market"):
        tier = {"One": 0, "Two": 1, "Three": 2}[action["tier"]]
        cid = board["market"][tier][action["slot"]]
        label = {"action": kind, "card": card_info(cards, cid)}
        if kind == "reserve_market":
            label["return_tokens"] = action.get("return", {})
        return label
    if kind == "buy_reserved":
        cid = obs["private"]["reserved"][action["slot"]]["card"]
        return {"action": kind, "card": card_info(cards, cid)}
    if kind == "take_tokens":
        return {"action": kind, "take": action["take"], "return_tokens": action.get("return", {})}
    if kind == "reserve_deck":
        return {"action": kind, "tier": action["tier"], "unknown_card": True,
                "return_tokens": action.get("return", {})}
    if kind == "choose_noble":
        return {"action": kind, "noble": catalog["nobles"][action["noble"]]}
    if kind == "pass":
        return {"action": kind}
    raise AgentFault("unknown legal action type")


def candidates(legal: list[dict]) -> list[dict]:
    """Drop no-op takes; bound remaining choices, retaining buys and nobles.

    This is NOT a learned ranker: some legal moves are excluded if >80. We report
    that omission as a limitation, never claim Jev evaluated the entire legal set.
    """
    useful = [a for a in legal if a["type"] != "take_tokens" or a["take"] != a.get("return")]
    if not useful:  # Never invent an action; forced no-op is still legal.
        useful = legal
    if len(useful) <= MAX_OPTIONS:
        return useful
    priority = {"choose_noble": 0, "buy_market": 1, "buy_reserved": 1,
                "reserve_market": 2, "reserve_deck": 3, "take_tokens": 4, "pass": 5}
    def sort_key(pair: tuple[int, dict]) -> tuple:
        index, action = pair
        if action["type"] == "take_tokens":
            take = action["take"]
            total = sum(take.get(c, 0) for c in COLORS)
            returned = sum(action.get("return", {}).values())
            # Prefer 3 distinct colors (or 2 identical), avoid costly returns.
            return (4, returned, -total, index)
        return (priority[action["type"]], sum(action.get("return", {}).values()), 0, index)
    return [a for _, a in sorted(enumerate(useful), key=sort_key)[:MAX_OPTIONS]]


def question(obs: dict, legal: list[dict], catalog: dict) -> tuple[dict, list[dict]]:
    chosen = candidates(legal)
    criteria = {f"a{i}": description(a, obs, catalog) for i, a in enumerate(chosen)}
    return {"state": public_state(obs, catalog), "model": MODEL,
            "questions": {"move": {"type": "choice", "instructions":
                "Choose the strongest legal move for the viewer to win Splendor. Consider affordable cards, permanent discounts, nobles, opponent scores, remaining turns and resource needs. Options are actions, not statements. Choose exactly one; do not assume unknown deck contents.",
                "criteria": criteria}}}, chosen


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


def pick(obs: dict, legal: list[dict], catalog: dict, call: Callable[[dict], dict] = evaluate) -> tuple[dict, dict | None, int]:
    if not legal:
        raise AgentFault("empty legal actions")
    if len(legal) == 1:
        return legal[0], None, 1
    payload, offered = question(obs, legal, catalog)
    response = call(payload)
    try:
        answer = response["answers"]["move"]
        choice = answer["choice"]
        if answer["type"] != "choice" or not isinstance(choice, str) or choice not in payload["questions"]["move"]["criteria"]:
            raise AgentFault("TypeSafe returned non-candidate Choice")
        selected = offered[int(choice[1:])]
        if selected not in legal:
            raise AgentFault("TypeSafe selection not legal")
        usage = response.get("usage", {})
        if not isinstance(usage, dict):
            raise AgentFault("TypeSafe usage malformed")
        return selected, usage, len(offered)
    except (KeyError, TypeError, IndexError, ValueError) as exc:
        raise AgentFault("TypeSafe Choice response malformed") from exc


def send(message: dict) -> None:
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def run(lines, call: Callable[[dict], dict] = evaluate) -> dict:
    catalog = load_catalog()
    game_id = None
    seat = None
    obs = None
    obs_hash = None
    last_request = -1
    max_calls = int(os.environ.get("JEV_MAX_API_CALLS", "100"))
    if max_calls < 1:
        raise AgentFault("JEV_MAX_API_CALLS must be positive")
    metrics = {"api_calls": 0, "decisions": 0, "options_offered": 0, "options_omitted": 0,
               "input_tokens": 0, "output_tokens": 0, "model": MODEL, "model_version": None}
    def capture_call(payload: dict) -> dict:
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
            if len(legal) > 1 and metrics["api_calls"] >= max_calls:
                raise AgentFault("Jev API call budget exhausted")
            action, usage, offered = pick(obs, legal, catalog, capture_call)
            metrics["decisions"] += 1
            metrics["options_offered"] += offered
            metrics["options_omitted"] += len(legal) - offered
            if usage is not None:
                metrics["api_calls"] += 1
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
