"""Facts-only TypeSafe Jev agent: legal modes, color probabilities, exact actions.

Stdio protocol v0.5. No heuristic evaluation, referee input or paid fallback.
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Callable

from runtime import AGENT_VERSION, POLICY_ID, AgentFault, Deadline, Session
from transport import API_URL, credential, evaluate

HERE = Path(__file__).resolve().parent
MODEL = os.environ.get("JEV_MODEL", "jev-1.13.0")
EXPECTED_MODEL = os.environ.get("JEV_EXPECTED_MODEL", "jev-1.13.0")
PROTOCOL = "0.5"
COLORS = ("white", "blue", "green", "red", "black")
MAX_CHOICES = 255  # Provider limit; reject, never score/prune candidates.
MODE_RULES = {
    "take_distinct": "Take one token of each of up to three different available colors; fewer only if fewer colors remain.",
    "take_double": "Take two tokens of one color whose bank stack contains at least four tokens.",
    "reserve": "Reserve a visible market card or a blind tier-deck card; gain one gold if available. No immediate VP or bonus.",
    "buy": "Buy one affordable development card from the market or your own reserved cards, gaining its VP and permanent color bonus.",
    "choose_noble": "Choose one of the eligible nobles for 3 VP; this is not an extra main turn.",
    "pass": "Pass when the engine permits no other action.",
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


def sparse_gems(value: dict) -> dict:
    return {c: n for c, n in gems(value).items() if n}


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
    """Only rule facts, public state and the acting seat's own-private reserves."""
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


def action_mode(action: dict) -> str:
    kind = action["type"]
    if kind == "take_tokens":
        take = gems(action["take"])
        amounts = [take[c] for c in COLORS if take[c]]
        if not take["gold"]:
            if amounts == [2]:
                return "take_double"
            if 1 <= len(amounts) <= 3 and all(n == 1 for n in amounts):
                return "take_distinct"
        raise AgentFault("invalid certified take shape", "invalid_legal_actions")
    for mode, kinds in (("buy", ("buy_market", "buy_reserved")),
                        ("reserve", ("reserve_market", "reserve_deck")),
                        ("choose_noble", ("choose_noble",)), ("pass", ("pass",))):
        if kind in kinds:
            return mode
    raise AgentFault("unknown legal action type", "invalid_legal_actions")


def action_family(action: dict) -> str:
    mode = action_mode(action)
    return "take_tokens" if mode.startswith("take_") else mode


def target_fact(action: dict, obs: dict) -> dict:
    """Identity of a target. Card costs/VP/bonuses are in the shared state."""
    kind = action["type"]
    result = {"type": kind}
    if kind in ("buy_market", "reserve_market"):
        tier = ("One", "Two", "Three").index(action["tier"])
        result.update(tier=action["tier"], slot=action["slot"], card_id=obs["public"]["market"][tier][action["slot"]])
    elif kind == "buy_reserved":
        result.update(slot=action["slot"], card_id=obs["private"]["reserved"][action["slot"]]["card"])
    elif kind == "reserve_deck":
        result.update(tier=action["tier"], unknown_card=True)
    elif kind == "choose_noble":
        result["noble_id"] = action["noble"]
    return result


def question(state: dict, stage: str, instructions: str, criteria: dict) -> dict:
    if not 1 <= len(criteria) <= MAX_CHOICES:
        raise AgentFault("choice count outside provider limit", "choice_count")
    return {"state": state, "model": MODEL,
            "questions": {stage: {"type": "choice", "instructions": instructions, "criteria": criteria}}}


def _choice(response: dict, stage: str, allowed: set[str]) -> tuple[str, dict]:
    try:
        answer = response["answers"][stage]
        selected = answer["choice"]
        if answer["type"] != "choice" or not isinstance(selected, str) or selected not in allowed:
            raise AgentFault("TypeSafe returned non-candidate Choice", "invalid_choice")
        usage = response.get("usage", {})
        if not isinstance(usage, dict):
            raise AgentFault("TypeSafe usage malformed", "invalid_choice")
        return selected, usage
    except (KeyError, TypeError, IndexError, ValueError) as exc:
        raise AgentFault("TypeSafe Choice response malformed", "invalid_choice") from exc


