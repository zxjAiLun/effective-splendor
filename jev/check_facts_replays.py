"""Offline: round-trip every certified legal action at journalled replay roots.

The Rust probe verifies/rebuilds the replay. Test-owned Choice answers direct the
new policy to each action; no API, heuristic helper, gameplay or League writes.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess

import agent
from runtime import encode
from transport import MAX_REQUEST_BYTES


def check(root: Path, binary: Path) -> dict:
    catalog = agent.load_catalog()
    totals, stages, modes, coverage, max_bytes, hashes = Counter(), Counter(), Counter(), Counter(), {}, {}
    for journal in sorted(root.glob("*/metrics.jsonl")):
        replay = journal.with_name("replay.json")
        if not replay.is_file():
            continue
        hashes[str(replay.relative_to(root))] = hashlib.sha256(replay.read_bytes()).hexdigest()
        hashes[str(journal.relative_to(root))] = hashlib.sha256(journal.read_bytes()).hexdigest()
        starts = [e for line in journal.read_text(encoding="utf-8").splitlines()
                  if (e := json.loads(line)).get("event") == "decision_start"]
        totals["replays"] += 1
        print(f"checking {journal.parent.name}: {len(starts)} roots", flush=True)
        for start in starts:
            result = subprocess.run([str(binary), "probe-legal", "--source-replay", str(replay),
                                     "--branch-ply", str(start["ply"]), "--emit-observation"],
                                    capture_output=True, text=True, check=True, timeout=30)
            probe = json.loads(result.stdout)
            obs, legal = probe["observation"], probe["legal_actions"]
            assert probe["observation_hash"] == start["observation_hash"]
            assert obs["viewer"] == start["actor"]
            assert len(legal) == start["legal_count"]
            totals["roots"] += 1
            for expected_index, expected in enumerate(legal):
                mode = agent.action_mode(expected)
                modes[mode] += 1
                coverage[expected["type"]] += 1
                coverage["actions_with_returns"] += int(any(expected.get("return", {}).values()))

                def fake(payload):
                    stage, q = next(iter(payload["questions"].items()))
                    stages[stage] += 1
                    text = encode(payload)
                    size = len(text.encode("utf-8"))
                    max_bytes[stage] = max(max_bytes.get(stage, 0), size)
                    assert size <= MAX_REQUEST_BYTES
                    for banned in ("heuristic", "category_base", "advisory_term", "best_move_example", "referee", "seed"):
                        assert banned not in text.lower(), banned
                    criteria = q["criteria"]
                    answer = {"type": "choice"}
                    if stage == "family":
                        answer["choice"] = mode
                    elif stage == "colors":
                        chosen = [c for c in agent.COLORS if expected["take"].get(c, 0)]
                        answer.update(choice=chosen[0], probabilities={c: 1 / len(chosen) if c in chosen else 0 for c in agent.COLORS})
                    else:
                        value = ({"return": agent.sparse_gems(expected.get("return", {}))} if stage == "return"
                                 else agent.target_fact(expected, obs))
                        answer["choice"] = next(k for k, v in criteria.items() if v == value)
                    assert answer["choice"] in criteria
                    return {"model": agent.MODEL, "answers": {stage: answer}, "usage": {"input_tokens": 0, "output_tokens": 0}}

                trace = []
                actual, _, _, _ = agent.pick(obs, legal, catalog, fake, lambda **kw: trace.append(kw))
                assert actual == expected
                assert trace[0]["selected_index"] == expected_index
                assert trace[0]["cap_removed"] == trace[0]["noops_removed"] == 0
                totals["exact_action_roundtrips"] += 1
    assert totals["roots"] > 0
    return {"scope": "offline exhaustive legal-action mapping; test-owned responses, zero inference",
            "policy_id": agent.POLICY_ID, "counts": dict(totals), "modes": dict(modes), "coverage": dict(coverage),
            "mock_stage_counts": dict(stages), "max_request_bytes_by_stage": max_bytes,
            "input_sha256": hashes, "agent_sha256": hashlib.sha256(Path(agent.__file__).read_bytes()).hexdigest(),
            "checker_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("refuse to overwrite evidence")
    result = check(args.root.resolve(), args.binary.resolve())
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "input_sha256"}))


if __name__ == "__main__":
    main()
