//! M49A decline diagnostics: lockstep trace of two checkpoints on the frozen
//! validation cohort. Read-only measurement; no training, no Canonical access.
//!
//! Contract `m49a_validation_trace_v1` replays two existing weight files on the
//! SAME 64 validation seeds with the SAME per-seed policy RNG construction and
//! 1e-4 tie threshold as `m49a_eval_command::evaluate_weights_on_validation`.
//! Both policies act on identical environments in lockstep until their first
//! differing action; each then finishes independently with its own RNG stream
//! (identical to a standalone evaluation rollout of that checkpoint).
//!
//! Fail-closed audit: on the full 64-seed cohort the trace's aggregate
//! success/failures/J_val/successful-mean must reproduce the frozen evaluator
//! exactly for both checkpoints, otherwise the command exits non-zero and
//! writes no report.

use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};

use serde::Serialize;
use sha2::{Digest, Sha256};
use splendor_agent::{AgentPolicy, DecisionContext, StableRng};
use splendor_analysis::m49a_collector::validation_seeds_v1;
use splendor_analysis::solo15::{
    Solo15Environment, Solo15Outcome, DEFAULT_MAX_MAIN_TURNS, SOLO15_CONTRACT_ID_V1,
};
use splendor_core::{observation_hash, Action, Observation, Phase};
use splendor_learning::{encode_combined_v2, EfficiencyQWeightsV1};

use crate::atomic_output::commit_single;
use crate::m49a_eval_command::{
    evaluate_weights_on_validation, load_weights_with_sha256, QPolicy, ValidationMetrics,
};

const EXIT_USAGE: i32 = 2;
const TRACE_CONTRACT: &str = "m49a_validation_trace_v1";
const EVALUATION_CONTRACT: &str = "m49a_validation_64_cap100_rng_ordinal_v1";
const FEATURE_WIDTH: usize = 428;
const SUPPORT_ROW_BYTES: usize = FEATURE_WIDTH * 4;
const FULL_COHORT: usize = 64;

#[derive(Serialize)]
struct WeightsRef {
    path: PathBuf,
    sha256: String,
}

#[derive(Serialize)]
struct SupportInfo {
    path: PathBuf,
    sha256: String,
    logged_rows: usize,
}

/// Byte-exact set of logged current-side 428-float feature rows.
struct SupportSet {
    rows: HashSet<Vec<u8>>,
    logged_rows: usize,
}

impl SupportSet {
    fn load(path: &Path) -> Result<Self, String> {
        let bytes = fs::read(path).map_err(|e| format!("read {}: {e}", path.display()))?;
        if bytes.is_empty() || bytes.len() % SUPPORT_ROW_BYTES != 0 {
            return Err(format!(
                "support file {} is not a non-empty multiple of {} bytes",
                path.display(),
                SUPPORT_ROW_BYTES
            ));
        }
        let logged_rows = bytes.len() / SUPPORT_ROW_BYTES;
        let mut rows = HashSet::with_capacity(logged_rows);
        for chunk in bytes.chunks_exact(SUPPORT_ROW_BYTES) {
            rows.insert(chunk.to_vec());
        }
        Ok(Self { rows, logged_rows })
    }

    fn contains_feature(&self, feature: &[f32]) -> bool {
        if feature.len() != FEATURE_WIDTH {
            return false;
        }
        let mut key = Vec::with_capacity(SUPPORT_ROW_BYTES);
        for value in feature {
            key.extend_from_slice(&value.to_le_bytes());
        }
        self.rows.contains(&key)
    }
}

fn action_kind(action: &Action) -> &'static str {
    match action {
        Action::TakeTokens { .. } => "take_tokens",
        Action::BuyMarket { .. } => "buy_market",
        Action::BuyReserved { .. } => "buy_reserved",
        Action::ReserveMarket { .. } => "reserve_market",
        Action::ReserveDeck { .. } => "reserve_deck",
        Action::ChooseNoble { .. } => "choose_noble",
        Action::Pass => "pass",
    }
}

#[derive(Clone, Copy, Default, Serialize)]
struct ActionHistogram {
    take_tokens: usize,
    buy_market: usize,
    buy_reserved: usize,
    reserve_market: usize,
    reserve_deck: usize,
    choose_noble: usize,
    pass: usize,
}

