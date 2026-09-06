//! M45A P2 Behavior Audit and P3 Residual Bonus-Vector Capacity Audit Command.
//!
//! Enforces:
//! - P2: Exact 180-context quota matrix (3 pairings x 3 stages x 20).
//! - P2: Authoritative context identity = (observation_hash,
//!   visible_history_hash, information_set_hash) via the same
//!   `build_information_set_v1` pipeline as `analyze-replay-player-view`.
//! - P2: 1-based decision-ply staging (early 1..=20, mid 21..=45, late 46+).
//! - P2: Top-1 vs runner-up margins from sorted root utilities.
//! - P2: True-vs-shifted F4/E2 delta distributions (descriptive).
//! - P3: Residual capacity audit on all accepted replays, deduplicated by the
//!   authoritative identity triple, keyed by K_path = (C, E2, F4) and
//!   K_eval = (F1, CORE, E2, F3, F4) collision groups.

use std::collections::{BTreeMap, HashMap, HashSet};
use std::fs::File;
use std::path::PathBuf;

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use splendor_core::{
    observation_hash, visible_events, Action, Audience, FullState, GameConfig, Phase, PlayerId,
    Ruleset, VisibleEvent,
};
use splendor_imperfect_search::{
    analyze_player_view_attribution_v1, RootActionAggregateV1, RootDeterminizationConfigV1,
};
use splendor_replay::{verify_replay, ReplayV1};
use splendor_search::{family_progress_for, AttributionProfile, SearchConfigV1};

const SAMPLE_SEED: u64 = 20_260_703;
const SAMPLE_COUNT: u16 = 4;
const DEPTH_TURNS: u8 = 1;
const MAX_NODES: u64 = 1;

fn n1_config() -> RootDeterminizationConfigV1 {
    RootDeterminizationConfigV1 {
        sample_seed: SAMPLE_SEED,
        sample_count: SAMPLE_COUNT,
        continuation_search: SearchConfigV1 {
            max_depth_turns: DEPTH_TURNS,
            max_nodes: MAX_NODES,
        },
    }
}

fn is_engine_action(action: &Action) -> bool {
    matches!(
        action,
        Action::BuyMarket { .. } | Action::BuyReserved { .. }
    )
}

/// Stage classification on 1-based decision ply:
/// early = decisions 1..=20, mid = 21..=45, late = 46+.
fn stage_for_decision_ply(decision_ply: u32) -> &'static str {
    if decision_ply <= 20 {
        "early"
    } else if decision_ply <= 45 {
        "mid"
    } else {
        "late"
    }
}

/// Authoritative context identity triple (same pipeline as
/// `analyze-replay-player-view` source metadata).
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct IdentityTriple {
    pub observation_hash: String,
    pub visible_history_hash: String,
    pub information_set_hash: String,
}

impl IdentityTriple {
    fn composite_key(&self) -> String {
        format!(
            "{}:{}:{}",
            self.observation_hash, self.visible_history_hash, self.information_set_hash
        )
    }
}

