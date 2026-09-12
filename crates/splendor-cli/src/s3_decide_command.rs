//! `splendor s3-decide` — S3 Stage-A fixed-context decision probe
//! (DESIGN_V2 @ 92af7bb): reconstruct a verified replay context, compute
//! the frozen proposals (a_H via scoring, a_n1/a_M07 via their policies),
//! run the full S3 decision with per-stage timing, and emit one JSON row.

use std::io::Write;
use std::time::Instant;

use splendor_agent::AgentPolicy;
use splendor_core::{Audience, Ruleset};
use splendor_determinization_agent::s3_rollout;
use splendor_determinization_agent::s3_rollout::{
    loo_agreement, s3_decide, s3_m07_config, s3_n1_config, S3Path,
};
use splendor_determinization_agent::DeterminizationAgentPolicyV1;
use splendor_replay::{verify_replay_trace, ReplayV1};
use splendor_search::canonical_order;

use crate::arena_command::{print_stdout, wants_help};
use splendor_agent::{DecisionContext, PublicRequestMeta, StableRng};

const USAGE: &str = "Usage: splendor s3-decide --input <replay.json> --ply <k> --out <rows.jsonl>

Reconstruct the verified decision context at <ply>, compute the frozen
proposals and the full S3 rollout decision (fixed workload, shared worlds,
completion-gated integer scoring), and append one JSONL telemetry row with
per-stage timings. Deterministic; no wall-clock input to the decision.
";

pub fn run_s3_decide(args: &[String]) -> i32 {
    if wants_help(args) {
        print_stdout(USAGE);
        return 0;
    }
    match run(args) {
        Ok(()) => 0,
        Err(message) => {
            let mut stderr = std::io::stderr().lock();
            let _ = writeln!(stderr, "error: {message}");
            let _ = stderr.flush();
            1
        }
    }
}