impl ActionHistogram {
    fn record(&mut self, action: &Action) {
        match action {
            Action::TakeTokens { .. } => self.take_tokens += 1,
            Action::BuyMarket { .. } => self.buy_market += 1,
            Action::BuyReserved { .. } => self.buy_reserved += 1,
            Action::ReserveMarket { .. } => self.reserve_market += 1,
            Action::ReserveDeck { .. } => self.reserve_deck += 1,
            Action::ChooseNoble { .. } => self.choose_noble += 1,
            Action::Pass => self.pass += 1,
        }
    }
}

fn outcome_name(outcome: Solo15Outcome) -> &'static str {
    match outcome {
        Solo15Outcome::Running => "running",
        Solo15Outcome::Reached15 => "reached_15",
        Solo15Outcome::Stalled => "stalled",
        Solo15Outcome::TurnCap => "turn_cap",
    }
}

fn phase_name(phase: Phase) -> &'static str {
    match phase {
        Phase::Main => "main",
        Phase::ChooseNoble => "choose_noble",
        Phase::GameOver => "game_over",
    }
}

#[derive(Serialize)]
struct PrefixStep {
    ply: u32,
    main_turns: u32,
    phase: &'static str,
    legal_count: usize,
    chosen_kind: &'static str,
    q_a_chosen: f32,
    q_b_chosen: f32,
    best_q_a: f32,
    second_best_q_a: f32,
    tie_count_a: usize,
    best_q_b: f32,
    second_best_q_b: f32,
    tie_count_b: usize,
}

#[derive(Serialize)]
struct DivergenceAction {
    action: Action,
    kind: &'static str,
    q_a: f32,
    q_b: f32,
    in_d2_support: Option<bool>,
    chosen_by: &'static str,
}

#[derive(Serialize)]
struct Divergence {
    ply: u32,
    main_turns: u32,
    phase: &'static str,
    remaining_main_turns: u32,
    legal_count: usize,
    observation_hash: String,
    action_a: Action,
    action_b: Action,
    q_a_of_action_a: f32,
    q_b_of_action_a: f32,
    q_a_of_action_b: f32,
    q_b_of_action_b: f32,
    best_q_a: f32,
    second_best_q_a: f32,
    tie_count_a: usize,
    best_q_b: f32,
    second_best_q_b: f32,
    tie_count_b: usize,
    actions: Vec<DivergenceAction>,
}

#[derive(Serialize)]
struct SeedTrace {
    ordinal: usize,
    seed: u64,
    outcome_a: &'static str,
    outcome_b: &'static str,
    main_turns_to_15_a: Option<u32>,
    main_turns_to_15_b: Option<u32>,
    decision_plies_a: u32,
    decision_plies_b: u32,
    final_prestige_a: u8,
    final_prestige_b: u8,
    purchased_a: usize,
    purchased_b: usize,
    reserved_a: usize,
    reserved_b: usize,
    nobles_a: usize,
    nobles_b: usize,
    action_histogram_a: ActionHistogram,
    action_histogram_b: ActionHistogram,
    diverged: bool,
    divergence: Option<Divergence>,
    shared_prefix: Vec<PrefixStep>,
}

#[derive(Serialize)]
struct MetricsSnapshot {
    success_count: usize,
    failures: usize,
    j_val: f64,
    successful_mean_turns: Option<f64>,
}

impl MetricsSnapshot {
    fn from_metrics(m: &ValidationMetrics) -> Self {
        Self {
            success_count: m.success_count,
            failures: m.failures,
            j_val: m.j_val,
            successful_mean_turns: Some(m.successful_mean_turns),
        }
    }

    fn from_traces(traces: &[SeedTrace], side: Side) -> Self {
        let mut successes = 0usize;
        let mut failures = 0usize;
        let mut turn_sum = 0u64;
        for trace in traces {
            let (outcome, turns) = match side {
                Side::A => (trace.outcome_a, trace.main_turns_to_15_a),
                Side::B => (trace.outcome_b, trace.main_turns_to_15_b),
            };
            if outcome == "reached_15" {
                successes += 1;
                turn_sum += u64::from(turns.expect("success records main turns"));
            } else {
                failures += 1;
            }
        }
        let n = traces.len() as f64;
        let j_val = (turn_sum as f64 + (failures as f64) * 101.0) / n;
        Self {
            success_count: successes,
            failures,
            j_val,
            successful_mean_turns: if successes == 0 {
                None
            } else {
                Some(turn_sum as f64 / successes as f64)
            },
        }
    }

