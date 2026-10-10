"""One-shot, player-view-only frozen teacher query. Never executes its suggestion."""
from __future__ import annotations

import hashlib
import json
import subprocess


def query_teacher(program, args, context, report, query_id, timeout=10):
    view = context["player_view"]
    actor = int(view["actor"])
    observation = view["observation"]
    legal = view["legal_actions"]
    assert legal and actor in (0, 1)
    # Referee-only metadata remains outside the wire payload.
    def reject_hidden_keys(value):
        if isinstance(value, dict):
            assert not {"seed", "decks", "full_state_hash"}.intersection(value)
            for child in value.values():
                reject_hidden_keys(child)
        elif isinstance(value, list):
            for child in value:
                reject_hidden_keys(child)
    reject_hidden_keys(observation)
    reject_hidden_keys(view["visible_history"])
    game_id = "m50-query-" + hashlib.sha256(str(query_id).encode()).hexdigest()[:24]
    protocol = report["protocol_version"]
    sequence = 0
    messages = []
    def send(kind, scoped=False, **fields):
        nonlocal sequence
        sequence += 1
        message = {"type": kind, "protocol_version": protocol, "game_id": game_id, "server_seq": sequence}
        if scoped:
            message["recipient_player_id"] = actor
        message.update(fields)
        messages.append(message)
    send("hello", engine_version=report["engine_version"], ruleset=report["ruleset"],
         catalog_version="0.1.0", ruleset_fingerprint=report["ruleset_fingerprint"])
    send("game_start", True, player_count=2, seed_commitment=report["seed_commitment"])
    for event in view["visible_history"]:
        send("event", True, event=event)
    send("observation", True, observation_hash=view["observation_hash"], observation=observation)
    send("request_action", True, observation_hash=view["observation_hash"], request_id=1,
         deadline_ms=60000, legal_actions=legal)
    wire = "".join(json.dumps(message, ensure_ascii=False) + "\n" for message in messages)
    process = subprocess.run([str(program), *args], input=wire, capture_output=True, text=True,
                             encoding="utf-8", timeout=timeout)
    replies = [json.loads(line) for line in process.stdout.splitlines() if line.strip()]
    assert len(replies) == 2 and replies[0]["type"] == "hello" and replies[1]["type"] == "action", process.stderr
    for reply in replies:
        assert reply["game_id"] == game_id and reply["protocol_version"] == protocol
    response = replies[1]
    assert response["request_id"] == 1 and response["action"] in legal
    assert process.returncode in (0, 1), f"unexpected query termination {process.returncode}"
    return {"policy_target_idx": legal.index(response["action"]), "action": response["action"],
            "returncode": process.returncode, "stderr": process.stderr,
            "termination": "query_input_closed_after_one_request_not_a_completed_game",
            "rng_mode": "fresh_process_fixed_cli_seed", "wire_sha256": hashlib.sha256(wire.encode()).hexdigest()}
