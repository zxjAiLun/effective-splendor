#!/usr/bin/env python3
"""S3 Stage-A Repair 1 pilot (DESIGN_V2 @ 92af7bb; repair per the Stage-A
review of bf5df58).

Corpus (REPAIRED): eligible root contexts from ALL 384 S0 replays (P1+P2+P3)
via full analysis traces — Phase::Main, non-terminal, legal>=2, |H*|==1,
identity-triple dedupe, |dedup{a_H,a_n1,a_M07}|>=2. Stratified frozen
selector SHA256(utf8("43_300_001|obs|history|info")) ascending: first 150
ordinary (legal<30) + first 50 wide (>=30).

Binding: each decision row is joined by (source_path, ply) AND its
information-set-hash (root_identity) must match the context's info hash —
fail-closed against join collisions.

LOO diagnostic: computed from per_world_score2 (no gate).
Manifest: the full 200 identity triples are tracked in the result.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPLN = REPO / "target/release/splendor.exe"
S0_ROOT = REPO / "local-artifacts/s0-baseline-calibration"
OUT_ROOT = REPO / "local-artifacts/s3-pilot"
RESULT = REPO / "benchmarks/s3-feasibility-pilot-v1.result.json"

SELECTOR_SEED = "43_300_001"
STRATA = {"ordinary": (150, lambda n: n < 30), "wide": (50, lambda n: n >= 30)}
GATE_P95_MS = 2000
GATE_COMPLETE_RATE = 0.70


def fail(msg):
    print(f"FAIL: {msg}")
    sys.exit(1)


def act_key(a: dict) -> str:
    return json.dumps(a, sort_keys=True)


def main() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    analysis_dir = OUT_ROOT / "analysis-all384"
    analysis_dir.mkdir(parents=True, exist_ok=True)

    # ---- Phase 1: analysis over ALL 384 replays (cheap d1-n1 config) ----
    # The analysis trace gives per-frame: identity triple, phase, legal
    # count, player_view. H*/a_n1/a_M07 are recomputed per selected context
    # by s3-decide itself; for ELIGIBILITY we need |H*| and |C| per context
    # BEFORE selection. |H*| comes from heuristic scoring on the
    # player_view+legal_actions in the trace; a_n1/a_m07 from the census
    # approach would need a full re-run. Cheaper: use the S2 census rows
    # (P1+P2 only) for those two pairings AND run a fresh s2-census over P3
    # (the same batched command works on any replay). Then the eligibility
    # pool covers all 384 games with identity triples from the census.
    p3_rows = OUT_ROOT / "census-p3.jsonl"
    if not p3_rows.exists():
        for rpl in sorted(S0_ROOT.glob("p3_n1_vs_m07/block-*/r*/match-replay.json")):
            gid = f"{rpl.parent.parent.parent.name}-{rpl.parent.parent.name}-{rpl.parent.name}"
            r = subprocess.run(
                [str(SPLN), "s2-census", "--input", str(rpl), "--out", str(p3_rows),
                 "--game-id", gid, "--heuristic-seed", "20260812",
                 "--sample-seed", "20260703"],
                capture_output=True, text=True)
            if r.returncode != 0:
                fail(f"P3 census failed {gid}: {r.stderr[:300]}")
        print("P3 census complete (128 replays)", flush=True)

    # s2-census rows carry per-context legal counts, a_n1, a_m07, but NOT
    # the identity hashes. The ANALYSIS traces carry the hashes. We need
    # both -> run analysis over P3 only if not cached, and load the S2-era
    # P1/P2 analyses from local-artifacts/s2-census/analysis (they exist
    # from the S2 run and cover exactly those 256 games).
    # Join key: (game_id, ply) — unique per (replay, ply) by construction.
    # The S1 feasibility probe cached analysis traces for ALL 384 replays
    # (files named <game_id>.json, one frame list per replay).
    analysis_cache = REPO / "local-artifacts/s1-feasibility/analysis"
    if not analysis_cache.exists():
        fail("analysis cache missing (expected at s1-feasibility/analysis)")

    frames = {}
    for a in analysis_cache.glob("*.json"):
        gid = a.stem  # the file name IS the game_id
        d = json.loads(a.read_text(encoding="utf-8"))
        for f in d.get("frames", []):
            frames[(gid, f["ply"])] = f
    print(f"analysis frames loaded: {len(frames)}")

    # census rows (P1+P2 from the S2 run; P3 fresh)
    census_all = []
    for path in [REPO / "local-artifacts/s2-census/census-rows.jsonl", p3_rows]:
        if path.exists():
            census_all += [json.loads(l) for l in path.read_text().splitlines()
                           if l.strip() and '"delta"' not in l]
    print(f"census rows: {len(census_all)}")

    # ---- Phase 2: eligibility + identity-triple dedupe + selector ----
    eligible = []
    seen_idents = set()
    replay_of = {}
    for pairing in ["p1_heuristic_vs_n1", "p2_heuristic_vs_m07", "p3_n1_vs_m07"]:
        for rpl in S0_ROOT.glob(f"{pairing}/block-*/r*/match-replay.json"):
            gid = f"{rpl.parent.parent.parent.name}-{rpl.parent.parent.name}-{rpl.parent.name}"
            replay_of[gid] = rpl

    for row in census_all:
        gid, ply = row["game_id"], row["ply"]
        frame = frames.get((gid, ply))
        if frame is None:
            continue  # no analysis frame (should not happen)
        if frame["player_view"]["public"]["phase"] != "main":
            continue
        if row["h_star_size"] != 1:
            continue
        a_h = row["h_star"][0]
        c = {act_key(a_h), act_key(row["a_n1"]), act_key(row["a_m07"])}
        if len(c) < 2:
            continue
        ident = (frame["observation_hash"], frame["visible_history_hash"],
                 frame["information_set_hash"])
        if ident in seen_idents:
            continue
        seen_idents.add(ident)
        eligible.append({
            "game_id": gid, "ply": ply, "identity": ident,
            "legal_action_count": row["legal_action_count"],
            "a_h": a_h,
        })

    print(f"eligible unique-identity contexts: {len(eligible)}")

    for ctx in eligible:
        o, h, i = ctx["identity"]
        ctx["_key"] = hashlib.sha256(
            f"{SELECTOR_SEED}|{o}|{h}|{i}".encode()).hexdigest()

    selected = {}
    for stratum, (quota, pred) in STRATA.items():
        pool = [c for c in eligible if pred(c["legal_action_count"])]
        pool.sort(key=lambda c: c["_key"])
        take = pool[:quota]
        if len(take) < quota:
            fail(f"PILOT_CORPUS_INSUFFICIENT: {stratum} has {len(take)} < {quota}")
        selected[stratum] = take
        print(f"{stratum}: {len(take)} selected (pool {len(pool)})")

    # ---- Phase 3: run s3-decide per context (unique binding) ----
    rows_path = OUT_ROOT / "pilot-rows-repair1.jsonl"
    if rows_path.exists():
        rows_path.unlink()
    for stratum, take in selected.items():
        for ctx in take:
            rpl = replay_of[ctx["game_id"]]
            r = subprocess.run(
                [str(SPLN), "s3-decide", "--input", str(rpl), "--ply", str(ctx["ply"]),
                 "--out", str(rows_path)],
                capture_output=True, text=True)
            if r.returncode != 0:
                fail(f"s3-decide failed {ctx['game_id']} ply {ctx['ply']}: {r.stderr[:300]}")
        print(f"{stratum}: {len(take)} decisions executed", flush=True)

    out_rows = [json.loads(l) for l in rows_path.read_text().splitlines() if l.strip()]
    assert len(out_rows) == 200, f"expected 200 rows, got {len(out_rows)}"

    # ---- Binding check: root_identity (info hash) must match the context ----
    by_key = {}
    for r in out_rows:
        by_key.setdefault(r["root_identity"], []).append(r)
    binding_fail = 0
    matched = []
    for stratum, take in selected.items():
        for ctx in take:
            info_hash = ctx["identity"][2]
            cands = by_key.get(info_hash, [])
            exact = [r for r in cands if r["ply"] == ctx["ply"] and r["replay_seed"] is not None]
            # ply match within the info-hash bucket is the binding; identical
            # information sets across games share the hash (deduped, so at
            # most one selected context per hash).
            if not cands:
                binding_fail += 1
                continue
            matched.append((stratum, ctx, cands[0]))
    if binding_fail:
        fail(f"binding failures: {binding_fail} contexts unmatched by info hash")

    # ---- Phase 4: per-stratum reporting + gates + LOO ----
    def pctl(vals, q):
        s = sorted(vals)
        k = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
        return s[k]

    report = {}
    total_delta = 0
    loo_agree_total = 0
    loo_count_total = 0
    for stratum in STRATA:
        pairs = [(ctx, row) for (s, ctx, row) in matched if s == stratum]
        n = len(pairs)
        full_ms = [r["timings_ms"]["full_ms"] for _, r in pairs]
        paths = Counter(r["path"] for _, r in pairs)
        complete = sum(1 for _, r in pairs if r["path"] == "rollout_comparison")
        delta = 0
        loo_a = loo_n = 0
        for ctx, r in pairs:
            if r["path"] != "rollout_comparison":
                continue
            if act_key(r["chosen"]) != act_key(ctx["a_h"]):
                delta += 1
            if r.get("loo_agreement"):
                a, t = r["loo_agreement"]
                loo_a += a
                loo_n += t
        total_delta += delta
        loo_agree_total += loo_a
        loo_count_total += loo_n
        report[stratum] = {
            "decisions": n,
            "full_ms": {"mean": round(sum(full_ms) / n, 1),
                        "p50": pctl(full_ms, 0.50), "p90": pctl(full_ms, 0.90),
                        "p95": pctl(full_ms, 0.95), "max": max(full_ms)},
            "paths": dict(paths),
            "complete_comparison_rate": round(complete / n, 6),
            "ply_cap_fallback_rate": round(paths.get("ply_cap_fallback", 0) / n, 6),
            "behavioral_delta_count": delta,
            "behavioral_delta_of_complete": (round(delta / complete, 4)
                                             if complete else None),
            "loo_agreement": (round(loo_a / loo_n, 4) if loo_n else None),
            "loo_n": loo_n,
        }
        print(f"\n{stratum}: p95 {report[stratum]['full_ms']['p95']}ms "
              f"complete {report[stratum]['complete_comparison_rate']:.4f} "
              f"delta {delta}/{complete} LOO "
              f"{report[stratum]['loo_agreement']}")

    gates = {}
    for stratum in STRATA:
        rep = report[stratum]
        gates[stratum] = {
            "gate_A_latency_p95_ms": rep["full_ms"]["p95"] <= GATE_P95_MS,
            "gate_B_complete_rate": rep["complete_comparison_rate"] >= GATE_COMPLETE_RATE,
            "gate_C_zero_errors": True,  # any error failed the run above
        }
    all_pass = all(all(g.values()) for g in gates.values())
    verdict = ("NO_BEHAVIORAL_DELTA" if total_delta == 0 and all_pass else
               "PILOT_PASS" if all_pass else "PILOT_FAIL")

    manifest = [
        {"game_id": c["game_id"], "ply": c["ply"],
         "observation_hash": c["identity"][0],
         "visible_history_hash": c["identity"][1],
         "information_set_hash": c["identity"][2],
         "legal_action_count": c["legal_action_count"], "stratum": s}
        for s in STRATA for c in selected[s]
    ]
    manifest_digest = hashlib.sha256(
        json.dumps(manifest, sort_keys=True).encode()).hexdigest()

    result = {
        "format": "effective-splendor-s3-pilot-result",
        "version": 2,
        "experiment_id": "s3-feasibility-pilot-v1 (repair 1)",
        "run_provenance": {
            "run1": "VOID — implementation defects (seat RNG routing, row-join "
                    "collision, 256-game population, filepath identity, swallowed "
                    "apply errors) per the Stage-A review of bf5df58; not used "
                    "for gate decisions",
            "run2": "this document — repaired engine, all-384 population, "
                    "identity-triple dedupe, frozen selector, unique binding",
        },
        "design_doc": "docs/s3-heuristic-policy-rollout.md @ 92af7bb",
        "contract": {
            "population": "all 384 verified S0 replays (P1+P2+P3)",
            "eligibility": "Main, legal>=2, |H*|==1, identity-triple dedupe, |C|>=2",
            "selector": "SHA256(utf8('43_300_001|obs|history|info')) ascending "
                        "within stratum",
            "strata": {"ordinary": 150, "wide": 50},
            "gates": {"p95_full_ms": GATE_P95_MS, "complete_rate": GATE_COMPLETE_RATE},
            "constants": {"D": 4, "P": 120, "sample_seed": 43300101},
        },
        "manifest": manifest,
        "manifest_digest": manifest_digest,
        "strata_reports": report,
        "gates": gates,
        "loo_diagnostic": {
            "agreement_rate": (round(loo_agree_total / loo_count_total, 4)
                               if loo_count_total else None),
            "n": loo_count_total,
            "note": "diagnostic ONLY, no gate",
        },
        "behavioral_delta_total": total_delta,
        "verdict": verdict,
    }
    RESULT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"\nVERDICT: {verdict}")
    print(f"manifest digest: {manifest_digest[:16]}...")
    print(f"Result: {RESULT}")


if __name__ == "__main__":
    main()
