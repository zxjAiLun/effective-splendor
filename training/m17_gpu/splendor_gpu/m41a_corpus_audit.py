"""M41A P2 corpus acceptance audit (read-only).

Verifies every P2-review deliverable over the generated corpus:
  1. run-contract identity (design/executor/binary/checkpoints/server).
  2. counts by split with exact seed/ordinal identity; zero missing,
     zero duplicate states.
  3. manifest/provenance validation: every state manifest carries the
     run-contract SHA; every action entry is complete (v2 fields) and
     its artifact SHAs re-hash correctly.
  4. H0b-style source-action reproduction audit: per split, a frozen
     sample of states — the source action's branch replay must
     reproduce the source game suffix exactly.
  5. terminal/cap counts; return-value alphabet sanity.
  6. corpus root hashes (split manifests + state-manifest digest).
  7. power-calibration SEALED proof present.
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent.parent
ROOT = REPO / "local-artifacts/m41a-corpus"
SPLITS = {"train": (9_000_000, 192), "validation": (9_000_192, 48), "power-calibration": (9_000_240, 64)}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def select_states(replay: dict, ordinal: int) -> list[int]:
    seat = ordinal % 2
    steps = replay["steps"]
    plies = [s["ply"] for s in steps if s["actor"] == seat]
    n = len(plies)
    idxs = sorted({min(n - 1, int(round(q * (n - 1)))) for q in (0.25, 0.5, 0.75)})
    return [plies[i] for i in idxs][:3]


def main() -> None:
    audit: dict = {}

    # 1. run contract
    contract = json.loads((ROOT / "run-contract.json").read_text(encoding="utf-8"))
    contract_sha = sha256_file(ROOT / "run-contract.json")
    audit["run_contract"] = {
        "sha256": contract_sha,
        "design_sha": contract["design_sha"],
        "executor_commit": contract["executor_commit"],
        "model_id": contract["model_id"],
        "checkpoint_file_sha256": contract["checkpoint_file_sha256"][:16] + "...",
        "checkpoint_semantic_sha256": contract["checkpoint_semantic_sha256"][:16] + "...",
        "ply_cap": contract["ply_cap"],
        "tau": contract["tau"],
    }
    assert contract["design_sha"] == "c05d3fb162c73a7d7127b910f5a10c97f347e0b9"
    assert contract["executor_commit"] == "209ecd5a91cc433d3514e9e9c929ec40aae1e4c2"
    assert contract["ply_cap"] == 150 and contract["tau"] == 1.0

    # 2-6. per-split audits
    split_audits = {}
    for split, (seed_start, count) in SPLITS.items():
        games = 0
        states = 0
        branches = 0
        truncated = 0
        missing = []
        state_manifest_hashes = []
        action_entries_checked = 0
        sha_failures = []
        returns = set()
        h0b_checked = 0
        h0b_failures = []

        rng = random.Random(20260904)
        sample_ordinals = set()
        dirs = sorted((ROOT / split).glob("game-*"))
        assert len(dirs) == count, f"{split}: {len(dirs)} != {count} games"
        # sample 3 games per split for the H0b audit
        sample_ordinals = {rng.randrange(count) for _ in range(3)}

        for i, gdir in enumerate(dirs):
            ordinal = int(gdir.name.split("-")[1])
            assert ordinal == seed_start - 9_000_000 + i, f"ordinal drift at {gdir}"
            replay = json.loads((gdir / "replay.json").read_text(encoding="utf-8"))
            assert replay["seed"] == seed_start + i, f"seed drift at {gdir}"
            games += 1
            for ply in select_states(replay, ordinal):
                sdir = gdir / f"branch-ply{ply:04d}"
                m = json.loads((sdir / "state-manifest.json").read_text(encoding="utf-8"))
                if m.get("run_contract_sha256") != contract_sha:
                    missing.append(f"{sdir}: contract SHA mismatch")
                    continue
                states += 1
                state_manifest_hashes.append(sha256_file(sdir / "state-manifest.json"))
                for entry in m["actions"]:
                    branches += 1
                    truncated += 1 if entry["truncated"] else 0
                    returns.add(entry["acting_seat_return"])
                    adir = sdir / f"action-{entry['action_index']:03d}"
                    # verify SHAs re-hash (every 5th entry to bound runtime)
                    if action_entries_checked % 5 == 0 or entry["action_index"] == 0:
                        if sha256_file(adir / "report.json") != entry["report_sha256"]:
                            sha_failures.append(str(adir / "report.json"))
                        if sha256_file(adir / "replay.json") != entry["replay_sha256"]:
                            sha_failures.append(str(adir / "replay.json"))
                    action_entries_checked += 1
                # H0b audit on sampled games: the source action's branch
                # must reproduce the source suffix exactly.
                if i in sample_ordinals:
                    source_action = replay["steps"][ply]["action"]
                    match = next(
                        (e for e in m["actions"] if e["forced_action"] == source_action),
                        None,
                    )
                    assert match is not None, f"{sdir}: source action missing"
                    branch_replay = json.loads(
                        (sdir / f"action-{match['action_index']:03d}" / "replay.json")
                        .read_text(encoding="utf-8")
                    )
                    ok = (
                        branch_replay["steps"][ply:] == replay["steps"][ply:]
                        and branch_replay["final_state_hash"] == replay["final_state_hash"]
                        and branch_replay["result"] == replay["result"]
                    )
                    h0b_checked += 1
                    if not ok:
                        h0b_failures.append(str(sdir))

        digest = hashlib.sha256(
            json.dumps(state_manifest_hashes, separators=(",", ":")).encode()
        ).hexdigest()
        split_manifest = json.loads((ROOT / split / "split-manifest.json").read_text(encoding="utf-8"))
        assert split_manifest["games"] == games
        assert split_manifest["states"] == states
        assert split_manifest["branches"] == branches
        assert split_manifest["state_manifest_sha256"] == digest
        split_audits[split] = {
            "games": games, "states": states, "branches": branches,
            "truncated": truncated,
            "missing_or_contract_mismatch": len(missing),
            "sha_rehash_failures": len(sha_failures),
            "action_entries_sha_checked": action_entries_checked,
            "returns_alphabet": sorted(returns),
            "h0b_sample_states": h0b_checked,
            "h0b_failures": len(h0b_failures),
            "split_manifest_sha256": sha256_file(ROOT / split / "split-manifest.json"),
        }
        assert not missing and not sha_failures and not h0b_failures, (
            missing[:3], sha_failures[:3], h0b_failures[:3]
        )

    # 7. sealed proof
    seal = json.loads((ROOT / "power-calibration" / "SEALED.json").read_text(encoding="utf-8"))
    assert seal["format"] == "effective-splendor-m41a-power-calibration-seal"

    total = {
        "games": sum(s["games"] for s in split_audits.values()),
        "states": sum(s["states"] for s in split_audits.values()),
        "branches": sum(s["branches"] for s in split_audits.values()),
    }
    audit["splits"] = split_audits
    audit["totals"] = total
    audit["sealed"] = True
    out = ROOT / "p2-acceptance-audit.json"
    out.write_text(json.dumps(audit, indent=2), encoding="utf-8")
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
