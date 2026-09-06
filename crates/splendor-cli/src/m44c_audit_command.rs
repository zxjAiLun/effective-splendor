//! M44C P2 Scale Audit and P3 Vector Heterogeneity Audit Command.
//!
//! Enforces (Closure Repair 1):
//! - P2: Exact 200-context quota matrix across 3 pairings and 3 game stages.
//! - P2: Authoritative context identity = (observation_hash,
//!   visible_history_hash, information_set_hash) computed via the same
//!   `build_information_set_v1` pipeline used by `analyze-replay-player-view`.
//! - P2: Decision-ply staging with `decision_ply = zero_based_ply + 1`
//!   (early 1..=20, mid 21..=45, late 46+).
//! - P2: Top-1 vs runner-up margin computed from sorted root utilities, not
//!   canonical array positions.
//! - P2: Deterministic global deduplication, 200/200 source action
//!   reproduction (fail closed), and full/scale evaluations.
//! - P3: Arena-state corpus scan deduplicated by the same authoritative
//!   identity triple; root-actor Phase::Main contexts only.
//! - P3: In-stratum bonus vector diversity, Shannon entropy, F4/E2
//!   observational distributions.

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

/// Stage classification on 1-based decision ply (Closure Repair 1):
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

/// Authoritative context identity triple. The observation hash comes from
/// `splendor_core::observation_hash`; the visible-history and
/// information-set hashes come from the same
/// `splendor_belief::build_information_set_v1` pipeline used by the
/// `analyze-replay-player-view` command (via
/// `analyze_player_view_attribution_v1`).
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