/// Top-1 vs runner-up margin from actual root utilities (M44C-corrected
/// method): best = highest root-player utility with canonical tie-break;
/// runner-up = second-highest utility among other actions; asserts best ==
/// analyzer-selected action.
fn top1_runnerup_margin(
    aggregates: &[RootActionAggregateV1],
    root_player: PlayerId,
    selected_action: &Action,
) -> Result<(Action, Action, i64), String> {
    let player_index = root_player.index();
    if aggregates.len() < 2 {
        return Err(format!(
            "expected at least 2 action aggregates, got {}",
            aggregates.len()
        ));
    }

    let value_of = |agg: &RootActionAggregateV1| -> Result<i64, String> {
        agg.utility_sum_by_player
            .get(player_index)
            .copied()
            .ok_or_else(|| format!("utility shape mismatch for player {player_index}"))
    };

    let mut best_idx = 0usize;
    let mut best_value = i64::MIN;
    for (idx, agg) in aggregates.iter().enumerate() {
        let value = value_of(agg)?;
        if idx == 0 || value > best_value {
            best_value = value;
            best_idx = idx;
        }
    }

    let mut runner_idx = usize::MAX;
    let mut runner_value = i64::MIN;
    for (idx, agg) in aggregates.iter().enumerate() {
        if idx == best_idx {
            continue;
        }
        let value = value_of(agg)?;
        if runner_idx == usize::MAX || value > runner_value {
            runner_value = value;
            runner_idx = idx;
        }
    }

    let best_action = aggregates[best_idx].action;
    if best_action != *selected_action {
        return Err(format!(
            "best action by utility ({best_action:?}) != analyzer selected action ({selected_action:?})"
        ));
    }

    Ok((
        best_action,
        aggregates[runner_idx].action,
        best_value - runner_value,
    ))
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct P2ContextRecord {
    pub context_idx: usize,
    pub pairing_id: String,
    pub seed: u64,
    pub rotation: u8,
    pub step_index: usize,
    pub decision_ply: u32,
    pub stage: String,
    pub recorded_actor: usize,
    pub recorded_action: Action,
    pub recorded_profile: String,
    pub observation_hash: String,
    pub visible_history_hash: String,
    pub information_set_hash: String,
    pub c_val: i64,
    pub bonus_vector: [u8; 5],
    pub true_f4: i64,
    pub shifted_f4: i64,
    pub true_e2: i64,
    pub shifted_e2: i64,
    pub full_action: Action,
    pub full_margin: i64,
    pub shift_f4_action: Action,
    pub shift_f4_margin: i64,
    pub shift_e2_action: Action,
    pub shift_e2_margin: i64,
    pub shift_f4_e2_action: Action,
    pub shift_f4_e2_margin: i64,
    pub shift_f4_engine_pivotal: bool,
    pub shift_e2_engine_pivotal: bool,
    pub shift_f4_e2_engine_pivotal: bool,
}

/// One scanned candidate context during the selection walk over a replay.
struct ScannedContext {
    pairing_id: &'static str,
    seed: u64,
    rotation: u8,
    step_index: usize,
    decision_ply: u32,
    stage: &'static str,
    actor: PlayerId,
    recorded_action: Action,
    recorded_profile: String,
    rpl_path: PathBuf,
    identity: IdentityTriple,
}

pub fn run_m45a_audit(args: &[String]) -> i32 {
    let arena_dir = if let Some(pos) = args.iter().position(|a| a == "--arena-dir") {
        PathBuf::from(&args[pos + 1])
    } else {
        PathBuf::from("local-artifacts/m45a-arena")
    };

    let p2_out = if let Some(pos) = args.iter().position(|a| a == "--p2-out") {
        PathBuf::from(&args[pos + 1])
    } else {
        arena_dir.join("m45a-behavior-audit.json")
    };

    let p3_out = if let Some(pos) = args.iter().position(|a| a == "--p3-out") {
        PathBuf::from(&args[pos + 1])
    } else {
        arena_dir.join("m45a-residual-capacity-audit.json")
    };

    println!("Starting M45A Audits (P2 & P3)...");
    println!("Arena Directory: {:?}", arena_dir);

    let pairings = [
        "shift_f4_vs_full",
        "shift_e2_vs_full",
        "shift_f4_e2_vs_full",
    ];

    let ruleset = Ruleset::base_v1();
    let cfg = n1_config();

    // -----------------------------------------------------------------------
    // P2: Exact 180-Context Quota Matrix (authoritative identity)
    // -----------------------------------------------------------------------
    // 3 pairings x (early 20, mid 20, late 20) = 180.
    let target_quotas: HashMap<(&'static str, &'static str), usize> = [
        (("shift_f4_vs_full", "early"), 20),
        (("shift_f4_vs_full", "mid"), 20),
        (("shift_f4_vs_full", "late"), 20),
        (("shift_e2_vs_full", "early"), 20),
        (("shift_e2_vs_full", "mid"), 20),
        (("shift_e2_vs_full", "late"), 20),
        (("shift_f4_e2_vs_full", "early"), 20),
        (("shift_f4_e2_vs_full", "mid"), 20),
        (("shift_f4_e2_vs_full", "late"), 20),
    ]
    .into_iter()
    .collect();

    let mut current_counts: HashMap<(&'static str, &'static str), usize> = HashMap::new();
    let mut selected_contexts: Vec<ScannedContext> = Vec::new();
    let mut global_seen_identities = HashSet::new();

    for &pairing_id in &pairings {
        let p_candidate_profile = pairing_id.replace("_vs_full", "");
        let _primary_attr_profile: AttributionProfile = p_candidate_profile.parse().unwrap();

        for &stage in &["early", "mid", "late"] {
            let cell_target = *target_quotas.get(&(pairing_id, stage)).unwrap();

            'search_loop: for seed in 5_800_000..5_800_064 {
                let block_idx = seed - 5_800_000;
                for rotation in [0u8, 1] {
                    let rpl_path = arena_dir
                        .join(pairing_id)
                        .join(format!("block-{block_idx:02}-seed-{seed}"))
                        .join(format!("r{rotation}"))
                        .join("match-replay.json");

                    if !rpl_path.exists() {
                        eprintln!("Missing replay file: {:?}", rpl_path);
                        return 1;
                    }

                    let file = File::open(&rpl_path).unwrap();
                    let replay: ReplayV1 = serde_json::from_reader(file).unwrap();
                    let _verified = verify_replay(&replay).unwrap();

                    let (mut state, setup) = FullState::new(GameConfig {
                        player_count: replay.player_count,
                        seed: replay.seed,
                        ruleset,
                    })
                    .unwrap();

                    let player_count = replay.player_count as usize;
                    let mut histories: Vec<Vec<VisibleEvent>> = (0..player_count)
                        .map(|p| visible_events(&setup.events, Audience::Player(PlayerId(p as u8))))
                        .collect();

                    for step_index in 0..replay.steps.len() {
                        let step = &replay.steps[step_index];
                        let actor = step.actor;
                        let decision_ply = u32::try_from(step_index).unwrap() + 1;
                        let ply_stage = stage_for_decision_ply(decision_ply);

                        let legal = state.legal_actions();
                        let is_main = state.phase == Phase::Main;
                        let eligible = is_main && legal.len() >= 2;

                        let visible_history = &histories[actor.index()];
                        let obs = state.observation(actor);
                        let identity = {
                            let probe = match analyze_player_view_attribution_v1(
                                ruleset,
                                &obs,
                                visible_history,
                                cfg,
                                AttributionProfile::Full,
                            ) {
                                Ok(p) => p,
                                Err(e) => {
                                    eprintln!(
                                        "FAIL CLOSED: identity probe failed at {:?} step {}: {e}",
                                        rpl_path, step_index
                                    );
                                    return 1;
                                }
                            };
                            IdentityTriple {
                                observation_hash: observation_hash(&obs).to_string(),
                                visible_history_hash: probe
                                    .visible_history_hash()
                                    .as_str()
                                    .to_string(),
                                information_set_hash: probe
                                    .information_set_hash()
                                    .as_str()
                                    .to_string(),
                            }
                        };

                        let cell_count = current_counts.entry((pairing_id, stage)).or_insert(0);
                        if eligible
                            && ply_stage == stage
                            && *cell_count < cell_target
                            && !global_seen_identities.contains(&identity.composite_key())
                        {
                            global_seen_identities.insert(identity.composite_key());
                            *cell_count += 1;

                            let recorded_profile_str = if rotation == 0 {
                                if actor.index() == 0 {
                                    p_candidate_profile.as_str()
                                } else {
                                    "full"
                                }
                            } else if actor.index() == 1 {
                                p_candidate_profile.as_str()
                            } else {
                                "full"
                            };

                            selected_contexts.push(ScannedContext {
                                pairing_id,
                                seed,
                                rotation,
                                step_index,
                                decision_ply,
                                stage,
                                actor,
                                recorded_action: step.action,
                                recorded_profile: recorded_profile_str.to_string(),
                                rpl_path: rpl_path.clone(),
                                identity,
                            });

                            if *cell_count >= cell_target {
                                break 'search_loop;
                            }
                        }

                        let res = state.apply(step.action).unwrap();
                        for (p, history) in histories.iter_mut().enumerate() {
                            history.extend(visible_events(
                                &res.events,
                                Audience::Player(PlayerId(p as u8)),
                            ));
                        }
                    }
                }
            }

            let cell_count = *current_counts.get(&(pairing_id, stage)).unwrap_or(&0);
            if cell_count < cell_target {
                eprintln!(
                    "FAIL CLOSED: Quota for ({}, {}) could not be filled: got {} < target {}",
                    pairing_id, stage, cell_count, cell_target
                );
                return 1;
            }
        }
    }

    assert_eq!(
        selected_contexts.len(),
        180,
        "Must select exactly 180 contexts"
    );
    println!("Successfully selected 180 contexts strictly fulfilling the quota matrix.");

    // Evaluate each of the 180 contexts under FULL and all three shift profiles.
    let mut p2_records = Vec::new();
    let mut source_reproductions_ok = 0;

    for (idx, sc) in selected_contexts.iter().enumerate() {
        let file = File::open(&sc.rpl_path).unwrap();
        let replay: ReplayV1 = serde_json::from_reader(file).unwrap();

        let (mut state, setup) = FullState::new(GameConfig {
            player_count: replay.player_count,
            seed: replay.seed,
            ruleset,
        })
        .unwrap();

        let viewer = sc.actor;
        let mut visible_history = visible_events(&setup.events, Audience::Player(viewer));

        for step in replay.steps.iter().take(sc.step_index) {
            let res = state.apply(step.action).unwrap();
            visible_history.extend(visible_events(&res.events, Audience::Player(viewer)));
        }

        let obs = state.observation(viewer);
        let player = &state.players[sc.actor.index()];
        let fp = family_progress_for(&state, player);
        let c_val = fp.purchased_card_count;
        let bonus_vector = player.bonuses;

        // 1. FULL
        let a_full = analyze_player_view_attribution_v1(
            ruleset,
            &obs,
            &visible_history,
            cfg,
            AttributionProfile::Full,
        )
        .unwrap();
        let res_full = a_full.result();
        let full_action = res_full.action;
        let (full_best, _r, full_margin) =
            match top1_runnerup_margin(&res_full.action_aggregates, sc.actor, &full_action) {
                Ok(v) => v,
                Err(msg) => {
                    eprintln!(
                        "FAIL CLOSED: context {}: FULL margin check failed: {msg}",
                        idx
                    );
                    return 1;
                }
            };
        debug_assert_eq!(full_best, full_action);
        if a_full.visible_history_hash().as_str() != sc.identity.visible_history_hash
            || a_full.information_set_hash().as_str() != sc.identity.information_set_hash
        {
            eprintln!(
                "FAIL CLOSED: context {}: identity mismatch between selection and analysis",
                idx
            );
            return 1;
        }

        // 2. SHIFT_F4
        let a_sf4 = analyze_player_view_attribution_v1(
            ruleset,
            &obs,
            &visible_history,
            cfg,
            AttributionProfile::ShiftF4,
        )
        .unwrap();
        let res_sf4 = a_sf4.result();
        let sf4_action = res_sf4.action;
        let (_, _, sf4_margin) =
            match top1_runnerup_margin(&res_sf4.action_aggregates, sc.actor, &sf4_action) {
                Ok(v) => v,
                Err(msg) => {
                    eprintln!(
                        "FAIL CLOSED: context {}: SHIFT_F4 margin check failed: {msg}",
                        idx
                    );
                    return 1;
                }
            };

        // 3. SHIFT_E2
        let a_se2 = analyze_player_view_attribution_v1(
            ruleset,
            &obs,
            &visible_history,
            cfg,
            AttributionProfile::ShiftE2,
        )
        .unwrap();
        let res_se2 = a_se2.result();
        let se2_action = res_se2.action;
        let (_, _, se2_margin) =
            match top1_runnerup_margin(&res_se2.action_aggregates, sc.actor, &se2_action) {
                Ok(v) => v,
                Err(msg) => {
                    eprintln!(
                        "FAIL CLOSED: context {}: SHIFT_E2 margin check failed: {msg}",
                        idx
                    );
                    return 1;
                }
            };

        // 4. SHIFT_F4_E2
        let a_sboth = analyze_player_view_attribution_v1(
            ruleset,
            &obs,
            &visible_history,
            cfg,
            AttributionProfile::ShiftF4E2,
        )
        .unwrap();
        let res_sboth = a_sboth.result();
        let sboth_action = res_sboth.action;
        let (_, _, sboth_margin) =
            match top1_runnerup_margin(&res_sboth.action_aggregates, sc.actor, &sboth_action) {
                Ok(v) => v,
                Err(msg) => {
                    eprintln!(
                        "FAIL CLOSED: context {}: SHIFT_F4_E2 margin check failed: {msg}",
                        idx
                    );
                    return 1;
                }
            };

        // Source reproduction (fail closed).
        let source_action = match sc.recorded_profile.as_str() {
            "full" => full_action,
            "shift_f4" => sf4_action,
            "shift_e2" => se2_action,
            "shift_f4_e2" => sboth_action,
            other => panic!("Unknown recorded profile: {other}"),
        };

        if source_action == sc.recorded_action {
            source_reproductions_ok += 1;
        } else {
            eprintln!(
                "FAIL CLOSED: Source reproduction mismatch at context {} ({}, seed {}, ply {}): recorded {:?}, reproduced {:?}",
                idx, sc.pairing_id, sc.seed, sc.decision_ply, sc.recorded_action, source_action
            );
            return 1;
        }

        let full_is_engine = is_engine_action(&full_action);
        p2_records.push(P2ContextRecord {
            context_idx: idx,
            pairing_id: sc.pairing_id.to_string(),
            seed: sc.seed,
            rotation: sc.rotation,
            step_index: sc.step_index,
            decision_ply: sc.decision_ply,
            stage: sc.stage.to_string(),
            recorded_actor: sc.actor.index(),
            recorded_action: sc.recorded_action,
            recorded_profile: sc.recorded_profile.clone(),
            observation_hash: sc.identity.observation_hash.clone(),
            visible_history_hash: sc.identity.visible_history_hash.clone(),
            information_set_hash: sc.identity.information_set_hash.clone(),
            c_val,
            bonus_vector,
            true_f4: fp.f4_convertibility,
            shifted_f4: fp.shifted_f4_convertibility,
            true_e2: fp.e2_noble_progress,
            shifted_e2: fp.shifted_e2_noble_progress,
            full_action,
            full_margin,
            shift_f4_action: sf4_action,
            shift_f4_margin: sf4_margin,
            shift_e2_action: se2_action,
            shift_e2_margin: se2_margin,
            shift_f4_e2_action: sboth_action,
            shift_f4_e2_margin: sboth_margin,
            shift_f4_engine_pivotal: full_is_engine != is_engine_action(&sf4_action),
            shift_e2_engine_pivotal: full_is_engine != is_engine_action(&se2_action),
            shift_f4_e2_engine_pivotal: full_is_engine != is_engine_action(&sboth_action),
        });
    }

    assert_eq!(
        source_reproductions_ok, 180,
        "Source reproduction must be 180/180"
    );
    println!("Source reproduction passed: 180 / 180 exact matches (100.0%).");

    // P2 summary statistics.
    let n_ctx = 180.0;
    let sf4_disagreements = p2_records
        .iter()
        .filter(|r| r.shift_f4_action != r.full_action)
        .count();
    let se2_disagreements = p2_records
        .iter()
        .filter(|r| r.shift_e2_action != r.full_action)
        .count();
    let sboth_disagreements = p2_records
        .iter()
        .filter(|r| r.shift_f4_e2_action != r.full_action)
        .count();

    let sf4_pivotal = p2_records
        .iter()
        .filter(|r| r.shift_f4_engine_pivotal)
        .count();
    let se2_pivotal = p2_records
        .iter()
        .filter(|r| r.shift_e2_engine_pivotal)
        .count();
    let sboth_pivotal = p2_records
        .iter()
        .filter(|r| r.shift_f4_e2_engine_pivotal)
        .count();

    // True-vs-shifted delta distributions.
    let mut f4_delta_dist: BTreeMap<i64, usize> = BTreeMap::new();
    let mut e2_delta_dist: BTreeMap<i64, usize> = BTreeMap::new();
    for r in &p2_records {
        *f4_delta_dist.entry(r.shifted_f4 - r.true_f4).or_insert(0) += 1;
        *e2_delta_dist.entry(r.shifted_e2 - r.true_e2).or_insert(0) += 1;
    }

    // Identity digest over the frozen context list.
    let identities_json = serde_json::to_vec(
        &p2_records
            .iter()
            .map(|r| {
                (
                    &r.observation_hash,
                    &r.visible_history_hash,
                    &r.information_set_hash,
                )
            })
            .collect::<Vec<_>>(),
    )
    .unwrap();
    let contexts_identity_sha256 = {
        let mut hasher = Sha256::new();
        hasher.update(b"effective-splendor-m45a-p2-context-identities-v1\0");
        hasher.update(&identities_json);
        hex_encode(hasher.finalize().as_slice())
    };

    // Global uniqueness assertion.
    {
        let mut seen = HashSet::new();
        for r in &p2_records {
            let key = format!(
                "{}:{}:{}",
                r.observation_hash, r.visible_history_hash, r.information_set_hash
            );
            if !seen.insert(key) {
                eprintln!(
                    "FAIL CLOSED: duplicate identity triple in selected contexts (context {})",
                    r.context_idx
                );
                return 1;
            }
        }
    }

    let p2_summary = serde_json::json!({
        "format": "effective-splendor-m45a-p2-behavior-audit",
        "version": 1,
        "identity_method": "authoritative information-set triple (observation_hash, visible_history_hash, information_set_hash) via build_information_set_v1; identical pipeline to analyze-replay-player-view source metadata",
        "decision_ply_convention": "decision_ply = zero_based_step_index + 1; early = 1..=20, mid = 21..=45, late = 46+",
        "margin_definition": "top-1 utility minus runner-up utility for the root actor, ties broken by canonical action order; best action asserted equal to analyzer selected action",
        "audited_contexts_count": 180,
        "source_reproduction": {
            "checks": 180,
            "reproduced": source_reproductions_ok,
            "rate": 1.0,
            "pass": true
        },
        "quota_matrix_composition": {
            "shift_f4": {"early": 20, "mid": 20, "late": 20, "total": 60},
            "shift_e2": {"early": 20, "mid": 20, "late": 20, "total": 60},
            "shift_f4_e2": {"early": 20, "mid": 20, "late": 20, "total": 60},
            "total": 180
        },
        "contexts_identity_sha256": contexts_identity_sha256,
        "disagreement_rates_vs_full": {
            "shift_f4_vs_full": (sf4_disagreements as f64) / n_ctx,
            "shift_e2_vs_full": (se2_disagreements as f64) / n_ctx,
            "shift_f4_e2_vs_full": (sboth_disagreements as f64) / n_ctx
        },
        "disagreement_counts": {
            "shift_f4_vs_full": sf4_disagreements,
            "shift_e2_vs_full": se2_disagreements,
            "shift_f4_e2_vs_full": sboth_disagreements
        },
        "engine_pivotal_behavior_rates": {
            "shift_f4": (sf4_pivotal as f64) / n_ctx,
            "shift_e2": (se2_pivotal as f64) / n_ctx,
            "shift_f4_e2": (sboth_pivotal as f64) / n_ctx
        },
        "engine_pivotal_counts": {
            "shift_f4": sf4_pivotal,
            "shift_e2": se2_pivotal,
            "shift_f4_e2": sboth_pivotal
        },
        "f4_delta_distribution": f4_delta_dist,
        "e2_delta_distribution": e2_delta_dist,
        "contexts": p2_records
    });

    std::fs::write(&p2_out, serde_json::to_string_pretty(&p2_summary).unwrap()).unwrap();
    println!("P2 Audit Summary written to {:?}", p2_out);

    // -----------------------------------------------------------------------
    // P3: Residual Bonus-Vector Capacity Audit
    // -----------------------------------------------------------------------
    println!("\nStarting P3 Residual Capacity Audit on all 384 replays...");

    // Per-context record of (bonus_vector, C, F1, CORE, E2, F3, F4).
    struct CtxInfo {
        bonus_vector: [u8; 5],
        c: i64,
        f1: i64,
        core: i64,
        e2: i64,
        f3: i64,
        f4: i64,
    }

    let mut contexts: Vec<CtxInfo> = Vec::new();
    let mut p3_unique_keys = HashSet::new();

    for &pairing_id in &pairings {
        for seed in 5_800_000..5_800_064 {
            let block_idx = seed - 5_800_000;
            for rotation in [0u8, 1] {
                let rpl_path = arena_dir
                    .join(pairing_id)
                    .join(format!("block-{block_idx:02}-seed-{seed}"))
                    .join(format!("r{rotation}"))
                    .join("match-replay.json");

                let file = File::open(&rpl_path).unwrap();
                let replay: ReplayV1 = serde_json::from_reader(file).unwrap();
                let _verified = verify_replay(&replay).unwrap();

                let (mut state, setup) = FullState::new(GameConfig {
                    player_count: replay.player_count,
                    seed: replay.seed,
                    ruleset,
                })
                .unwrap();

                let player_count = replay.player_count as usize;
                let mut histories: Vec<Vec<VisibleEvent>> = (0..player_count)
                    .map(|p| visible_events(&setup.events, Audience::Player(PlayerId(p as u8))))
                    .collect();

                for step_index in 0..replay.steps.len() {
                    let step = &replay.steps[step_index];
                    let actor = step.actor;

                    if state.phase == Phase::Main {
                        let visible_history = &histories[actor.index()];
                        let obs = state.observation(actor);
                        let probe = match analyze_player_view_attribution_v1(
                            ruleset,
                            &obs,
                            visible_history,
                            cfg,
                            AttributionProfile::Full,
                        ) {
                            Ok(p) => p,
                            Err(e) => {
                                eprintln!(
                                    "FAIL CLOSED: P3 identity probe failed at {:?} step {}: {e}",
                                    rpl_path, step_index
                                );
                                return 1;
                            }
                        };
                        let id_key = format!(
                            "{}:{}:{}",
                            observation_hash(&obs),
                            probe.visible_history_hash().as_str(),
                            probe.information_set_hash().as_str()
                        );
                        if !p3_unique_keys.contains(&id_key) {
                            p3_unique_keys.insert(id_key);

                            let player = &state.players[actor.index()];
                            let fp = family_progress_for(&state, player);
                            contexts.push(CtxInfo {
                                bonus_vector: player.bonuses,
                                c: fp.purchased_card_count,
                                f1: fp.f1_score,
                                core: fp.e1_core_engine,
                                e2: fp.e2_noble_progress,
                                f3: fp.f3_liquidity,
                                f4: fp.f4_convertibility,
                            });
                        }
                    }

                    let res = state.apply(step.action).unwrap();
                    for (p, history) in histories.iter_mut().enumerate() {
                        history.extend(visible_events(
                            &res.events,
                            Audience::Player(PlayerId(p as u8)),
                        ));
                    }
                }
            }
        }
    }

    let corpus_size = contexts.len();
    println!(
        "P3 Corpus Scanned: {} unique authoritative-identity Phase::Main root-actor decision contexts.",
        corpus_size
    );

    // Key A: K_path = (C, E2, F4).
    let mut key_a_groups: BTreeMap<(i64, i64, i64), Vec<[u8; 5]>> = BTreeMap::new();
    for ctx in &contexts {
        key_a_groups
            .entry((ctx.c, ctx.e2, ctx.f4))
            .or_default()
            .push(ctx.bonus_vector);
    }

    let key_a_collision_groups = key_a_groups
        .iter()
        .filter(|(_, vectors)| {
            let mut distinct = HashSet::new();
            for v in vectors.iter() {
                distinct.insert(*v);
            }
            distinct.len() > 1
        })
        .count();
    let key_a_contexts_in_collisions: usize = key_a_groups
        .values()
        .filter(|vectors| {
            let mut distinct = HashSet::new();
            for v in vectors.iter() {
                distinct.insert(*v);
            }
            distinct.len() > 1
        })
        .map(|v| v.len())
        .sum();

    // Key B: K_eval = (F1, CORE, E2, F3, F4).
    type EvalKey = (i64, i64, i64, i64, i64);
    let mut key_b_groups: BTreeMap<EvalKey, Vec<[u8; 5]>> = BTreeMap::new();
    for ctx in &contexts {
        key_b_groups
            .entry((ctx.f1, ctx.core, ctx.e2, ctx.f3, ctx.f4))
            .or_default()
            .push(ctx.bonus_vector);
    }

    let key_b_collision_groups = key_b_groups
        .iter()
        .filter(|(_, vectors)| {
            let mut distinct = HashSet::new();
            for v in vectors.iter() {
                distinct.insert(*v);
            }
            distinct.len() > 1
        })
        .count();
    let key_b_contexts_in_collisions: usize = key_b_groups
        .values()
        .filter(|vectors| {
            let mut distinct = HashSet::new();
            for v in vectors.iter() {
                distinct.insert(*v);
            }
            distinct.len() > 1
        })
        .map(|v| v.len())
        .sum();

    // Per-key stratum metrics (context count, distinct vectors, entropy) for
    // up to the largest groups; plus aggregate conditional entropy of the
    // bonus vector given each key.
    fn group_metrics(groups: &BTreeMap<impl Ord, Vec<[u8; 5]>>) -> (f64, usize, usize, usize, f64) {
        // Returns (conditional entropy bits, total groups, collision groups,
        // contexts in collisions, mean distinct vectors in collision groups).
        let mut total_entropy = 0.0f64;
        let mut total_contexts = 0usize;
        let mut collision_groups = 0usize;
        let mut contexts_in_collisions = 0usize;
        let mut distinct_in_collisions = 0usize;

        for vectors in groups.values() {
            let n = vectors.len();
            total_contexts += n;
            let mut counts: HashMap<[u8; 5], usize> = HashMap::new();
            for v in vectors {
                *counts.entry(*v).or_insert(0) += 1;
            }
            let k = counts.len();
            let mut h = 0.0f64;
            for &c in counts.values() {
                let p = c as f64 / n as f64;
                h -= p * p.log2();
            }
            total_entropy += (n as f64) * h;
            if k > 1 {
                collision_groups += 1;
                contexts_in_collisions += n;
                distinct_in_collisions += k;
            }
        }

        let mean_distinct = if collision_groups > 0 {
            distinct_in_collisions as f64 / collision_groups as f64
        } else {
            0.0
        };
        (
            total_entropy / total_contexts as f64,
            groups.len(),
            collision_groups,
            contexts_in_collisions,
            mean_distinct,
        )
    }

    let (key_a_cond_entropy, key_a_total_groups, _, _, key_a_mean_distinct) =
        group_metrics(&key_a_groups);
    let (key_b_cond_entropy, key_b_total_groups, _, _, key_b_mean_distinct) =
        group_metrics(&key_b_groups);

    // Distribution of distinct-vector counts inside collision groups (Key B).
    let mut key_b_collision_size_dist: BTreeMap<usize, usize> = BTreeMap::new();
    for vectors in key_b_groups.values() {
        let mut distinct = HashSet::new();
        for v in vectors.iter() {
            distinct.insert(*v);
        }
        let k = distinct.len();
        if k > 1 {
            *key_b_collision_size_dist.entry(k).or_insert(0) += 1;
        }
    }
    let mut key_a_collision_size_dist: BTreeMap<usize, usize> = BTreeMap::new();
    for vectors in key_a_groups.values() {
        let mut distinct = HashSet::new();
        for v in vectors.iter() {
            distinct.insert(*v);
        }
        let k = distinct.len();
        if k > 1 {
            *key_a_collision_size_dist.entry(k).or_insert(0) += 1;
        }
    }

    // Corpus identity digest.
    let mut sorted_p3_keys: Vec<String> = p3_unique_keys.into_iter().collect();
    sorted_p3_keys.sort_unstable();
    let corpus_identity_sha256 = {
        let mut hasher = Sha256::new();
        hasher.update(b"effective-splendor-m45a-p3-corpus-identities-v1\0");
        for key in &sorted_p3_keys {
            hasher.update(key.as_bytes());
            hasher.update(b"\n");
        }
        hex_encode(hasher.finalize().as_slice())
    };

    let p3_summary = serde_json::json!({
        "format": "effective-splendor-m45a-p3-residual-capacity-audit",
        "version": 1,
        "identity_method": "authoritative information-set triple (observation_hash, visible_history_hash, information_set_hash) via build_information_set_v1; identical pipeline to analyze-replay-player-view source metadata",
        "corpus_scope": "Phase::Main root-actor decision contexts across all 384 accepted Arena replays, deduplicated by authoritative identity triple",
        "corpus_unique_contexts": corpus_size,
        "corpus_identity_sha256": corpus_identity_sha256,
        "key_a_path_conditioned": {
            "key_definition": "K_path = (C, E2, F4)",
            "total_groups": key_a_total_groups,
            "collision_groups": key_a_collision_groups,
            "contexts_in_collision_groups": key_a_contexts_in_collisions,
            "collision_fraction": key_a_contexts_in_collisions as f64 / corpus_size as f64,
            "conditional_entropy_bits": key_a_cond_entropy,
            "mean_distinct_vectors_in_collision_groups": key_a_mean_distinct,
            "collision_group_size_distribution": key_a_collision_size_dist,
        },
        "key_b_eval_conditioned": {
            "key_definition": "K_eval = (F1, CORE, E2, F3, F4)",
            "total_groups": key_b_total_groups,
            "collision_groups": key_b_collision_groups,
            "contexts_in_collision_groups": key_b_contexts_in_collisions,
            "collision_fraction": key_b_contexts_in_collisions as f64 / corpus_size as f64,
            "conditional_entropy_bits": key_b_cond_entropy,
            "mean_distinct_vectors_in_collision_groups": key_b_mean_distinct,
            "collision_group_size_distribution": key_b_collision_size_dist,
        },
        "formal_meaning": "Collision groups demonstrate that the current static evaluator is many-to-one with respect to the player's full bonus vector: some color-structure information remains unrepresented even after conditioning on the scalar progress summaries. This is a representation result only; it does not prove the omitted vector information would improve playing strength, and other game-state variables can co-vary inside the groups. No causal inference from collision statistics.",
    });

    std::fs::write(&p3_out, serde_json::to_string_pretty(&p3_summary).unwrap()).unwrap();
    println!("P3 Audit Summary written to {:?}", p3_out);

    println!("\n=== Audits Completed Successfully ===");
    0
}

fn hex_encode(bytes: &[u8]) -> String {
    let mut out = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        out.push_str(&format!("{b:02x}"));
    }
    out
}
