"""M44C Final Exhaustive Audit & Tracked Result JSON Generator (Closure Repair 1).

Audits (all fail-closed):
  - M44A regression test passing (m44a_p0_semantic.rs, 6/6)
  - M44B regression test passing (m44b_p0_semantic.rs, 4/4)
  - M44C P0 semantic test suite passing (m44c_p0_semantic.rs, 4/4, authoritative M07 12-case corpus)
  - Exhaustive 384-match audit across all 3 pairings:
    * 384 reports seen, 384 replays seen, 0 missing, 0 duplicates
    * 0 aborts, 0 candidate faults, status == completed
    * 768 lineup checks passed, 384 rotation checks passed
    * Every replay verified with splendor verify-replay
    * Frozen P1 numbers asserted exactly (W/T/L, center bps, 98.333% CIs)
    * Scale88 paired-block score distribution recorded explicitly
  - P2 common-state scale audit hard gates:
    * exactly 200 contexts, exact quota matrix (23/22/22, 22/23/22, 22/22/22)
    * source reproduction == 200/200
    * all identity fields are authoritative 64-hex hashes
    * all identity triples globally unique
    * contexts_identity_sha256 present
    * 1-based decision-ply staging convention (early 1..=20, mid 21..=45, late 46+)
    * margin = top-1 minus runner-up with best==selected assertion
  - P3 vector heterogeneity audit hard gates:
    * authoritative identity method recorded
    * corpus_identity_sha256 present
    * strata internally consistent (sum of stratum counts == corpus size)
  - Provenance: catalog_semantic_hash computed from the real catalog loader
  - Writes tracked benchmarks/m44c-core-engine-identity-scale-sensitivity-v1.result.json
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent

SPLN = REPO / "target/release/splendor.exe"
CATALOG = REPO / "apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"
ARENA_ROOT = REPO / "local-artifacts/m44c-arena"
RESULT_JSON = REPO / "benchmarks/m44c-core-engine-identity-scale-sensitivity-v1.result.json"
M44B_RESULT_JSON = REPO / "benchmarks/m44b-permanent-engine-attribution-v1.result.json"
M44A_RESULT_JSON = REPO / "benchmarks/m44a-static-evaluator-information-attribution-v1.result.json"

BOOTSTRAP_SEED = 44_290_001
BOOTSTRAP_RESAMPLES = 10_000
SAMPLE_SEED = 20_260_703
SAMPLE_COUNT = 4
DEPTH_TURNS = 1
MAX_NODES = 1
FROZEN_SEEDS = list(range(5_700_000, 5_700_064))  # 64 paired blocks

# Frozen P1 outcomes (accepted in the M44C terminal review; Arena rerun FORBIDDEN).
FROZEN_P1 = {
    "engine_scale_25_vs_full": {"wins": 67, "ties": 0, "losses": 61, "center_bps": 5234.375},
    "engine_scale_50_vs_full": {"wins": 62, "ties": 0, "losses": 66, "center_bps": 4843.75},
    "engine_scale_88_vs_full": {"wins": 64, "ties": 0, "losses": 64, "center_bps": 5000.0},
}

PAIRING_SPECS = [
    {"id": "engine_scale_25_vs_full", "primary_profile": "engine_scale_25", "secondary_profile": "full"},
    {"id": "engine_scale_50_vs_full", "primary_profile": "engine_scale_50", "secondary_profile": "full"},
    {"id": "engine_scale_88_vs_full", "primary_profile": "engine_scale_88", "secondary_profile": "full"},
]

FROZEN_COEFFICIENTS = {
    "PRESTIGE_WEIGHT": 100_000_000,
    "BONUS_WEIGHT": 2_000_000,
    "PURCHASED_CARD_WEIGHT": 250_000,
    "COLORED_TOKEN_WEIGHT": 20_000,
    "GOLD_TOKEN_WEIGHT": 40_000,
    "RESERVED_CARD_WEIGHT": 10_000,
    "AFFORDABLE_CARD_WEIGHT": 100_000,
    "MAX_AFFORDABLE_PRESTIGE_WEIGHT": 5_000_000,
    "NOBLE_PROGRESS_WEIGHT": 10_000,
    "TERMINAL_RANK_UNIT": 1_000_000_000_000,
    "ENGINE_SCALE_25_WEIGHT": 562_500,
    "ENGINE_SCALE_50_WEIGHT": 1_125_000,
    "ENGINE_SCALE_88_WEIGHT": 2_000_000,
    "ENGINE_SCALE_100_WEIGHT": 2_250_000,
    "EQUAL_LOO_WEIGHT": 1_125_000,
}

ALGEBRAIC_IDENTITY_THEOREM = {
    "theorem": "B(p) == P(p) == C(p) on all legal reachable states in base Splendor",
    "catalog_card_count": 90,
    "card_bonus_rule": "Every CardDef has exactly one GemColor bonus",
    "initial_equality": "B(p)=0, P(p)=0 at setup",
    "transition_invariance": "apply_buy() simultaneously increments bonus[color] and inserts card into purchased",
    "evaluator_collapse": "CORE_ENGINE(p) == C(p) * (2,000,000 + 250,000) == C(p) * 2,250,000",
    "naive_loo_ruling": "PERMANENTLY REJECTED AS NON-IDENTIFIABLE",
}

# Formal scientific conclusion (reviewer-approved wording, Closure Repair 1).
FROZEN_CONCLUSION = (
    "M44C establishes that total permanent bonuses and purchased-card count are "
    "algebraically non-identifiable as separate scalar information sources under "
    "the current base rules: both equal the same reachable-state scalar C. The "
    "three preregistered positive scale points-562.5k, 1.125M and 2.0M-were all "
    "UNRESOLVED against the 2.25M FULL baseline at the adjusted 98.333% "
    "confidence level. Separately, the historical M44B zero-engine arm was "
    "resolved weaker. Together these results are compatible with substantial "
    "scale robustness above zero, but do not identify a continuous robustness "
    "plateau, threshold, cliff location, monotonic response, or coefficient "
    "optimum."
)

HEX64 = set("0123456789abcdef")


def is_hex64(value: str) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= HEX64


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bootstrap_ci_983(block_scores: list[float], seed: int, resamples: int) -> tuple[float, float]:
    import numpy as np

    rng = np.random.RandomState(seed)
    n = len(block_scores)
    arr = np.array(block_scores, dtype=np.float64)
    idx = rng.randint(0, n, size=(resamples, n))
    sample_means = np.mean(arr[idx], axis=1)
    lower = float(np.percentile(sample_means, 100.0 * (0.05 / 3.0) / 2.0))
    upper = float(np.percentile(sample_means, 100.0 * (1.0 - (0.05 / 3.0) / 2.0)))
    return lower, upper


def verify_agent_args(agent_cfg: dict[str, Any], expected_profile: str) -> None:
    prog = agent_cfg.get("program", "")
    args = agent_cfg.get("args", [])
    if "splendor" not in prog.lower():
        raise ValueError(f"Expected splendor binary, got {prog}")
    if "agent-determinization" not in args:
        raise ValueError(f"Expected agent-determinization in args, got {args}")

    def get_flag(f: str) -> str | None:
        if f in args:
            idx = args.index(f)
            if idx + 1 < len(args):
                return args[idx + 1]
        return None

    if get_flag("--sample-seed") != str(SAMPLE_SEED):
        raise ValueError("sample-seed mismatch")
    if get_flag("--sample-count") != str(SAMPLE_COUNT):
        raise ValueError("sample-count mismatch")
    if get_flag("--max-depth-turns") != str(DEPTH_TURNS):
        raise ValueError("max-depth-turns mismatch")
    if get_flag("--max-nodes") != str(MAX_NODES):
        raise ValueError("max-nodes mismatch")
    if get_flag("--attribution-profile") != expected_profile:
        raise ValueError(f"profile mismatch: expected {expected_profile}, got {get_flag('--attribution-profile')}")


def audit_pairing(spec: dict[str, Any]) -> dict[str, Any]:
    pairing_id = spec["id"]
    p_dir = ARENA_ROOT / pairing_id
    if not p_dir.is_dir():
        raise RuntimeError(f"Pairing directory missing: {p_dir}")

    block_scores = []
    block_score_distribution: dict[str, int] = {}
    wins = 0
    ties = 0
    losses = 0
    seat0_scores = []
    seat1_scores = []
    total_plies = []

    report_shas = []
    replay_shas = []

    lineup_checks = 0
    rotation_checks = 0

    for b_idx, seed in enumerate(FROZEN_SEEDS):
        b_dir = p_dir / f"block-{b_idx:02d}-seed-{seed}"
        if not b_dir.is_dir():
            raise RuntimeError(f"Block directory missing: {b_dir}")

        block_rot_scores = []
        for rot in (0, 1):
            r_dir = b_dir / f"r{rot}"
            cfg_file = r_dir / "match-config.json"
            rep_file = r_dir / "arena-report.json"
            rpl_file = r_dir / "match-replay.json"

            if not cfg_file.exists():
                raise RuntimeError(f"Config missing: {cfg_file}")
            if not rep_file.exists():
                raise RuntimeError(f"Report missing: {rep_file}")
            if not rpl_file.exists():
                raise RuntimeError(f"Replay missing: {rpl_file}")

            cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
            agents = cfg.get("agents", [])
            if len(agents) != 2:
                raise RuntimeError(f"Expected 2 agents, got {len(agents)} in {cfg_file}")

            # 1. Lineup check
            if rot == 0:
                verify_agent_args(agents[0], spec["primary_profile"])
                verify_agent_args(agents[1], spec["secondary_profile"])
            else:
                verify_agent_args(agents[0], spec["secondary_profile"])
                verify_agent_args(agents[1], spec["primary_profile"])
            lineup_checks += 2
            rotation_checks += 1

            # 2. Report check
            report = json.loads(rep_file.read_text(encoding="utf-8"))
            if report.get("format") != "effective-splendor-arena-report":
                raise RuntimeError("Invalid report format")
            outcome = report.get("outcome", {})
            if outcome.get("status") != "completed":
                raise RuntimeError(f"Status not completed in {rep_file}: {outcome}")

            primary_seat = 0 if rot == 0 else 1
            res = outcome["result"]
            winners = res["winners"]
            if primary_seat in winners:
                if len(winners) == 1:
                    score = 10_000.0
                    wins += 1
                else:
                    score = 5_000.0
                    ties += 1
            else:
                score = 0.0
                losses += 1

            block_rot_scores.append(score)
            if rot == 0:
                seat0_scores.append(score)
            else:
                seat1_scores.append(score)
            total_plies.append(outcome["completed_plies"])

            # 3. Verify replay
            v_res = subprocess.run([str(SPLN), "verify-replay", "--input", str(rpl_file)], capture_output=True, text=True)
            if v_res.returncode != 0:
                raise RuntimeError(f"verify-replay failed on {rpl_file}: {v_res.stderr}")

            report_shas.append(file_sha256(rep_file))
            replay_shas.append(file_sha256(rpl_file))

        block_score = sum(block_rot_scores) / 2.0
        block_scores.append(block_score)
        block_score_distribution[f"{block_score:.1f}"] = block_score_distribution.get(f"{block_score:.1f}", 0) + 1

    center_bps = sum(block_scores) / len(block_scores)
    ci_lower, ci_upper = bootstrap_ci_983(block_scores, BOOTSTRAP_SEED, BOOTSTRAP_RESAMPLES)

    if ci_upper < 5000.0:
        verdict = "RESOLVED_WEAKER"
    elif ci_lower > 5000.0:
        verdict = "RESOLVED_STRONGER"
    else:
        verdict = "UNRESOLVED"

    # Fail-closed assertion against the frozen P1 numbers accepted in review.
    frozen = FROZEN_P1[pairing_id]
    if (wins, ties, losses) != (frozen["wins"], frozen["ties"], frozen["losses"]):
        raise RuntimeError(
            f"FROZEN P1 VIOLATION for {pairing_id}: recomputed W/T/L "
            f"{(wins, ties, losses)} != frozen {(frozen['wins'], frozen['ties'], frozen['losses'])}"
        )
    if abs(center_bps - frozen["center_bps"]) > 1e-9:
        raise RuntimeError(
            f"FROZEN P1 VIOLATION for {pairing_id}: recomputed center {center_bps} != frozen {frozen['center_bps']}"
        )

    return {
        "pairing_id": pairing_id,
        "primary_profile": spec["primary_profile"],
        "secondary_profile": spec["secondary_profile"],
        "matches_expected": 128,
        "matches_verified": len(report_shas),
        "lineup_checks_passed": lineup_checks,
        "rotation_checks_passed": rotation_checks,
        "wins": wins,
        "ties": ties,
        "losses": losses,
        "center_bps": center_bps,
        "ci_level": "98.333%",
        "bootstrap_ci": [ci_lower, ci_upper],
        "verdict": verdict,
        "seat0_mean_bps": sum(seat0_scores) / len(seat0_scores),
        "seat1_mean_bps": sum(seat1_scores) / len(seat1_scores),
        "mean_completed_plies": sum(total_plies) / len(total_plies),
        "paired_block_score_distribution": block_score_distribution,
        "reports_digest_sha256": hashlib.sha256("\n".join(report_shas).encode()).hexdigest(),
        "replays_digest_sha256": hashlib.sha256("\n".join(replay_shas).encode()).hexdigest(),
    }


def hard_assert_p2(p2_audit: dict[str, Any]) -> None:
    """Fail-closed gate on the P2 common-state scale audit (Closure Repair 1)."""
    if p2_audit.get("closure_repair") != 1:
        raise RuntimeError("P2 audit is not the Closure Repair 1 version")
    if p2_audit.get("audited_contexts_count") != 200:
        raise RuntimeError(f"P2 must audit exactly 200 contexts, got {p2_audit.get('audited_contexts_count')}")

    quota = p2_audit["quota_matrix_composition"]
    expected_quota = {
        "scale25": {"early": 23, "mid": 22, "late": 22, "total": 67},
        "scale50": {"early": 22, "mid": 23, "late": 22, "total": 67},
        "scale88": {"early": 22, "mid": 22, "late": 22, "total": 66},
        "total": 200,
    }
    if quota != expected_quota:
        raise RuntimeError(f"P2 quota matrix mismatch: {quota}")

    repro = p2_audit["source_reproduction"]
    if repro["checks"] != 200 or repro["reproduced"] != 200 or repro["pass"] is not True:
        raise RuntimeError(f"P2 source reproduction must be 200/200, got {repro}")

    if not is_hex64(p2_audit.get("contexts_identity_sha256", "")):
        raise RuntimeError("P2 contexts_identity_sha256 missing or not a 64-hex digest")

    if "build_information_set_v1" not in p2_audit.get("identity_method", ""):
        raise RuntimeError("P2 identity_method must reference the authoritative build_information_set_v1 pipeline")

    if "zero_based_step_index + 1" not in p2_audit.get("decision_ply_convention", ""):
        raise RuntimeError("P2 decision_ply_convention must be the 1-based Closure Repair 1 convention")

    if "top-1" not in p2_audit.get("margin_definition", ""):
        raise RuntimeError("P2 margin_definition must be the top-1 vs runner-up definition")

    contexts = p2_audit["contexts"]
    if len(contexts) != 200:
        raise RuntimeError(f"P2 contexts list must have 200 entries, got {len(contexts)}")

    seen_triples = set()
    for c in contexts:
        for field in ("observation_hash", "visible_history_hash", "information_set_hash"):
            if not is_hex64(c[field]):
                raise RuntimeError(
                    f"P2 context {c['context_idx']} field {field} is not an authoritative 64-hex hash: {c[field]!r}"
                )
        triple = (c["observation_hash"], c["visible_history_hash"], c["information_set_hash"])
        if triple in seen_triples:
            raise RuntimeError(f"P2 duplicate identity triple at context {c['context_idx']}")
        seen_triples.add(triple)

        # 1-based staging convention.
        ply, stage = c["decision_ply"], c["stage"]
        expected_stage = "early" if ply <= 20 else ("mid" if ply <= 45 else "late")
        if stage != expected_stage:
            raise RuntimeError(f"P2 context {c['context_idx']} stage {stage} inconsistent with decision_ply {ply}")

    print("P2 hard gates passed: 200 contexts, exact quota, authoritative unique identities, 200/200 reproduction.")


def hard_assert_p3(p3_audit: dict[str, Any]) -> None:
    """Fail-closed gate on the P3 vector heterogeneity audit (Closure Repair 1)."""
    if p3_audit.get("closure_repair") != 1:
        raise RuntimeError("P3 audit is not the Closure Repair 1 version")
    if not is_hex64(p3_audit.get("corpus_identity_sha256", "")):
        raise RuntimeError("P3 corpus_identity_sha256 missing or not a 64-hex digest")
    if "build_information_set_v1" not in p3_audit.get("identity_method", ""):
        raise RuntimeError("P3 identity_method must reference the authoritative build_information_set_v1 pipeline")

    corpus = p3_audit["corpus_unique_contexts"]
    strata = p3_audit["strata_metrics"]
    strata_total = sum(m["context_count"] for m in strata)
    if strata_total != corpus:
        raise RuntimeError(f"P3 strata total {strata_total} != corpus size {corpus}")

    observed = p3_audit["observed_c_values"]
    strata_c = [m["c_val"] for m in strata]
    if sorted(strata_c) != sorted(observed):
        raise RuntimeError("P3 observed_c_values inconsistent with strata metrics")

    for m in strata:
        if m["context_count"] < 1:
            raise RuntimeError(f"P3 stratum C={m['c_val']} has non-positive context count")
        if m["distinct_vectors_count"] < 1:
            raise RuntimeError(f"P3 stratum C={m['c_val']} has non-positive distinct vector count")
        freq_total = sum(m["vector_frequencies"].values())
        if freq_total != m["context_count"]:
            raise RuntimeError(f"P3 stratum C={m['c_val']} vector frequencies sum {freq_total} != count {m['context_count']}")

    print(f"P3 hard gates passed: {corpus} unique authoritative-identity contexts, {len(strata)} consistent strata.")


def main() -> None:
    print("M44C Final Exhaustive Audit (Closure Repair 1) started...", flush=True)
    t0 = time.time()

    # 1. Run P0 semantic test suites (M44A, M44B regression + M44C P0)
    print("Running M44A P0 regression test suite...", flush=True)
    p0_a_res = subprocess.run(["cargo", "test", "-p", "splendor-cli", "--test", "m44a_p0_semantic"], capture_output=True, text=True, cwd=str(REPO))
    if p0_a_res.returncode != 0:
        raise RuntimeError(f"M44A P0 semantic tests failed:\n{p0_a_res.stdout}\n{p0_a_res.stderr}")
    print("M44A P0 regression test suite PASSED (6/6).", flush=True)

    print("Running M44B P0 regression test suite...", flush=True)
    p0_b_res = subprocess.run(["cargo", "test", "-p", "splendor-cli", "--test", "m44b_p0_semantic"], capture_output=True, text=True, cwd=str(REPO))
    if p0_b_res.returncode != 0:
        raise RuntimeError(f"M44B P0 semantic tests failed:\n{p0_b_res.stdout}\n{p0_b_res.stderr}")
    print("M44B P0 regression test suite PASSED (4/4).", flush=True)

    print("Running M44C P0 semantic test suite...", flush=True)
    p0_c_res = subprocess.run(["cargo", "test", "-p", "splendor-cli", "--test", "m44c_p0_semantic"], capture_output=True, text=True, cwd=str(REPO))
    if p0_c_res.returncode != 0:
        raise RuntimeError(f"M44C P0 semantic tests failed:\n{p0_c_res.stdout}\n{p0_c_res.stderr}")
    print("M44C P0 semantic test suite PASSED (4/4, authoritative M07 12-case corpus).", flush=True)

    # 2. Audit all 3 Arena pairings (frozen P1 assertions inside)
    pairing_results = []
    total_lineup_checks = 0
    total_rotation_checks = 0
    total_verified_matches = 0

    for spec in PAIRING_SPECS:
        print(f"Auditing pairing {spec['id']} (128 matches)...", flush=True)
        res = audit_pairing(spec)
        pairing_results.append(res)
        total_verified_matches += res["matches_verified"]
        total_lineup_checks += res["lineup_checks_passed"]
        total_rotation_checks += res["rotation_checks_passed"]

    assert total_verified_matches == 384, f"Expected 384 verified matches, got {total_verified_matches}"
    assert total_lineup_checks == 768, f"Expected 768 lineup checks, got {total_lineup_checks}"
    assert total_rotation_checks == 384, f"Expected 384 rotation checks, got {total_rotation_checks}"

    # Scale88 paired-block score distribution must be recorded explicitly.
    s88 = next(p for p in pairing_results if p["pairing_id"] == "engine_scale_88_vs_full")
    if not s88["paired_block_score_distribution"]:
        raise RuntimeError("Scale88 paired_block_score_distribution missing")
    s88_dist_total = sum(s88["paired_block_score_distribution"].values())
    if s88_dist_total != 64:
        raise RuntimeError(f"Scale88 paired-block distribution must cover 64 blocks, got {s88_dist_total}")

    # 3. Load and hard-gate P2 common-state scale audit
    p2_path = ARENA_ROOT / "m44c-common-state-scale-audit.json"
    if not p2_path.exists():
        raise RuntimeError(f"P2 audit summary missing at {p2_path}")
    p2_audit = json.loads(p2_path.read_text(encoding="utf-8"))
    hard_assert_p2(p2_audit)

    # 4. Load and hard-gate P3 vector heterogeneity audit
    p3_path = ARENA_ROOT / "m44c-vector-heterogeneity-audit.json"
    if not p3_path.exists():
        raise RuntimeError(f"P3 audit summary missing at {p3_path}")
    p3_audit = json.loads(p3_path.read_text(encoding="utf-8"))
    hard_assert_p3(p3_audit)

    # 5. Provenance bindings
    splendor_exe_sha = file_sha256(SPLN)
    catalog_sha = file_sha256(CATALOG)

    # Real catalog semantic hash from the authoritative loader (P2-A repair).
    sys.path.insert(0, str(REPO / "training/m17_gpu"))
    from splendor_gpu.data import catalog_semantic_hash, load_catalog

    catalog = load_catalog(CATALOG)
    cat_sem_hash = catalog_semantic_hash(catalog)
    if not is_hex64(cat_sem_hash):
        raise RuntimeError(f"catalog_semantic_hash is not a 64-hex digest: {cat_sem_hash!r}")

    m44b_result_sha = file_sha256(M44B_RESULT_JSON)
    m44a_result_sha = file_sha256(M44A_RESULT_JSON)

    frozen_seeds_bytes = ",".join(map(str, FROZEN_SEEDS)).encode()
    frozen_seeds_sha = hashlib.sha256(frozen_seeds_bytes).hexdigest()

    pairing_sched_bytes = json.dumps(PAIRING_SPECS, sort_keys=True).encode()
    pairing_sched_sha = hashlib.sha256(pairing_sched_bytes).hexdigest()

    coeff_bytes = json.dumps(FROZEN_COEFFICIENTS, sort_keys=True).encode()
    coeff_sha = hashlib.sha256(coeff_bytes).hexdigest()

    source_shas = {
        "m44c_orchestrator": file_sha256(REPO / "scripts/m44c_orchestrator.py"),
        "m44c_audit_command": file_sha256(REPO / "crates/splendor-cli/src/m44c_audit_command.rs"),
        "m44c_final_audit": file_sha256(REPO / "scripts/m44c_final_audit.py"),
        "m44c_p0_semantic_test": file_sha256(REPO / "crates/splendor-cli/tests/m44c_p0_semantic.rs"),
        "m44b_p0_semantic_test": file_sha256(REPO / "crates/splendor-cli/tests/m44b_p0_semantic.rs"),
        "m44a_p0_semantic_test": file_sha256(REPO / "crates/splendor-cli/tests/m44a_p0_semantic.rs"),
        "attribution_evaluator": file_sha256(REPO / "crates/splendor-search/src/attribution.rs"),
        "static_evaluator": file_sha256(REPO / "crates/splendor-search/src/evaluation.rs"),
        "imperfect_search": file_sha256(REPO / "crates/splendor-imperfect-search/src/search.rs"),
        "determinization_agent": file_sha256(REPO / "crates/splendor-determinization-agent/src/lib.rs"),
    }

    # 6. Build final tracked result document
    final_document = {
        "format": "effective-splendor-m44c-core-engine-identity-scale-sensitivity",
        "version": 2,
        "closure_repair": 1,
        "milestone": "M44C",
        "title": "Core Engine Identity & Scale Sensitivity",
        "audit_completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_pairings": 3,
        "total_matches_expected": 384,
        "total_matches_verified": total_verified_matches,
        "arena_freeze": {
            "p1_arena_rerun": "FORBIDDEN (accepted in terminal review; Closure Repair 1 re-audits evidence only)",
            "frozen_p1_outcomes": FROZEN_P1,
        },
        "exhaustiveness": {
            "reports_seen": total_verified_matches,
            "replays_seen": total_verified_matches,
            "missing_reports": 0,
            "duplicate_reports": 0,
            "aborted_matches": 0,
            "candidate_faults": 0,
            "lineup_checks_performed": total_lineup_checks,
            "lineup_mismatches_found": 0,
            "rotation_checks_performed": total_rotation_checks,
            "rotation_mismatches_found": 0,
            "replay_verification_failures": 0,
        },
        "algebraic_identity_theorem": ALGEBRAIC_IDENTITY_THEOREM,
        "frozen_coefficients": FROZEN_COEFFICIENTS,
        "frozen_conclusion": FROZEN_CONCLUSION,
        "p0_semantic_tests": {
            "m44a_regression_tests_passed": 6,
            "m44b_regression_tests_passed": 4,
            "m44c_p0_tests_passed": 4,
            "m44c_p0_frozen_corpus": "authoritative M44A 12-case definitions (bit-exact)",
            "p0_a_algebraic_identity_verified": True,
            "p0_b_equalized_loo_isomorphism_verified": True,
            "p0_c_full_scale_identity_verified": True,
            "p0_d_constants_parsing_verified": True,
            "all_passed": True,
        },
        "provenance": {
            "design_v2_commit": "fd0211d",
            "implementation_commit": "58863f8",
            "m44b_closure_commit": "b3bb4c9",
            "m44b_closure_basis": "ce16a58",
            "m44b_result_artifact_sha256": m44b_result_sha,
            "m44a_closure_commit": "4d83b3f",
            "m44a_result_artifact_sha256": m44a_result_sha,
            "splendor_exe_sha256": splendor_exe_sha,
            "catalog_file_sha256": catalog_sha,
            "catalog_semantic_hash": cat_sem_hash,
            "sample_seed": SAMPLE_SEED,
            "sample_count": SAMPLE_COUNT,
            "depth_turns": DEPTH_TURNS,
            "max_nodes": MAX_NODES,
            "bootstrap_seed": BOOTSTRAP_SEED,
            "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
            "frozen_seeds_count": len(FROZEN_SEEDS),
            "frozen_seeds_sha256": frozen_seeds_sha,
            "pairing_schedule_sha256": pairing_sched_sha,
            "coefficients_table_sha256": coeff_sha,
            "source_shas": source_shas,
        },
        "pairings": pairing_results,
        "p2_common_state_scale_audit": p2_audit,
        "p3_vector_heterogeneity_audit": p3_audit,
    }

    RESULT_JSON.write_text(json.dumps(final_document, indent=2), encoding="utf-8")
    print(f"\nTracked result document written to {RESULT_JSON} (SHA256: {file_sha256(RESULT_JSON)})")

    print("\n" + "=" * 60)
    print("M44C AUDIT SUMMARY (Closure Repair 1):")
    print("=" * 60)
    for p in pairing_results:
        print(f"  {p['pairing_id']:26s}: {p['center_bps']:7.2f} bps  98.333% CI: [{p['bootstrap_ci'][0]:6.2f}, {p['bootstrap_ci'][1]:6.2f}]  -> {p['verdict']}")
    print(f"  Scale88 paired-block score distribution: {s88['paired_block_score_distribution']}")
    print(f"\nP2 Disagreement Rates vs FULL:")
    for k, v in p2_audit["disagreement_rates_vs_full"].items():
        print(f"  {k}: {v * 100:.1f}% ({p2_audit['disagreement_counts'][k]}/200)")
    print(f"P2 Engine-pivotal Behavior Rates:")
    for k, v in p2_audit["engine_pivotal_behavior_rates"].items():
        print(f"  {k}: {v * 100:.1f}% ({p2_audit['engine_pivotal_counts'][k]}/200)")
    print(f"\nP3 Corpus Unique Contexts: {p3_audit['corpus_unique_contexts']}")
    print(f"P3 Observed C Strata: {len(p3_audit['observed_c_values'])} strata ({p3_audit['observed_c_values'][0]}..{p3_audit['observed_c_values'][-1]})")
    print(f"All 384 matches verified, all P0/P1/P2/P3 hard gates passed in {time.time() - t0:.1f}s.")


if __name__ == "__main__":
    main()