    fn matches(&self, other: &Self) -> bool {
        self.success_count == other.success_count
            && self.failures == other.failures
            && (self.j_val - other.j_val).abs() < 1e-9
            && match (self.successful_mean_turns, other.successful_mean_turns) {
                (None, None) => true,
                (Some(x), Some(y)) => (x - y).abs() < 1e-9,
                _ => false,
            }
    }
}

#[derive(Clone, Copy)]
enum Side {
    A,
    B,
}

#[derive(Serialize)]
struct Audit {
    evaluator_a: MetricsSnapshot,
    evaluator_b: MetricsSnapshot,
    trace_a: MetricsSnapshot,
    trace_b: MetricsSnapshot,
    matches: bool,
}

#[derive(Serialize)]
struct Aggregate {
    seed_count: usize,
    success_a: usize,
    failures_a: usize,
    j_val_a: f64,
    successful_mean_turns_a: Option<f64>,
    success_b: usize,
    failures_b: usize,
    j_val_b: f64,
    successful_mean_turns_b: Option<f64>,
    diverged_seeds: usize,
    identical_seeds: usize,
    a_success_b_failure: Vec<u64>,
    a_failure_b_success: Vec<u64>,
    divergence_ply_min: Option<u32>,
    divergence_ply_median: Option<u32>,
    divergence_ply_max: Option<u32>,
}

#[derive(Serialize)]
struct TraceReport {
    trace_contract: &'static str,
    evaluation_contract: &'static str,
    weights_a: WeightsRef,
    weights_b: WeightsRef,
    validation_seeds: Vec<u64>,
    max_main_turns: u32,
    support: Option<SupportInfo>,
    seeds: Vec<SeedTrace>,
    aggregate: Aggregate,
    audit: Option<Audit>,
}

struct RolloutTail {
    outcome: Solo15Outcome,
    main_turns_to_15: Option<u32>,
    decision_plies: u32,
    final_prestige: u8,
    purchased: usize,
    reserved: usize,
    nobles: usize,
}

fn choose_with_policy(
    weights: &EfficiencyQWeightsV1,
    observation: &Observation,
    legal: &[Action],
    remaining: u32,
    max_turns: u32,
    request_id: u64,
    rng: &mut StableRng,
) -> Result<Action, String> {
    let mut policy = QPolicy {
        weights,
        remaining_turns: remaining,
        max_turns,
    };
    let obs_hash = observation_hash(observation);
    let context = DecisionContext {
        observation: observation.clone(),
        visible_history: &[],
        legal_actions: legal,
        meta: splendor_agent::PublicRequestMeta {
            game_id: SOLO15_CONTRACT_ID_V1.to_string(),
            recipient_seat: splendor_core::PlayerId(0),
            request_id,
            observation_hash: obs_hash,
        },
        rng,
    };
    policy.choose_action(context).map_err(|e| e)
}

/// (best, second-best, tie count at 1e-4) over Q values in legal order.
fn best_stats(q_values: &[f32]) -> (f32, f32, usize) {
    let mut best = f32::INFINITY;
    let mut second = f32::INFINITY;
    for &q in q_values {
        if q < best {
            second = best;
            best = q;
        } else if q < second {
            second = q;
        }
    }
    let tie_count = q_values
        .iter()
        .filter(|q| (**q - best).abs() < 1e-4)
        .count();
    (best, second, tie_count)
}

fn finish_rollout(
    env: &mut Solo15Environment,
    weights: &EfficiencyQWeightsV1,
    rng: &mut StableRng,
    histogram: &mut ActionHistogram,
    seed: u64,
) -> Result<RolloutTail, String> {
    let max_turns = DEFAULT_MAX_MAIN_TURNS;
    while !env.is_terminal() {
        let legal = env.legal_actions();
        if legal.is_empty() {
            return Err(format!(
                "seed {seed}: nonterminal state has no legal actions"
            ));
        }
        let remaining = max_turns.saturating_sub(env.main_turns());
        let action = match env.phase() {
            Phase::Main | Phase::ChooseNoble => {
                let observation = env.observation();
                choose_with_policy(
                    weights,
                    &observation,
                    &legal,
                    remaining,
                    max_turns,
                    env.decision_plies() as u64,
                    rng,
                )?
            }
            Phase::GameOver => return Err(format!("seed {seed}: nonterminal GameOver phase")),
        };
        histogram.record(&action);
        env.step(action)
            .map_err(|e| format!("seed {seed}: step error: {e}"))?;
    }
    summary_tail(env)
}

