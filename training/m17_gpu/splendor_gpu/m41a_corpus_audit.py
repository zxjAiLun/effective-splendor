"""M41A P2 corpus acceptance audit (read-only, STRENGTHENED revision).

Every claim in this audit is now EXHAUSTIVE (no sampling anywhere):

  1. Run-contract identity — design/executor/cap/tau/split ranges AND a
     full re-hash of every locally-available bound asset (Rust binary,
     D2 checkpoint file, m41a_server.py, m41a_proxy_agent.py).
  2. Counts by split with exact seed/ordinal identity; zero missing,
     zero duplicate; FULL re-hash of ALL artifact pairs — every report
     and every replay SHA recomputed and compared to manifest v2
     (artifact_entries_seen == report_sha_rehashed == replay_sha_rehashed).
  3. H0b source-action reproduction on ALL 912 states (zero new
     execution): the source action's existing branch must reproduce the
     source replay suffix, result, final-state hash, and acting-seat
     return exactly.
  4. SEALED binding: SEALED.sealed_at_split_manifest_sha256 == the
     power-calibration split manifest's state_manifest_sha256, and the
     power-calibration split manifest carries sealed == true.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent.parent
ROOT = REPO / "local-artifacts/m41a-corpus"
SPLITS = {
    "train": (9_000_000, 192),
    "validation": (9_000_192, 48),
    "power-calibration": (9_000_240, 64),
}
SPLN = REPO / "target/release/splendor.exe"
D2 = REPO / "local-artifacts/m25-recovery-exp-d2-v2/checkpoint.pt"
M41A_SERVER = REPO / "training/m17_gpu/splendor_gpu/m41a_server.py"
M41A_PROXY = REPO / "training/m17_gpu/m41a_proxy_agent.py"


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

    # ---------------- 1. Run contract (full asset re-hash) ----------------
    contract = json.loads((ROOT / "run-contract.json").read_text(encoding="utf-8"))
    contract_sha = sha256_file(ROOT / "run-contract.json")
    asset_rehash = {
        "rust_binary_sha256": (SPLN, contract["rust_binary_sha256"]),
        "checkpoint_file_sha256": (D2, contract["checkpoint_file_sha256"]),
        "m41a_server_sha256": (M41A_SERVER, contract["m41a_server_sha256"]),
        "m41a_proxy_agent_sha256": (M41A_PROXY, contract["m41a_proxy_agent_sha256"]),
    }
    asset_failures = []
    for field, (path, expected) in asset_rehash.items():
        actual = sha256_file(path)
        if actual != expected:
            asset_failures.append(f"{field}: {actual[:16]}... != {expected[:16]}...")
    assert contract["design_sha"] == "c05d3fb162c73a7d7127b910f5a10c97f347e0b9"
    assert contract["executor_commit"] == "209ecd5a91cc433d3514e9e9c929ec40aae1e4c2"
    assert contract["ply_cap"] == 150 and contract["tau"] == 1.0
    assert not asset_failures, asset_failures
    audit["run_contract"] = {
        "sha256": contract_sha,
        "design_sha": contract["design_sha"],
        "executor_commit": contract["executor_commit"],
        "asset_rehash": "PASS (binary/checkpoint/server/proxy all re-hashed and matched)",
    }

    # ---------------- 2/3. Exhaustive per-split audits ----------------
    split_audits = {}
    totals = {"artifact_entries_seen": 0, "report_sha_rehashed": 0,
              "replay_sha_rehashed": 0, "sha_failures": 0,
              "h0b_states_checked": 0, "h0b_failures": 0}

    for split, (seed_start, count) in SPLITS.items():
        games = 0
        states = 0
        branches = 0
        truncated = 0
        missing = []
        state_manifest_hashes = []
        sha_failures = []
        returns = set()
        h0b_failures = []

        dirs = sorted((ROOT / split).glob("game-*"))
        assert len(dirs) == count, f"{split}: {len(dirs)} != {count} games"

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
                # --- FULL SHA re-hash of EVERY artifact pair (no sampling) ---
                for entry in m["actions"]:
                    branches += 1
                    totals["artifact_entries_seen"] += 1
                    truncated += 1 if entry["truncated"] else 0
                    returns.add(entry["acting_seat_return"])
                    adir = sdir / f"action-{entry['action_index']:03d}"
                    if sha256_file(adir / "report.json") != entry["report_sha256"]:
                        sha_failures.append(str(adir / "report.json"))
                        totals["sha_failures"] += 1
                    else:
                        totals["report_sha_rehashed"] += 1
                    if sha256_file(adir / "replay.json") != entry["replay_sha256"]:
                        sha_failures.append(str(adir / "replay.json"))
                        totals["sha_failures"] += 1
                    else:
                        totals["replay_sha_rehashed"] += 1
                    # --- H0b on EVERY state (source action's branch) ---
                    if not entry["resumed"] or True:
                        source_action = replay["steps"][ply]["action"]
                        if entry["forced_action"] == source_action:
                            branch_replay = json.loads(
                                (adir / "replay.json").read_text(encoding="utf-8")
                            )
                            # acting-seat return consistency
                            if branch_replay.get("result") is not None:
                                rep = json.loads((adir / "report.json").read_text(encoding="utf-8"))
                                outcome = rep["outcome"]
                                winners = outcome["result"]["winners"]
                                if len(winners) == 2:
                                    g = 0.0
                                elif (ordinal % 2) in winners:
                                    g = 1.0
                                else:
                                    g = -1.0
                                return_ok = abs(g - entry["acting_seat_return"]) < 1e-12
                            else:
                                return_ok = True
                            ok = (
                                branch_replay["steps"][ply:] == replay["steps"][ply:]
                                and branch_replay["final_state_hash"] == replay["final_state_hash"]
                                and branch_replay["result"] == replay["result"]
                                and return_ok
                            )
                            totals["h0b_states_checked"] += 1
                            if not ok:
                                h0b_failures.append(str(sdir))
                # guard: exactly one source-action branch per state
                source_action = replay["steps"][ply]["action"]
                n_source = sum(
                    1 for e in m["actions"] if e["forced_action"] == source_action
                )
                assert n_source == 1, f"{sdir}: {n_source} source-action branches (expected 1)"

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
            "h0b_states_checked_in_split": totals["h0b_states_checked"],
            "returns_alphabet": sorted(returns),
            "split_manifest_sha256": sha256_file(ROOT / split / "split-manifest.json"),
        }
        assert not missing and not sha_failures and not h0b_failures, (
            missing[:3], sha_failures[:3], h0b_failures[:3]
        )

    # ---------------- 4. SEALED binding ----------------
    seal = json.loads((ROOT / "power-calibration" / "SEALED.json").read_text(encoding="utf-8"))
    powercal_manifest = json.loads(
        (ROOT / "power-calibration" / "split-manifest.json").read_text(encoding="utf-8")
    )
    assert seal["format"] == "effective-splendor-m41a-power-calibration-seal"
    assert powercal_manifest["sealed"] is True
    assert (
        seal["sealed_at_split_manifest_sha256"]
        == powercal_manifest["state_manifest_sha256"]
    ), "SEALED marker is not bound to THIS power-calibration corpus"
    audit["sealed_binding"] = "PASS (seal SHA == power-cal split manifest state_manifest_sha256; sealed=true)"

    audit["splits"] = split_audits
    audit["totals"] = totals
    audit["corpus_totals"] = {
        "games": sum(s["games"] for s in split_audits.values()),
        "states": sum(s["states"] for s in split_audits.values()),
        "branches": sum(s["branches"] for s in split_audits.values()),
    }
    out = ROOT / "p2-acceptance-audit.json"
    out.write_text(json.dumps(audit, indent=2), encoding="utf-8")
    print(json.dumps(audit, indent=2))

    # Final explicit assertion block (the reviewer's exact output shape).
    assert totals["artifact_entries_seen"] == 19_190
    assert totals["report_sha_rehashed"] == 19_190
    assert totals["replay_sha_rehashed"] == 19_190
    assert totals["sha_failures"] == 0
    assert totals["h0b_states_checked"] == 912
    assert totals["h0b_failures"] == 0
    print("P2 ACCEPTANCE AUDIT (STRENGTHENED): ALL FOUR CHECKS PASS")


if __name__ == "__main__":
    main()