/// Top-1 vs runner-up margin computed from actual root utilities.
///
/// Best action = highest root-player utility with earliest canonical index
/// breaking ties (identical tie-break to `choose_best_action`). Runner-up =
/// second-highest utility (a different canonical action; when several actions
/// tie for second the canonical-first among them is used, matching aggregate
/// order). Returns (best_action, runner_up_action, margin). Fails closed if
/// fewer than two legal actions exist.
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

    let mut best_idx = 0usize;
    let mut best_value = i64::MIN;
    for (idx, agg) in aggregates.iter().enumerate() {
        let value = *agg
            .utility_sum_by_player
            .get(player_index)
            .ok_or_else(|| format!("utility shape mismatch for player {player_index}"))?;
        if idx == 0 || value > best_value {
            best_value = value;
            best_idx = idx;
        }
    }

    // Runner-up: highest utility among actions other than best_idx; ties
    // resolved by canonical order (first encountered wins because we only
    // replace on strictly greater value).
    let mut runner_idx = usize::MAX;
    let mut runner_value = i64::MIN;
    for (idx, agg) in aggregates.iter().enumerate() {
        if idx == best_idx {
            continue;
        }
        let value = *agg
            .utility_sum_by_player
            .get(player_index)
            .ok_or_else(|| format!("utility shape mismatch for player {player_index}"))?;
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

    let margin = best_value - runner_value;
    Ok((best_action, aggregates[runner_idx].action, margin))
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct P2ContextRecord {
    pub context_idx: usize,
    pub pairing_id: String,
    pub seed: u64,
    pub rotation: u8,
    /// 0-based step index into the replay file.
    pub step_index: usize,
    /// 1-based decision ply used for staging (Closure Repair 1).
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
    pub full_action: Action,
    pub full_margin: i64,
    pub scale25_action: Action,
    pub scale25_margin: i64,
    pub scale50_action: Action,
    pub scale50_margin: i64,
    pub scale88_action: Action,
    pub scale88_margin: i64,
    pub scale25_engine_pivotal: bool,
    pub scale50_engine_pivotal: bool,
    pub scale88_engine_pivotal: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct P3StratumMetrics {
    pub c_val: i64,
    pub context_count: usize,
    pub distinct_vectors_count: usize,
    pub shannon_entropy_bits: f64,
    pub vector_frequencies: BTreeMap<String, usize>,
    pub f4_mean: f64,
    pub f4_std: f64,
    pub f4_min: i64,
    pub f4_max: i64,
    pub e2_mean: f64,
    pub e2_std: f64,
    pub e2_min: i64,
    pub e2_max: i64,
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

pub fn run_m44c_audit(args: &[String]) -> i32 {
    let arena_dir = if let Some(pos) = args.iter().position(|a| a == "--arena-dir") {
        PathBuf::from(&args[pos + 1])
    } else {
        PathBuf::from("local-artifacts/m44c-arena")
    };

    let p2_out = if let Some(pos) = args.iter().position(|a| a == "--p2-out") {
        PathBuf::from(&args[pos + 1])
    } else {
        arena_dir.join("m44c-common-state-scale-audit.json")
    };

    let p3_out = if let Some(pos) = args.iter().position(|a| a == "--p3-out") {
        PathBuf::from(&args[pos + 1])
    } else {
        arena_dir.join("m44c-vector-heterogeneity-audit.json")
    };

    println!("Starting M44C Audits (P2 & P3, Closure Repair 1)...");
    println!("Arena Directory: {:?}", arena_dir);

    let pairings = [
        "engine_scale_25_vs_full",
        "engine_scale_50_vs_full",
        "engine_scale_88_vs_full",
    ];

    let ruleset = Ruleset::base_v1();
    let cfg = n1_config();

    // -----------------------------------------------------------------------
    // P2: Exact 200-Context Quota Matrix (authoritative identity)
    // -----------------------------------------------------------------------
    // Quota matrix:
    // Scale25: Early 23, Mid 22, Late 22 -> 67
    // Scale50: Early 22, Mid 23, Late 22 -> 67
    // Scale88: Early 22, Mid 22, Late 22 -> 66
    let target_quotas: HashMap<(&'static str, &'static str), usize> = [
        (("engine_scale_25_vs_full", "early"), 23),
        (("engine_scale_25_vs_full", "mid"), 22),
        (("engine_scale_25_vs_full", "late"), 22),
        (("engine_scale_50_vs_full", "early"), 22),
        (("engine_scale_50_vs_full", "mid"), 23),
        (("engine_scale_50_vs_full", "late"), 22),
        (("engine_scale_88_vs_full", "early"), 22),
        (("engine_scale_88_vs_full", "mid"), 22),
        (("engine_scale_88_vs_full", "late"), 22),
    ]
    .into_iter()
    .collect();

    let mut current_counts: HashMap<(&'static str, &'static str), usize> = HashMap::new();
    let mut selected_contexts: Vec<ScannedContext> = Vec::new();
    let mut global_seen_identities = HashSet::new();

    // Iterate over pairings
    for &pairing_id in &pairings {
        let p_candidate_profile = pairing_id.replace("_vs_full", "");
        let _primary_attr_profile: AttributionProfile = p_candidate_profile.parse().unwrap();

        for &stage in &["early", "mid", "late"] {
            let cell_target = *target_quotas.get(&(pairing_id, stage)).unwrap();

            'search_loop: for seed in 5_700_000..5_700_064 {
                let block_idx = seed - 5_700_000;
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

                    // Maintain per-player cumulative visible histories so that
                    // each step's identity probe sees exactly the transcript
                    // the acting player has observed up to that decision.
                    let player_count = replay.player_count as usize;
                    let mut histories: Vec<Vec<VisibleEvent>> = (0..player_count)
                        .map(|p| visible_events(&setup.events, Audience::Player(PlayerId(p as u8))))
                        .collect();

                    // Replay step by step, maintaining the visible history for
                    // the acting player of each step.
                    for step_index in 0..replay.steps.len() {
                        let step = &replay.steps[step_index];
                        let actor = step.actor;
                        let decision_ply = u32::try_from(step_index).unwrap() + 1;
                        let ply_stage = stage_for_decision_ply(decision_ply);

                        let legal = state.legal_actions();
                        let is_main = state.phase == Phase::Main;
                        let eligible = is_main && legal.len() >= 2;

                        // Authoritative identity for this actor's information
                        // set, computed via the same pipeline as
                        // `analyze-replay-player-view`. The search result is
                        // discarded; only the identity hashes are consumed.
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

                        // If eligible for P2 selection in this pairing & stage:
                        let cell_count = current_counts.entry((pairing_id, stage)).or_insert(0);
                        if eligible
                            && ply_stage == stage
                            && *cell_count < cell_target
                            && !global_seen_identities.contains(&identity.composite_key())
                        {
                            global_seen_identities.insert(identity.composite_key());
                            *cell_count += 1;

                            // Determine recorded profile for this actor
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

                        // Apply action to advance state and extend every
                        // player's visible transcript with the events of this
                        // step as projected for that player.
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
        200,
        "Must select exactly 200 contexts"
    );
    println!("Successfully selected 200 contexts strictly fulfilling the quota matrix.");

    // Now evaluate each of the 200 contexts with Full, Scale25, Scale50, Scale88
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

        // 1. Analyze with FULL
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
        let (full_best, _full_runner, full_margin) =
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
        // Authoritative identity cross-check: the analysis-time hashes must
        // equal the selection-time identity triple.
        if a_full.visible_history_hash().as_str() != sc.identity.visible_history_hash
            || a_full.information_set_hash().as_str() != sc.identity.information_set_hash
        {
            eprintln!(
                "FAIL CLOSED: context {}: identity mismatch between selection and analysis",
                idx
            );
            return 1;
        }

        // 2. Analyze with SCALE 25
        let a_s25 = analyze_player_view_attribution_v1(
            ruleset,
            &obs,
            &visible_history,
            cfg,
            AttributionProfile::EngineScale25,
        )
        .unwrap();
        let res_s25 = a_s25.result();
        let s25_action = res_s25.action;
        let (_, _, s25_margin) =
            match top1_runnerup_margin(&res_s25.action_aggregates, sc.actor, &s25_action) {
                Ok(v) => v,
                Err(msg) => {
                    eprintln!(
                        "FAIL CLOSED: context {}: Scale25 margin check failed: {msg}",
                        idx
                    );
                    return 1;
                }
            };

        // 3. Analyze with SCALE 50
        let a_s50 = analyze_player_view_attribution_v1(
            ruleset,
            &obs,
            &visible_history,
            cfg,
            AttributionProfile::EngineScale50,
        )
        .unwrap();
        let res_s50 = a_s50.result();
        let s50_action = res_s50.action;
        let (_, _, s50_margin) =
            match top1_runnerup_margin(&res_s50.action_aggregates, sc.actor, &s50_action) {
                Ok(v) => v,
                Err(msg) => {
                    eprintln!(
                        "FAIL CLOSED: context {}: Scale50 margin check failed: {msg}",
                        idx
                    );
                    return 1;
                }
            };

        // 4. Analyze with SCALE 88
        let a_s88 = analyze_player_view_attribution_v1(
            ruleset,
            &obs,
            &visible_history,
            cfg,
            AttributionProfile::EngineScale88,
        )
        .unwrap();
        let res_s88 = a_s88.result();
        let s88_action = res_s88.action;
        let (_, _, s88_margin) =
            match top1_runnerup_margin(&res_s88.action_aggregates, sc.actor, &s88_action) {
                Ok(v) => v,
                Err(msg) => {
                    eprintln!(
                        "FAIL CLOSED: context {}: Scale88 margin check failed: {msg}",
                        idx
                    );
                    return 1;
                }
            };

        // Check source reproduction
        let source_action = match sc.recorded_profile.as_str() {
            "full" => full_action,
            "engine_scale_25" => s25_action,
            "engine_scale_50" => s50_action,
            "engine_scale_88" => s88_action,
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
        let s25_pivotal = full_is_engine != is_engine_action(&s25_action);
        let s50_pivotal = full_is_engine != is_engine_action(&s50_action);
        let s88_pivotal = full_is_engine != is_engine_action(&s88_action);

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
            full_action,
            full_margin,
            scale25_action: s25_action,
            scale25_margin: s25_margin,
            scale50_action: s50_action,
            scale50_margin: s50_margin,
            scale88_action: s88_action,
            scale88_margin: s88_margin,
            scale25_engine_pivotal: s25_pivotal,
            scale50_engine_pivotal: s50_pivotal,
            scale88_engine_pivotal: s88_pivotal,
        });
    }

    assert_eq!(
        source_reproductions_ok, 200,
        "Source reproduction must be 200/200"
    );
    println!("Source reproduction passed: 200 / 200 exact matches (100.0%).");

    // Compute P2 summary statistics
    let n_ctx = 200.0;
    let s25_disagreements = p2_records
        .iter()
        .filter(|r| r.scale25_action != r.full_action)
        .count();
    let s50_disagreements = p2_records
        .iter()
        .filter(|r| r.scale50_action != r.full_action)
        .count();
    let s88_disagreements = p2_records
        .iter()
        .filter(|r| r.scale88_action != r.full_action)
        .count();

    let s25_pivotal_count = p2_records
        .iter()
        .filter(|r| r.scale25_engine_pivotal)
        .count();
    let s50_pivotal_count = p2_records
        .iter()
        .filter(|r| r.scale50_engine_pivotal)
        .count();
    let s88_pivotal_count = p2_records
        .iter()
        .filter(|r| r.scale88_engine_pivotal)
        .count();

    // Identity digest over the frozen context list (sorted by selection order,
    // which is deterministic given the fixed walk).
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
        hasher.update(b"effective-splendor-m44c-p2-context-identities-v1\0");
        hasher.update(&identities_json);
        hex_encode(hasher.finalize().as_slice())
    };

    // Global uniqueness assertion over identity triples.
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
        "format": "effective-splendor-m44c-p2-common-state-scale-audit",
        "version": 2,
        "closure_repair": 1,
        "identity_method": "authoritative information-set triple (observation_hash, visible_history_hash, information_set_hash) via build_information_set_v1; identical pipeline to analyze-replay-player-view source metadata",
        "decision_ply_convention": "decision_ply = zero_based_step_index + 1; early = 1..=20, mid = 21..=45, late = 46+",
        "margin_definition": "top-1 utility minus runner-up utility for the root actor, ties broken by canonical action order; best action asserted equal to analyzer selected action",
        "audited_contexts_count": 200,
        "source_reproduction": {
            "checks": 200,
            "reproduced": source_reproductions_ok,
            "rate": 1.0,
            "pass": true
        },
        "quota_matrix_composition": {
            "scale25": {"early": 23, "mid": 22, "late": 22, "total": 67},
            "scale50": {"early": 22, "mid": 23, "late": 22, "total": 67},
            "scale88": {"early": 22, "mid": 22, "late": 22, "total": 66},
            "total": 200
        },
        "contexts_identity_sha256": contexts_identity_sha256,
        "disagreement_rates_vs_full": {
            "scale25_vs_full": (s25_disagreements as f64) / n_ctx,
            "scale50_vs_full": (s50_disagreements as f64) / n_ctx,
            "scale88_vs_full": (s88_disagreements as f64) / n_ctx
        },
        "disagreement_counts": {
            "scale25_vs_full": s25_disagreements,
            "scale50_vs_full": s50_disagreements,
            "scale88_vs_full": s88_disagreements
        },
        "engine_pivotal_behavior_rates": {
            "scale25": (s25_pivotal_count as f64) / n_ctx,
            "scale50": (s50_pivotal_count as f64) / n_ctx,
            "scale88": (s88_pivotal_count as f64) / n_ctx
        },
        "engine_pivotal_counts": {
            "scale25": s25_pivotal_count,
            "scale50": s50_pivotal_count,
            "scale88": s88_pivotal_count
        },
        "contexts": p2_records
    });

    std::fs::write(&p2_out, serde_json::to_string_pretty(&p2_summary).unwrap()).unwrap();
    println!("P2 Audit Summary written to {:?}", p2_out);

    // -----------------------------------------------------------------------
    // P3: Vector Heterogeneity Audit on Arena-State Corpus
    // -----------------------------------------------------------------------
    println!("\nStarting P3 Vector Heterogeneity Audit on all 384 replays...");
    let mut p3_corpus_by_c: HashMap<i64, Vec<([u8; 5], i64, i64)>> = HashMap::new();
    let mut total_p3_contexts = 0;
    let mut p3_unique_keys = HashSet::new();

    for &pairing_id in &pairings {
        for seed in 5_700_000..5_700_064 {
            let block_idx = seed - 5_700_000;
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

                // Maintain per-player cumulative visible histories so that
                // each step's identity probe sees exactly the transcript the
                // acting player has observed up to that decision.
                let player_count = replay.player_count as usize;
                let mut histories: Vec<Vec<VisibleEvent>> = (0..player_count)
                    .map(|p| visible_events(&setup.events, Audience::Player(PlayerId(p as u8))))
                    .collect();

                // Root-actor Phase::Main contexts only.
                for step_index in 0..replay.steps.len() {
                    let step = &replay.steps[step_index];
                    let actor = step.actor;

                    if state.phase == Phase::Main {
                        // Authoritative identity triple for the root actor.
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
                            total_p3_contexts += 1;

                            let player = &state.players[actor.index()];
                            let fp = family_progress_for(&state, player);
                            let c_val = fp.purchased_card_count;
                            let vector = player.bonuses;
                            let f4_val = fp.f4_convertibility;
                            let e2_val = fp.e2_noble_progress;

                            p3_corpus_by_c
                                .entry(c_val)
                                .or_default()
                                .push((vector, f4_val, e2_val));
                        }
                    }

                    // Apply action to advance state and extend every
                    // player's visible transcript with the events of this
                    // step as projected for that player.
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

    println!(
        "P3 Corpus Scanned: {} unique authoritative-identity Phase::Main root-actor decision contexts.",
        total_p3_contexts
    );

    // Group and calculate diversity metrics per observed C
    let mut observed_c_keys: Vec<i64> = p3_corpus_by_c.keys().cloned().collect();
    observed_c_keys.sort_unstable();

    let mut strata_metrics = Vec::new();

    for &c_val in &observed_c_keys {
        let entries = p3_corpus_by_c.get(&c_val).unwrap();
        let n_c = entries.len();

        let mut vec_counts: BTreeMap<[u8; 5], usize> = BTreeMap::new();
        let mut f4_vals = Vec::new();
        let mut e2_vals = Vec::new();

        for (vec, f4, e2) in entries {
            *vec_counts.entry(*vec).or_insert(0) += 1;
            f4_vals.push(*f4);
            e2_vals.push(*e2);
        }

        let distinct_k = vec_counts.len();

        // Shannon entropy: H = - sum p * log2(p)
        let mut shannon_h = 0.0;
        let mut string_vec_counts = BTreeMap::new();
        for (v, count) in &vec_counts {
            let p = (*count as f64) / (n_c as f64);
            shannon_h -= p * p.log2();
            string_vec_counts.insert(format!("{:?}", v), *count);
        }

        let f4_mean = f4_vals.iter().map(|&v| v as f64).sum::<f64>() / (n_c as f64);
        let f4_var = f4_vals
            .iter()
            .map(|&v| (v as f64 - f4_mean).powi(2))
            .sum::<f64>()
            / (n_c as f64);
        let f4_std = f4_var.sqrt();
        let f4_min = *f4_vals.iter().min().unwrap_or(&0);
        let f4_max = *f4_vals.iter().max().unwrap_or(&0);

        let e2_mean = e2_vals.iter().map(|&v| v as f64).sum::<f64>() / (n_c as f64);
        let e2_var = e2_vals
            .iter()
            .map(|&v| (v as f64 - e2_mean).powi(2))
            .sum::<f64>()
            / (n_c as f64);
        let e2_std = e2_var.sqrt();
        let e2_min = *e2_vals.iter().min().unwrap_or(&0);
        let e2_max = *e2_vals.iter().max().unwrap_or(&0);

        strata_metrics.push(P3StratumMetrics {
            c_val,
            context_count: n_c,
            distinct_vectors_count: distinct_k,
            shannon_entropy_bits: shannon_h,
            vector_frequencies: string_vec_counts,
            f4_mean,
            f4_std,
            f4_min,
            f4_max,
            e2_mean,
            e2_std,
            e2_min,
            e2_max,
        });
    }

    // Stratum internal consistency: every stratum must have >= 1 context and
    // the total across strata must equal the corpus size.
    {
        let strata_total: usize = strata_metrics.iter().map(|m| m.context_count).sum();
        if strata_total != total_p3_contexts {
            eprintln!(
                "FAIL CLOSED: P3 strata total {} != corpus size {}",
                strata_total, total_p3_contexts
            );
            return 1;
        }
    }

    // Corpus identity digest over the sorted unique identity keys.
    let mut sorted_p3_keys: Vec<String> = p3_unique_keys.into_iter().collect();
    sorted_p3_keys.sort_unstable();
    let corpus_identity_sha256 = {
        let mut hasher = Sha256::new();
        hasher.update(b"effective-splendor-m44c-p3-corpus-identities-v1\0");
        for key in &sorted_p3_keys {
            hasher.update(key.as_bytes());
            hasher.update(b"\n");
        }
        hex_encode(hasher.finalize().as_slice())
    };

    let p3_summary = serde_json::json!({
        "format": "effective-splendor-m44c-p3-vector-heterogeneity-audit",
        "version": 2,
        "closure_repair": 1,
        "identity_method": "authoritative information-set triple (observation_hash, visible_history_hash, information_set_hash) via build_information_set_v1; identical pipeline to analyze-replay-player-view source metadata",
        "corpus_scope": "Phase::Main root-actor decision contexts across all 384 accepted Arena replays, deduplicated by authoritative identity triple",
        "structural_fact_attestation": {
            "f4_affordability_reads_bonuses_vector": true,
            "e2_noble_progress_reads_bonuses_vector": true,
            "structural_color_vector_entry_confirmed": true
        },
        "disciplinary_boundary": "At fixed scalar C, the observed Arena-state corpus contains multiple bonus-vector configurations, demonstrating information loss under scalar compression. F4 and E2 also vary within C strata, but this observational variance is not attributed uniquely to bonus-vector differences because other state variables co-vary simultaneously. Color-vector information already partially enters the current evaluator through F4 and E2; any future explicit vector probe must account for overlap with these existing paths. This does NOT establish that scalar C is sufficient, only that the vector is not wholly absent from the evaluator.",
        "corpus_unique_contexts": total_p3_contexts,
        "corpus_identity_sha256": corpus_identity_sha256,
        "observed_c_strata_count": observed_c_keys.len(),
        "observed_c_values": observed_c_keys,
        "strata_metrics": strata_metrics
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