def color_probabilities(response: dict) -> dict:
    _choice(response, "colors", set(COLORS))
    values = response["answers"]["colors"].get("probabilities")
    if (not isinstance(values, dict) or set(values) != set(COLORS)
            or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in values.values())
            or not math.isclose(sum(values.values()), 1.0, abs_tol=1e-3, rel_tol=0)):
        raise AgentFault("invalid five-color probability vector", "invalid_probabilities")
    return {c: values[c] for c in COLORS}


def pick(obs: dict, legal: list[dict], catalog: dict, call: Callable[[dict], dict] = evaluate,
         trace=None) -> tuple[dict, dict | None, int, int]:
    if not legal:
        raise AgentFault("empty legal actions", "invalid_legal_actions")
    groups = {}
    for i, action in enumerate(legal):
        groups.setdefault(action_mode(action), []).append(i)
    modes = {mode: groups[mode] for mode in MODE_RULES if mode in groups}
    state = public_state(obs, catalog)
    usages, path = [], []

    def choose(stage, instructions, criteria, *, context=None):
        # A forced stage has no inference result; the path records the skip.
        if len(criteria) == 1:
            selected = next(iter(criteria))
            path.append({"stage": stage, "selected_id": selected, "forced": True})
            return selected
        payload = question(state if context is None else dict(state, action_in_progress=context),
                           stage, instructions, criteria)
        reply = call(payload)
        selected, usage = _choice(reply, stage, set(criteria))
        usages.append(usage)
        path.append({"stage": stage, "selected_id": selected, "forced": False})
        return selected

    mode = choose("family", "Choose the legal action type most likely to help you win this game of Splendor. "
                  "Use the structured game facts and rules; only listed types are legal.",
                  {m: {"rule": MODE_RULES[m]} for m in modes})
    scoped = modes[mode]
    context = {"mode": mode}
    if mode.startswith("take_"):
        bundles = {}
        for i in scoped:
            key = tuple(gems(legal[i]["take"])[c] for c in COLORS)
            bundles.setdefault(key, []).append(i)
        eligible = [c for j, c in enumerate(COLORS) if any(v[j] for v in bundles)]
        if len(bundles) == 1:
            bundle = next(iter(bundles))
            path.append({"stage": "colors", "forced": True, "take": sparse_gems(legal[scoped[0]]["take"])})
        else:
            double = mode == "take_double"
            sizes = {sum(v) for v in bundles}
            if len(sizes) != 1:
                raise AgentFault("inconsistent certified take counts", "invalid_legal_actions")
            k = 1 if double else next(iter(sizes))
            payload = question(dict(state, action_in_progress={"mode": mode, "eligible_colors": eligible}),
                "colors", "Which gem color is most useful for this take to help you win? " +
                ("The program takes TWO tokens of the highest-probability eligible color. " if double else
                 f"The program takes ONE token of each of the {k} highest-probability eligible colors. ") +
                "All five colors are listed for a full distribution; ineligible colors cannot be taken. "
                "Equal probabilities use white, blue, green, red, black order.",
                {c: {"color": c, "eligible": c in eligible, "bank_count": state["bank"][c]} for c in COLORS})
            reply = call(payload)
            probs = color_probabilities(reply)
            usages.append(reply.get("usage", {}))
            ranked = sorted(eligible, key=lambda c: (-probs[c], COLORS.index(c)))
            chosen_colors = ranked[:k]
            bundle = tuple((2 if double else 1) if c in chosen_colors else 0 for c in COLORS)
            path.append({"stage": "colors", "forced": False, "probabilities": probs,
                         "eligible_colors": eligible, "ranked_eligible_colors": ranked,
                         "take": {c: bundle[j] for j, c in enumerate(COLORS) if bundle[j]},
                         "mapping": "eligible_argmax_double" if double else "eligible_top_k_distinct"})
        if bundle not in bundles:
            raise AgentFault("color selection has no certified legal action", "unmappable_colors")
        offered = bundles[bundle]
        context["take"] = sparse_gems(legal[offered[0]]["take"])
    else:
        targets = {}
        for i in scoped:
            fact = target_fact(legal[i], obs)
            key = json.dumps(fact, sort_keys=True)
            if key not in targets:
                targets[key] = {"fact": fact, "indices": []}
            targets[key]["indices"].append(i)
        entries = list(targets.values())
        stage = "noble" if mode == "choose_noble" else "target"
        key = choose(stage, "Choose one listed legal target to help you win. "
                     "Card details are in market / own_reserved, and noble details are in nobles. "
                     "Reserving grants no VP or permanent bonus now; blind card identity is unknown.",
                     {f"t{j}": e["fact"] for j, e in enumerate(entries)})
        chosen_target = entries[int(key[1:])]
        offered = chosen_target["indices"]
        context["target"] = chosen_target["fact"]

    returns = {}
    for i in offered:
        key = tuple(gems(legal[i].get("return", {})).values())
        # Exact duplicate actions are not distinct choices. Preserve first legal index.
        returns.setdefault(key, i)
    received = gems(context.get("take", {"gold": int(mode == "reserve" and state["bank"]["gold"] > 0)}))
    me = next(p for p in state["players"] if p["seat"] == state["viewer"])
    context.update(received_before_returns=sparse_gems(received),
                   tokens_before_returns={c: me["tokens"][c] + received[c] for c in received})
    indices = list(returns.values())
    return_choice = choose("return", "The main action/target is already selected in action_in_progress. "
                           "Choose which exact tokens to return to the bank, leaving at most 10. "
                           "Choose the resulting holdings most likely to help you win. Only listed returns are legal.",
                           {f"r{j}": {"return": sparse_gems(legal[i].get("return", {}))} for j, i in enumerate(indices)},
                           context=context)
    selected_index = indices[int(return_choice[1:])]
    selected = legal[selected_index]
    if trace:
        trace(family=action_family(selected), decision_mode=mode, family_count=len(modes),
              noops_removed=0, routed_out=len(legal)-len(scoped), cap_removed=0,
              target_removed=len(scoped)-len(offered), offered_indices=offered,
              selected_index=selected_index, selected_action=selected, selection_path=path)
    combined = {key: sum(u.get(key, 0) for u in usages if type(u.get(key, 0)) is int)
                for key in ("input_tokens", "output_tokens")}
    return selected, combined if usages else None, len(offered), len(usages)