fn summary_tail(env: &Solo15Environment) -> Result<RolloutTail, String> {
    let summary = env.summary();
    Ok(RolloutTail {
        outcome: summary.outcome,
        main_turns_to_15: summary.main_turns_to_15,
        decision_plies: summary.decision_plies_to_15,
        final_prestige: summary.final_prestige,
        purchased: summary.purchased_count,
        reserved: summary.reserved_count,
        nobles: summary.nobles_count,
    })
}

#[allow(clippy::too_many_arguments)]
fn trace_one_seed(
    ordinal: usize,
    seed: u64,
    weights_a: &EfficiencyQWeightsV1,
    weights_b: &EfficiencyQWeightsV1,
    support: Option<&SupportSet>,
) -> Result<SeedTrace, String> {
    let max_turns = DEFAULT_MAX_MAIN_TURNS;
    let mut env_a = Solo15Environment::with_max_main_turns(seed, max_turns)
        .map_err(|e| format!("seed {seed} init error: {e}"))?;
    let mut env_b = Solo15Environment::with_max_main_turns(seed, max_turns)
        .map_err(|e| format!("seed {seed} init error: {e}"))?;
    let mut rng_a = StableRng::new(0x5010_1515_0000_0000_u64.wrapping_add(ordinal as u64));
    let mut rng_b = StableRng::new(0x5010_1515_0000_0000_u64.wrapping_add(ordinal as u64));
    let mut histogram_a = ActionHistogram::default();
    let mut histogram_b = ActionHistogram::default();
    let mut shared_prefix: Vec<PrefixStep> = Vec::new();
    let mut divergence: Option<Divergence> = None;

    while !env_a.is_terminal() {
        let legal = env_a.legal_actions();
        if legal.is_empty() {
            return Err(format!(
                "seed {seed}: nonterminal state has no legal actions"
            ));
        }
        let remaining = max_turns.saturating_sub(env_a.main_turns());
        let phase = env_a.phase();
        let observation = match phase {
            Phase::Main | Phase::ChooseNoble => env_a.observation(),
            Phase::GameOver => return Err(format!("seed {seed}: nonterminal GameOver phase")),
        };
        // Lockstep invariant: both environments hold identical state here.
        if observation_hash(&observation) != observation_hash(&env_b.observation())
            || env_b.main_turns() != env_a.main_turns()
            || env_b.decision_plies() != env_a.decision_plies()
            || env_b.legal_actions() != legal
        {
            return Err(format!("seed {seed}: lockstep state desynchronization"));
        }

        // Q table under both checkpoints, in legal order.
        let mut features: Vec<Vec<f32>> = Vec::with_capacity(legal.len());
        let mut q_a_values: Vec<f32> = Vec::with_capacity(legal.len());
        let mut q_b_values: Vec<f32> = Vec::with_capacity(legal.len());
        for action in &legal {
            let feature = encode_combined_v2(&observation, action, remaining, max_turns)
                .map_err(|e| format!("seed {seed}: encode action: {e}"))?;
            q_a_values.push(weights_a.forward(&feature));
            q_b_values.push(weights_b.forward(&feature));
            features.push(feature);
        }
        let (best_q_a, second_best_q_a, tie_count_a) = best_stats(&q_a_values);
        let (best_q_b, second_best_q_b, tie_count_b) = best_stats(&q_b_values);

        let ply = env_a.decision_plies();
        let request_id = ply as u64;
        let action_a = choose_with_policy(
            weights_a,
            &observation,
            &legal,
            remaining,
            max_turns,
            request_id,
            &mut rng_a,
        )?;
        let action_b = choose_with_policy(
            weights_b,
            &observation,
            &legal,
            remaining,
            max_turns,
            request_id,
            &mut rng_b,
        )?;

        let q_a_chosen = q_a_values[legal
            .iter()
            .position(|a| *a == action_a)
            .expect("chosen action is legal")];
        let q_b_chosen = q_b_values[legal
            .iter()
            .position(|a| *a == action_a)
            .expect("chosen action is legal")];
        shared_prefix.push(PrefixStep {
            ply,
            main_turns: env_a.main_turns(),
            phase: phase_name(phase),
            legal_count: legal.len(),
            chosen_kind: action_kind(&action_a),
            q_a_chosen,
            q_b_chosen,
            best_q_a,
            second_best_q_a,
            tie_count_a,
            best_q_b,
            second_best_q_b,
            tie_count_b,
        });
        histogram_a.record(&action_a);
        histogram_b.record(&action_b);

        if action_a == action_b {
            env_a
                .step(action_a)
                .map_err(|e| format!("seed {seed}: step error: {e}"))?;
            env_b
                .step(action_b)
                .map_err(|e| format!("seed {seed}: step error: {e}"))?;
            continue;
        }

        // First divergence: record the full action table, then split rollouts.
        let position_a = legal
            .iter()
            .position(|a| *a == action_a)
            .expect("chosen action is legal");
        let position_b = legal
            .iter()
            .position(|a| *a == action_b)
            .expect("chosen action is legal");
        let actions = legal
            .iter()
            .enumerate()
            .map(|(index, action)| DivergenceAction {
                action: *action,
                kind: action_kind(action),
                q_a: q_a_values[index],
                q_b: q_b_values[index],
                in_d2_support: support.map(|s| s.contains_feature(&features[index])),
                chosen_by: if index == position_a {
                    "a"
                } else if index == position_b {
                    "b"
                } else {
                    "neither"
                },
            })
            .collect();
        divergence = Some(Divergence {
            ply,
            main_turns: env_a.main_turns(),
            phase: phase_name(phase),
            remaining_main_turns: remaining,
            legal_count: legal.len(),
            observation_hash: observation_hash(&observation).to_string(),
            action_a,
            action_b,
            q_a_of_action_a: q_a_values[position_a],
            q_b_of_action_a: q_b_values[position_a],
            q_a_of_action_b: q_a_values[position_b],
            q_b_of_action_b: q_b_values[position_b],
            best_q_a,
            second_best_q_a,
            tie_count_a,
            best_q_b,
            second_best_q_b,
            tie_count_b,
            actions,
        });
        env_a
            .step(action_a)
            .map_err(|e| format!("seed {seed}: step error: {e}"))?;
        env_b
            .step(action_b)
            .map_err(|e| format!("seed {seed}: step error: {e}"))?;
        break;
    }

    let tail_a = finish_rollout(&mut env_a, weights_a, &mut rng_a, &mut histogram_a, seed)?;
    let tail_b = finish_rollout(&mut env_b, weights_b, &mut rng_b, &mut histogram_b, seed)?;

    Ok(SeedTrace {
        ordinal,
        seed,
        outcome_a: outcome_name(tail_a.outcome),
        outcome_b: outcome_name(tail_b.outcome),
        main_turns_to_15_a: tail_a.main_turns_to_15,
        main_turns_to_15_b: tail_b.main_turns_to_15,
        decision_plies_a: tail_a.decision_plies,
        decision_plies_b: tail_b.decision_plies,
        final_prestige_a: tail_a.final_prestige,
        final_prestige_b: tail_b.final_prestige,
        purchased_a: tail_a.purchased,
        purchased_b: tail_b.purchased,
        reserved_a: tail_a.reserved,
        reserved_b: tail_b.reserved,
        nobles_a: tail_a.nobles,
        nobles_b: tail_b.nobles,
        action_histogram_a: histogram_a,
        action_histogram_b: histogram_b,
        diverged: divergence.is_some(),
        divergence,
        shared_prefix,
    })
}