fn run(args: &[String]) -> Result<(), String> {
    let mut input: Option<String> = None;
    let mut ply: Option<String> = None;
    let mut out: Option<String> = None;
    let mut i = 0;
    while i < args.len() {
        let arg = args[i].as_str();
        let slot = match arg {
            "--input" => &mut input,
            "--ply" => &mut ply,
            "--out" => &mut out,
            other if other.starts_with('-') => return Err(format!("unknown flag `{other}`")),
            other => return Err(format!("unexpected positional argument `{other}`")),
        };
        let value = args
            .get(i + 1)
            .ok_or_else(|| format!("{arg} requires a value"))?;
        if slot.is_some() {
            return Err(format!("{arg} given more than once"));
        }
        *slot = Some(value.clone());
        i += 2;
    }
    let input = input.ok_or("--input is required")?;
    let ply: u32 = ply
        .as_ref()
        .and_then(|v| v.parse().ok())
        .ok_or("--ply must be a u32")?;
    let out = out.ok_or("--out is required")?;

    let replay_text = std::fs::read_to_string(&input)
        .map_err(|error| format!("cannot read replay {input}: {error}"))?;
    let replay: ReplayV1 =
        serde_json::from_str(&replay_text).map_err(|error| format!("invalid replay: {error}"))?;
    let verified =
        verify_replay_trace(&replay).map_err(|error| format!("replay verification: {error}"))?;
    let position = verified
        .positions
        .iter()
        .find(|p| p.ply == ply)
        .ok_or_else(|| format!("ply {ply} out of range"))?;

    let actor = position.recorded_actor;
    let observation = position.state.observation(actor);
    let visible_history =
        splendor_core::visible_events(&position.state.log, Audience::Player(actor));
    let legal = canonical_order(&position.state.legal_actions());
    if legal.is_empty() {
        return Err("no legal actions".to_owned());
    }
    // Root identity is derived INSIDE s3_decide from the information-set
    // hash (never a file path). The game identity here is telemetry only.
    let game_identity = format!("seed{}|{}", replay.seed, ply);

    let mut timings = serde_json::Map::new();
    let t_all = Instant::now();

    // Proposals: a_n1 and a_m07 (their cost is part of the measured
    // full-decision pipeline).
    let t_n1 = Instant::now();
    let mut n1_policy =
        DeterminizationAgentPolicyV1::new(s3_n1_config()).map_err(|e| e.to_string())?;
    let a_n1 = {
        let mut rng = StableRng::new(0);
        let obs_hash = splendor_core::observation_hash(&observation).clone();
        n1_policy
            .choose_action(DecisionContext {
                observation: observation.clone(),
                visible_history: &visible_history,
                legal_actions: &legal,
                meta: PublicRequestMeta {
                    game_id: game_identity.clone(),
                    recipient_seat: actor,
                    request_id: 1,
                    observation_hash: obs_hash,
                },
                rng: &mut rng,
            })
            .map_err(|e| e.to_string())?
    };
    timings.insert(
        "n1_ms".into(),
        serde_json::json!(t_n1.elapsed().as_millis()),
    );

    let t_m07 = Instant::now();
    let mut m07_policy =
        DeterminizationAgentPolicyV1::new(s3_m07_config()).map_err(|e| e.to_string())?;
    let a_m07 = {
        let mut rng = StableRng::new(0);
        let obs_hash = splendor_core::observation_hash(&observation).clone();
        m07_policy
            .choose_action(DecisionContext {
                observation: observation.clone(),
                visible_history: &visible_history,
                legal_actions: &legal,
                meta: PublicRequestMeta {
                    game_id: game_identity.clone(),
                    recipient_seat: actor,
                    request_id: 1,
                    observation_hash: obs_hash,
                },
                rng: &mut rng,
            })
            .map_err(|e| e.to_string())?
    };
    timings.insert(
        "m07_ms".into(),
        serde_json::json!(t_m07.elapsed().as_millis()),
    );

    // Full S3 decision (a_H generation + worlds + rollouts + selection).
    let t_decide = Instant::now();
    let decision = s3_decide(
        &observation,
        &visible_history,
        &legal,
        a_n1,
        a_m07,
        Ruleset::base_v1(),
    )?;
    // a_H for the LOO tie rule: the unique optimum when eligible; the
    // canonical-first of H* otherwise (LOO only applies to complete
    // comparisons, where H* is unique by eligibility).
    let hs = s3_rollout::h_star(&observation, &legal);
    let a_h = hs[0];
    let loo = loo_agreement(&decision, a_h);
    timings.insert(
        "s3_decide_ms".into(),
        serde_json::json!(t_decide.elapsed().as_millis()),
    );
    timings.insert(
        "full_ms".into(),
        serde_json::json!(t_all.elapsed().as_millis()),
    );

    let path = match decision.path {
        S3Path::HeuristicFastPath => "heuristic_fast_path",
        S3Path::RootTieKeptA_H => "root_tie_kept_a_h",
        S3Path::ProposalsAgreed => "proposals_agreed",
        S3Path::PlyCapFallback => "ply_cap_fallback",
        S3Path::RolloutComparison => "rollout_comparison",
    };
    let row = serde_json::json!({
        "replay_seed": replay.seed,
        "source": input,
        "ply": ply,
        "actor_seat": actor.index(),
        "legal_action_count": legal.len(),
        "root_identity": decision.root_identity,
        "a_n1": a_n1,
        "a_m07": a_m07,
        "chosen": decision.action,
        "path": path,
        "candidate_set_size": decision.candidate_set_size,
        "score2": decision.score2,
        "per_world_score2": decision.per_world_score2,
        "loo_agreement": loo,
        "timings_ms": timings,
    });
    let mut file = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&out)
        .map_err(|error| format!("cannot open rows file {out}: {error}"))?;
    writeln!(file, "{row}").map_err(|error| format!("write row: {error}"))?;
    Ok(())
}
