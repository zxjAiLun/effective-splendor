"""TypeSafe Jev Splendor agent: stdio protocol v0.5, no referee access.

Run from the repository root with `python -u jev/agent.py`. Stdout is NDJSON ONLY.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Callable

from runtime import AGENT_VERSION, AgentFault, Deadline, Session, run_child
from transport import API_URL, credential, evaluate

HERE = Path(__file__).resolve().parent
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
    "prestige": "weighted card preference: buying scores printed card VP now; reserving scores potential card VP only (zero immediate VP)",
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


RULES = {
    "scope": "Repository base Splendor, 2-4 players, no expansions; choose only server-certified legal actions.",
    "turn": "One main action: take gems, buy a development card, or reserve one card. Pass only if forced.",
    "tokens": "Take 3 different available colors (fewer only if fewer remain), or 2 of a color with at least 4 in bank. No gold by taking. Return excess to finish with at most 10 tokens; returns are part of the action.",
    "payment": "Permanent color bonuses discount each purchase; spend colored gems first, gold substitutes for remaining deficits. Spent tokens return to the bank. Cards and bonuses are kept.",
    "reserve": "At most 3 reserved cards. Reserve face-up or blind from a tier deck; receive 1 gold if available, even if you must return tokens. Reserving earns neither VP nor a permanent bonus. Own blind reserves are visible only to their owner.",
    "nobles": "After a purchase, claim at most one eligible noble (permanent bonuses meet its color requirements). One eligible noble is automatic; multiple require a zero-extra-turn choose_noble decision. A base noble is worth 3 VP.",
    "ending": "15 or more VP triggers the end of the current round, not an instant win. Seats after the triggering seat still play so everyone has equal turns. Highest final VP wins; a tie favors fewer purchased development cards, then remains shared.",
    "stalemate": "A full cycle of consecutive forced passes also ends the game, using the same score/tie-break rule.",
    "hidden": "Future market refills and deck order, and opponents' blind reserves, are unknown. No hypothetical refill is observed.",
}


def load_catalog() -> dict:
    data = json.loads((HERE / "catalog.json").read_text(encoding="utf-8"))
    if data["catalog_version"] != "0.1.0" or len(data["cards"]) != 90 or len(data["nobles"]) != 10:
        raise AgentFault("catalog snapshot incompatible")
    return data


def count(value) -> int:
    if type(value) is not int or not 0 <= value <= 255:
        raise AgentFault("invalid public count", "invalid_observation")
    return value


def gems(value: dict) -> dict:
    return {c: count(value.get(c, 0)) for c in (*COLORS, "gold")}


def colors(values: list[int]) -> dict:
    if len(values) != len(COLORS):
        raise AgentFault("invalid color array", "invalid_observation")
    return {c: count(v) for c, v in zip(COLORS, values, strict=True)}


def card_info(cards: list[dict], card_id: int) -> dict:
    if type(card_id) is not int or not 0 <= card_id < len(cards):
        raise AgentFault("invalid card id", "invalid_observation")
    card = cards[card_id]
    if card["id"] != card_id:
        raise AgentFault("catalog card id mismatch")
    return dict(id=card_id, tier=card["tier"], bonus=card["bonus"], prestige=count(card["prestige"]),
                cost_by_color=colors(card["cost"]))


def noble_info(catalog: dict, noble_id: int) -> dict:
    if type(noble_id) is not int or not 0 <= noble_id < len(catalog["nobles"]):
        raise AgentFault("invalid noble id", "invalid_observation")
    noble = catalog["nobles"][noble_id]
    return dict(id=noble_id, prestige=count(noble["prestige"]), requirements_by_color=colors(noble["requirements"]))


def public_state(obs: dict, catalog: dict) -> dict:
    """Deeply project public and own-private fields, never arbitrary nested server data."""
    board = obs["public"]
    cards = catalog["cards"]
    market = [[card_info(cards, cid) if cid is not None else None for cid in row] for row in board["market"]]
    reserved = [dict(slot=count(r["slot"]), card=card_info(cards, r["card"])) for r in obs["private"]["reserved"]]
    players = [dict(seat=count(p["id"]), prestige=count(p["prestige"]), tokens=gems(p["tokens"]),
                    bonuses_by_color=colors(p["bonuses"]), reserved_count=count(p["reserved_count"]),
                    public_reserved=[card_info(cards, cid) for cid in p["public_reserved"]],
                    purchased_count=len(p["purchased"]), nobles=[noble_info(catalog, i) for i in p["nobles"]])
               for p in board["players"]]
    return dict(rules=RULES, viewer=count(obs["viewer"]), phase=board["phase"], bank=gems(board["bank"]), market=market,
                deck_counts=[count(n) for n in board["deck_counts"]], nobles=[noble_info(catalog, i) for i in board["nobles"]],
                players=players, own_reserved=reserved, final_round=board["end_game_triggered"],
                turns_remaining_in_final_round=board["turns_remaining_in_final_round"])


def description(action: dict, obs: dict, catalog: dict) -> dict:
    kind = action["type"]
    board = obs["public"]
    cards = catalog["cards"]
    label = {"action": kind, "standard_term": ACTION_TERMS[kind]}
    effects = {"card_vp_now": 0, "noble_vp_now": 0, "permanent_bonus_gained": None}
    if kind in ("buy_market", "reserve_market", "buy_reserved"):
        slot = count(action["slot"])
        if kind == "buy_reserved":
            cid = obs["private"]["reserved"][slot]["card"]
        else:
            tier = {"One": 0, "Two": 1, "Three": 2}[action["tier"]]
            cid = board["market"][tier][slot]
            label["tier"] = action["tier"]
        label.update(slot=slot, card=card_info(cards, cid))
        if kind.startswith("buy"):
            effects.update(card_vp_now=cards[cid]["prestige"], permanent_bonus_gained=cards[cid]["bonus"],
                           noble_vp_now=None, noble_settlement="Engine checks eligibility after purchase; not included in card_vp_now.")
        else:
            effects["reserved_card_vp_if_later_bought"] = cards[cid]["prestige"]
    if kind in ("reserve_market", "reserve_deck", "take_tokens"):
        returned = gems(action.get("return", {}))
        label["return_tokens"] = returned
        taken = gems(action["take"]) if kind == "take_tokens" else gems({"gold": int(board["bank"]["gold"] > 0)})
        effects["net_tokens"] = {c: taken[c] - returned[c] for c in taken}
        if kind == "take_tokens":
            label["take"] = taken
        else:
            effects["gold_received_before_returns"] = taken["gold"]
    if kind == "reserve_deck":
        label.update(tier=action["tier"], unknown_card=True)
        effects["reserved_card_vp_if_later_bought"] = None
    if kind == "choose_noble":
        label["noble"] = noble_info(catalog, action["noble"])
        effects["noble_vp_now"] = label["noble"]["prestige"]
    label["known_effects"] = effects
    return label


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
        result = run_child([str(binary), "agent-heuristic-terms"], input=request + "\n", timeout=timeout)
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


def _term_view(terms: dict, *, family_prior=True) -> dict:
    result = {k: terms[k] for k in TERM_NAMES if family_prior or k != "category_base"}
    result["heuristic_total" if family_prior else "total_excluding_family_prior"] = sum(result.values())
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
            "best_move_heuristic_terms": _term_view(terms[strongest], family_prior=False),
        }
    return {"state": public_state(obs, catalog), "model": MODEL,
            "questions": {"family": {"type": "choice", "instructions":
                {"task": "Stage 1 of 2: choose the move family most likely to help the viewer win Splendor. You will next choose one exact legal move in that family. Consider board, targets, engine building and opponent threat. Fixed family priors are not supplied. Heuristic advice is not ground truth or game-effect units.",
                 "advisory_term_definitions": {k: v for k, v in TERM_GLOSSARY.items() if k != "category_base"}},
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
         term_provider: Callable[[dict, list[dict]], list[dict]] = heuristic_terms, trace=None) -> tuple[dict, dict | None, int, int]:
    if not legal:
        raise AgentFault("empty legal actions")
    if len(legal) == 1:
        if trace:
            trace(family=action_family(legal[0]), family_count=1, noops_removed=0, routed_out=0, cap_removed=0,
                  offered_indices=[0], selected_index=0, selected_action=legal[0])
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
    if trace:
        trace(family=family_choice, family_count=len(families), noops_removed=len(legal)-len(indices),
              routed_out=len(indices)-len(scoped), cap_removed=len(scoped)-len(offered),
              offered_indices=offered, selected_index=offered[int(option[1:])], selected_action=selected)
    combined = {key: sum(u.get(key, 0) for u in usages if type(u.get(key, 0)) is int)
                for key in ("input_tokens", "output_tokens")}
    return selected, combined if calls else None, len(offered), calls


def send(message: dict) -> None:
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def run(lines, call=evaluate, term_provider=heuristic_terms, *, session=None,
        clock=time.monotonic, sleeper=time.sleep) -> dict:
    if session is None:
        path = Path(os.environ["JEV_METRICS_FILE"]) if os.environ.get("JEV_METRICS_FILE") else None
        session = Session(MODEL, max_calls=int(os.environ.get("JEV_MAX_API_CALLS", "100")),
                          summary_path=path, clock=clock, sleeper=sleeper)
    try:
        outcome = drive(lines, call, term_provider, session)
    except BaseException as exc:
        cancelled = isinstance(exc, (KeyboardInterrupt, SystemExit))
        session.finish("cancelled" if cancelled else "failed",
                       "cancelled" if cancelled else exc.code if isinstance(exc, AgentFault) else "local_error")
        raise
    session.finish(outcome)
    return session.metrics


def drive(lines, call, term_provider, session):
    catalog = load_catalog()
    game_id = seat = obs = obs_hash = None
    last_request = -1
    for line in lines:
        if len(line.encode("utf-8")) > 2_000_000:
            raise AgentFault("arena message too large", "message_too_large")
        msg = json.loads(line)
        kind = msg.get("type")
        if msg.get("protocol_version") != PROTOCOL:
            raise AgentFault("protocol version mismatch")
        if kind == "hello":
            if game_id is not None:
                raise AgentFault("duplicate hello")
            game_id = msg["game_id"]
            if msg.get("catalog_version") != catalog["catalog_version"] or msg.get("ruleset") != "splendor-base-v1":
                raise AgentFault("catalog or ruleset mismatch")
            send({"type": "hello", "protocol_version": PROTOCOL, "game_id": game_id,
                  "agent_name": "typesafe-jev-choice", "agent_version": AGENT_VERSION})
            continue
        if game_id is None or msg.get("game_id") != game_id:
            raise AgentFault("game id mismatch or missing hello")
        if kind == "game_start":
            if seat is not None:
                raise AgentFault("duplicate game_start")
            seat = msg["recipient_player_id"]
            # The runner may pre-register a run trace id and seat before the game
            # starts. The agent records the name it was actually given; it never
            # invents one, and an unknown message type stays rejected below.
            run_trace_id = msg.get("run_trace_id")
            if run_trace_id is not None:
                session.identify({"game_id": game_id, "run_id": run_trace_id, "seat": seat})
        elif kind == "observation":
            if seat is None or msg["recipient_player_id"] != seat:
                raise AgentFault("observation recipient mismatch")
            obs = msg["observation"]
            if obs["viewer"] != seat:
                raise AgentFault("observation viewer mismatch")
            obs_hash = msg["observation_hash"]
        elif kind == "request_action":
            deadline = Deadline(msg["deadline_ms"], session.clock)
            if seat is None or msg["recipient_player_id"] != seat or obs is None or msg["observation_hash"] != obs_hash:
                raise AgentFault("request observation/recipient mismatch")
            rid = msg["request_id"]
            if type(rid) is not int or rid <= last_request:
                raise AgentFault("request id not increasing")
            last_request = rid
            session.request_id = rid
            legal = msg["legal_actions"]
            session.emit("decision_start", deadline_ms=msg["deadline_ms"], legal_count=len(legal),
                         observation_hash=obs_hash, actor=seat, ply=msg.get("ply"))

            def terms(o, actions):
                started = session.clock()
                result = term_provider(o, actions, timeout=deadline.remaining(5.0))
                deadline.remaining()
                session.emit("helper_complete", latency_ms=round((session.clock()-started)*1000, 3))
                return result

            def capture(payload):
                return session.ask(payload, deadline, call)

            def trace(**info):
                session.metrics["families_offered"] += info["family_count"]
                session.metrics["options_offered"] += len(info["offered_indices"])
                for name in ("noops_removed", "routed_out", "cap_removed"):
                    session.metrics[name] += info[name]
                    session.metrics["options_omitted"] += info[name]
                session.emit("decision_choice", **info)

            action, _, _, _ = pick(obs, legal, catalog, capture, terms, trace)
            deadline.remaining()
            send({"type": "action", "protocol_version": PROTOCOL, "game_id": game_id,
                  "request_id": rid, "action": action})
            session.metrics["decisions"] += 1
            session.emit("action_sent")
        elif kind == "ping":
            send({"type": "pong", "protocol_version": PROTOCOL, "game_id": game_id})
        elif kind in ("game_end", "game_truncated"):
            if seat is None or msg["recipient_player_id"] != seat:
                raise AgentFault("terminal recipient mismatch")
            return "completed" if kind == "game_end" else "truncated"
        elif kind == "error":
            raise AgentFault("arena reported error")
        elif kind not in ("action_applied", "event"):
            raise AgentFault("unexpected server message")
        if kind in ("action_applied", "event") and (seat is None or msg["recipient_player_id"] != seat):
            raise AgentFault("event recipient mismatch")
    raise AgentFault("server stream ended before game_end", "arena_eof")


def bounded_lines(stream):
    while True:
        line = stream.readline(2_000_001)
        if not line:
            return
        if len(line.encode("utf-8")) > 2_000_000:
            raise AgentFault("arena message too large", "message_too_large")
        yield line


def main():
    # Standalone agents also retain failure evidence. Tests using run() can stay in-memory.
    if not os.environ.get("JEV_METRICS_FILE"):
        directory = HERE.parent / "local-artifacts/jev" / ("agent-" + uuid.uuid4().hex)
        os.environ["JEV_METRICS_FILE"] = str(directory / "metrics.json")
    try:
        run(bounded_lines(sys.stdin))
        return 0
    except (KeyboardInterrupt, SystemExit):
        print("jev agent error: cancelled", file=sys.stderr)
        return 130
    except Exception as exc:
        code = exc.code if isinstance(exc, AgentFault) else "local_error"
        print("jev agent error: " + code, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