fn sha256_file(path: &Path) -> Result<String, String> {
    let mut hasher = Sha256::new();
    let file = fs::File::open(path).map_err(|e| format!("open {}: {e}", path.display()))?;
    let mut reader = std::io::BufReader::new(file);
    let mut buffer = [0u8; 1 << 20];
    loop {
        let read = std::io::Read::read(&mut reader, &mut buffer)
            .map_err(|e| format!("read {}: {e}", path.display()))?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    Ok(hex::encode(hasher.finalize()))
}

struct Args {
    weights_a: PathBuf,
    weights_b: PathBuf,
    out_json: PathBuf,
    support_x: Option<PathBuf>,
    max_seeds: usize,
}

fn parse_args(args: &[String]) -> Result<Args, String> {
    let mut flags = std::collections::BTreeMap::new();
    let mut i = 0;
    while i < args.len() {
        let flag = args[i].as_str();
        if ![
            "--weights-a",
            "--weights-b",
            "--out-json",
            "--support-x",
            "--max-seeds",
        ]
        .contains(&flag)
        {
            return Err(format!("unknown flag `{flag}`"));
        }
        let value = args
            .get(i + 1)
            .filter(|s| !s.is_empty() && !s.starts_with("--"))
            .ok_or_else(|| format!("{flag} requires a value"))?;
        if flags.insert(flag, value.to_string()).is_some() {
            return Err(format!("duplicate flag `{flag}`"));
        }
        i += 2;
    }
    let max_seeds = match flags.get("--max-seeds") {
        None => FULL_COHORT,
        Some(raw) => raw.parse::<usize>().map_err(|_| "malformed --max-seeds")?,
    };
    if !(1..=FULL_COHORT).contains(&max_seeds) {
        return Err(format!("--max-seeds must be 1..={FULL_COHORT}"));
    }
    Ok(Args {
        weights_a: PathBuf::from(
            flags
                .get("--weights-a")
                .ok_or("missing required --weights-a")?,
        ),
        weights_b: PathBuf::from(
            flags
                .get("--weights-b")
                .ok_or("missing required --weights-b")?,
        ),
        out_json: PathBuf::from(
            flags
                .get("--out-json")
                .ok_or("missing required --out-json")?,
        ),
        support_x: flags.get("--support-x").map(PathBuf::from),
        max_seeds,
    })
}

fn run(args: Args) -> Result<(), String> {
    if args.out_json.exists() {
        return Err(format!(
            "refusing to overwrite {:?}",
            args.out_json.display()
        ));
    }
    let out_json = args.out_json.clone();
    let (weights_a, sha_a) = load_weights_with_sha256(&args.weights_a)?;
    let (weights_b, sha_b) = load_weights_with_sha256(&args.weights_b)?;

    let all_seeds = validation_seeds_v1();
    let seeds: Vec<u64> = all_seeds[..args.max_seeds].to_vec();
    let support = match &args.support_x {
        None => None,
        Some(path) => {
            let set = SupportSet::load(path)?;
            let info = SupportInfo {
                path: path.clone(),
                sha256: sha256_file(path)?,
                logged_rows: set.logged_rows,
            };
            println!(
                "loaded support set: {} logged rows from {}",
                set.logged_rows,
                path.display()
            );
            Some((set, info))
        }
    };
    let support_info = support.as_ref().map(|(_, info)| SupportInfo {
        path: info.path.clone(),
        sha256: info.sha256.clone(),
        logged_rows: info.logged_rows,
    });

    let mut traces = Vec::with_capacity(seeds.len());
    for (ordinal, &seed) in seeds.iter().enumerate() {
        let trace = trace_one_seed(
            ordinal,
            seed,
            &weights_a,
            &weights_b,
            support.as_ref().map(|(set, _)| set),
        )?;
        println!(
            "seed {} (ordinal {}): a={}, b={}, diverged={}",
            seed, ordinal, trace.outcome_a, trace.outcome_b, trace.diverged
        );
        traces.push(trace);
    }

    let trace_a = MetricsSnapshot::from_traces(&traces, Side::A);
    let trace_b = MetricsSnapshot::from_traces(&traces, Side::B);
    let mut divergence_plies: Vec<u32> = traces
        .iter()
        .filter_map(|t| t.divergence.as_ref().map(|d| d.ply))
        .collect();
    divergence_plies.sort_unstable();
    let a_success_b_failure: Vec<u64> = traces
        .iter()
        .filter(|t| t.outcome_a == "reached_15" && t.outcome_b != "reached_15")
        .map(|t| t.seed)
        .collect();
    let a_failure_b_success: Vec<u64> = traces
        .iter()
        .filter(|t| t.outcome_a != "reached_15" && t.outcome_b == "reached_15")
        .map(|t| t.seed)
        .collect();
    let aggregate = Aggregate {
        seed_count: traces.len(),
        success_a: trace_a.success_count,
        failures_a: trace_a.failures,
        j_val_a: trace_a.j_val,
        successful_mean_turns_a: trace_a.successful_mean_turns,
        success_b: trace_b.success_count,
        failures_b: trace_b.failures,
        j_val_b: trace_b.j_val,
        successful_mean_turns_b: trace_b.successful_mean_turns,
        diverged_seeds: divergence_plies.len(),
        identical_seeds: traces.len() - divergence_plies.len(),
        a_success_b_failure,
        a_failure_b_success,
        divergence_ply_min: divergence_plies.first().copied(),
        divergence_ply_median: divergence_plies.get(divergence_plies.len() / 2).copied(),
        divergence_ply_max: divergence_plies.last().copied(),
    };

    // Fail-closed audit against the frozen evaluator on the full cohort only.
    let audit = if traces.len() == FULL_COHORT {
        let evaluator_a =
            MetricsSnapshot::from_metrics(&evaluate_weights_on_validation(&weights_a)?);
        let evaluator_b =
            MetricsSnapshot::from_metrics(&evaluate_weights_on_validation(&weights_b)?);
        let matches = trace_a.matches(&evaluator_a) && trace_b.matches(&evaluator_b);
        if !matches {
            return Err(format!(
                "trace audit mismatch: a {:?} vs evaluator {:?}; b {:?} vs evaluator {:?}",
                (trace_a.success_count, trace_a.failures, trace_a.j_val),
                (
                    evaluator_a.success_count,
                    evaluator_a.failures,
                    evaluator_a.j_val
                ),
                (trace_b.success_count, trace_b.failures, trace_b.j_val),
                (
                    evaluator_b.success_count,
                    evaluator_b.failures,
                    evaluator_b.j_val
                ),
            ));
        }
        Some(Audit {
            evaluator_a,
            evaluator_b,
            trace_a,
            trace_b,
            matches,
        })
    } else {
        None
    };

    let report = TraceReport {
        trace_contract: TRACE_CONTRACT,
        evaluation_contract: EVALUATION_CONTRACT,
        weights_a: WeightsRef {
            path: args.weights_a,
            sha256: sha_a,
        },
        weights_b: WeightsRef {
            path: args.weights_b,
            sha256: sha_b,
        },
        validation_seeds: seeds,
        max_main_turns: DEFAULT_MAX_MAIN_TURNS,
        support: support_info,
        seeds: traces,
        aggregate,
        audit,
    };
    let json = serde_json::to_string_pretty(&report).map_err(|e| e.to_string())? + "\n";
    if let Some(parent) = out_json.parent().filter(|p| !p.as_os_str().is_empty()) {
        std::fs::create_dir_all(parent).map_err(|e| format!("create output parent: {e}"))?;
    }
    commit_single(&out_json, &json).map_err(|e| format!("publish trace report: {e}"))?;
    println!(
        "trace complete: {} seeds, {} diverged, a {}/{} successes, b {}/{} successes",
        report.aggregate.seed_count,
        report.aggregate.diverged_seeds,
        report.aggregate.success_a,
        report.aggregate.seed_count,
        report.aggregate.success_b,
        report.aggregate.seed_count,
    );
    Ok(())
}

/// `m49a-trace-validation --weights-a A --weights-b B --out-json FILE`
/// replays both checkpoints on the frozen validation cohort in lockstep and
/// records per-seed outcomes, first divergence, action Q tables, optional
/// D2 support flags, shared-prefix Q values, and action histograms.
pub fn run_m49a_trace_validation(args: &[String]) -> i32 {
    let args = match parse_args(args) {
        Ok(a) => a,
        Err(e) => {
            eprintln!("usage error: {e}");
            return EXIT_USAGE;
        }
    };
    match run(args) {
        Ok(()) => 0,
        Err(e) => {
            eprintln!("error: {e}");
            1
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn zero_weights() -> EfficiencyQWeightsV1 {
        EfficiencyQWeightsV1 {
            fc1_w: vec![vec![0.0; FEATURE_WIDTH]; 256],
            fc1_b: vec![0.0; 256],
            ln1_w: vec![1.0; 256],
            ln1_b: vec![0.0; 256],
            fc2_w: vec![vec![0.0; 256]; 128],
            fc2_b: vec![0.0; 128],
            fc3_w: vec![vec![0.0; 128]; 1],
            fc3_b: vec![0.0; 1],
        }
    }

    fn feature_sensitive_weights() -> EfficiencyQWeightsV1 {
        // Constant inputs are erased by LayerNorm, so route a single hidden
        // unit through an action-side feature (index 368, the first action
        // feature) to make Q vary across actions, unlike zero_weights.
        let mut weights = zero_weights();
        weights.fc1_w[0][368] = 1.0;
        weights.fc2_w[0][0] = 1.0;
        weights.fc3_w[0][0] = 1.0;
        weights
    }

    #[test]
    fn support_set_matches_exact_rows_only() {
        let dir = std::env::temp_dir().join("m49a_trace_support_test");
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("support.f32");
        let row_a: Vec<f32> = (0..FEATURE_WIDTH).map(|i| i as f32 * 0.25).collect();
        let row_b = vec![7.5f32; FEATURE_WIDTH];
        let mut bytes = Vec::new();
        for value in row_a.iter().chain(row_b.iter()) {
            bytes.extend_from_slice(&value.to_le_bytes());
        }
        std::fs::write(&path, &bytes).unwrap();
        let set = SupportSet::load(&path).unwrap();
        assert_eq!(set.logged_rows, 2);
        assert!(set.contains_feature(&row_a));
        assert!(set.contains_feature(&row_b));
        let mut other = row_a.clone();
        other[100] += 0.125;
        assert!(!set.contains_feature(&other));

        let bad = dir.join("bad.f32");
        std::fs::write(&bad, [0u8; 7]).unwrap();
        assert!(SupportSet::load(&bad).is_err());
    }

    #[test]
    fn identical_weights_never_diverge() {
        // One seed is enough for the structural invariants; the full-cohort
        // fidelity is enforced by the production run's fail-closed audit gate.
        let weights = zero_weights();
        let seeds = validation_seeds_v1();
        for (ordinal, &seed) in seeds.iter().take(1).enumerate() {
            let trace = trace_one_seed(ordinal, seed, &weights, &weights, None).unwrap();
            assert!(!trace.diverged);
            assert!(trace.divergence.is_none());
            assert_eq!(trace.outcome_a, trace.outcome_b);
            assert_eq!(trace.main_turns_to_15_a, trace.main_turns_to_15_b);
            assert_eq!(trace.purchased_a, trace.purchased_b);
            assert_eq!(trace.reserved_a, trace.reserved_b);
            assert!(!trace.shared_prefix.is_empty());
            for step in &trace.shared_prefix {
                assert!((step.q_a_chosen - step.q_b_chosen).abs() < 1e-6);
            }
            let total_a: usize = step_total(&trace.action_histogram_a);
            let total_b: usize = step_total(&trace.action_histogram_b);
            assert_eq!(total_a, trace.decision_plies_a as usize);
            assert_eq!(total_b, trace.decision_plies_b as usize);
            assert_eq!(total_a, total_b);
        }
    }

    #[test]
    fn divergent_weights_keep_invariants() {
        let weights_a = zero_weights();
        let weights_b = feature_sensitive_weights();
        let seeds = validation_seeds_v1();
        for (ordinal, &seed) in seeds.iter().take(1).enumerate() {
            let trace = trace_one_seed(ordinal, seed, &weights_a, &weights_b, None).unwrap();
            if let Some(divergence) = &trace.divergence {
                assert_ne!(divergence.action_a, divergence.action_b);
                assert!(divergence.actions.iter().any(|a| a.chosen_by == "a"));
                assert!(divergence.actions.iter().any(|a| a.chosen_by == "b"));
                assert!(divergence.actions.iter().all(|a| a.q_a.is_finite()));
                assert!(divergence.actions.iter().all(|a| a.q_b.is_finite()));
                assert_eq!(divergence.actions.len(), divergence.legal_count);
                assert_eq!(
                    divergence.legal_count,
                    trace.shared_prefix.last().unwrap().legal_count
                );
                let last = trace.shared_prefix.last().unwrap();
                assert_eq!(last.ply, divergence.ply);
            } else {
                assert_eq!(trace.outcome_a, trace.outcome_b);
            }
            let total_a: usize = step_total(&trace.action_histogram_a);
            assert_eq!(total_a, trace.decision_plies_a as usize);
            let total_b: usize = step_total(&trace.action_histogram_b);
            assert_eq!(total_b, trace.decision_plies_b as usize);
        }
    }

    fn step_total(histogram: &ActionHistogram) -> usize {
        histogram.take_tokens
            + histogram.buy_market
            + histogram.buy_reserved
            + histogram.reserve_market
            + histogram.reserve_deck
            + histogram.choose_noble
            + histogram.pass
    }
}