def send(message: dict) -> None:
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def run(lines, call=evaluate, *, session=None, clock=time.monotonic, sleeper=time.sleep) -> dict:
    if session is None:
        path = Path(os.environ["JEV_METRICS_FILE"]) if os.environ.get("JEV_METRICS_FILE") else None
        session = Session(MODEL, max_calls=int(os.environ.get("JEV_MAX_API_CALLS", "100")),
                          summary_path=path, clock=clock, sleeper=sleeper, expected_model=EXPECTED_MODEL)
    try:
        outcome = drive(lines, call, session)
    except BaseException as exc:
        cancelled = isinstance(exc, (KeyboardInterrupt, SystemExit))
        session.finish("cancelled" if cancelled else "failed",
                       "cancelled" if cancelled else exc.code if isinstance(exc, AgentFault) else "local_error")
        raise
    session.finish(outcome)
    return session.metrics


def drive(lines, call, session):
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

            def capture(payload):
                return session.ask(payload, deadline, call)

            def trace(**info):
                session.metrics["families_offered"] += info["family_count"]
                session.metrics["options_offered"] += len(info["offered_indices"])
                for name in ("noops_removed", "routed_out", "cap_removed", "target_removed"):
                    session.metrics[name] += info[name]
                    session.metrics["options_omitted"] += info[name]
                session.emit("decision_choice", **info)

            action, _, _, _ = pick(obs, legal, catalog, capture, trace)
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
