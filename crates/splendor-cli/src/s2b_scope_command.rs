//! S2b scope measurement harness (DESIGN_V2 @ ff7a4f1): batched fixed-context
//! analysis over one verified replay's n1 mover contexts.
//!
//! For every eligible Main-phase context (Phase::Main, >=2 legal actions)
//! where the recorded actor is the n1 seat, this emits one JSONL row with
//! the base n1 action, the heuristic optimal set, the candidate action, and
//! the trigger flag — all computed on the SAME reconstructed context
//! (fixed-context pointwise comparison; never trajectory replay).
//!
//! The harness takes the n1 seat index so the caller can target whichever
//! seat played n1 in that replay.

use std::io::Write;

use splendor_agent::heuristic_term_scores;
use splendor_core::{Action, Audience, Phase};
use splendor_determinization_agent::DeterminizationAgentPolicyV1;
use splendor_imperfect_search::RootDeterminizationConfigV1;
use splendor_replay::{verify_replay_trace, ReplayV1};
use splendor_search::{canonical_order, SearchConfigV1};

use crate::arena_command::{print_stdout, wants_help};
use splendor_agent::{AgentPolicy, DecisionContext, PublicRequestMeta, StableRng};

const SCOPE_USAGE: &str = "Usage: splendor s2b-scope --input <replay.json> --out <rows.jsonl> \
--game-id <id> --n1-seat <u8>

Reconstruct every eligible Main-phase context of the verified replay where
the recorded actor is the n1 seat, and emit one JSONL row per context with
base_n1 / h_star / candidate / trigger — computed on the SAME fixed context
(fixed-context pointwise scope measurement; never trajectory replay).
Appends to --out. Deterministic.
";

pub fn run_s2b_scope(args: &[String]) -> i32 {
    if wants_help(args) {
        print_stdout(SCOPE_USAGE);
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
    let mut out: Option<String> = None;
    let mut game_id: Option<String> = None;
    let mut n1_seat: Option<String> = None;
    let mut i = 0;
    while i < args.len() {
        let arg = args[i].as_str();
        let slot = match arg {
            "--input" => &mut input,
            "--out" => &mut out,
            "--game-id" => &mut game_id,
            "--n1-seat" => &mut n1_seat,
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
    let out = out.ok_or("--out is required")?;
    let game_id = game_id.ok_or("--game-id is required")?;
    let n1_seat: u8 = n1_seat
        .as_ref()
        .and_then(|v| v.parse().ok())
        .ok_or("--n1-seat must be a u8")?;

    // The EXACT frozen n1 config (the scope harness is n1-only by design).
    let config = RootDeterminizationConfigV1 {
        sample_seed: 20_260_703,
        sample_count: 4,
        continuation_search: SearchConfigV1 {
            max_depth_turns: 1,
            max_nodes: 1,
        },
    };
    config.validate().map_err(|e| format!("n1 config: {e}"))?;

    let replay_text = std::fs::read_to_string(&input)
        .map_err(|error| format!("cannot read replay {input}: {error}"))?;
    let replay: ReplayV1 =
        serde_json::from_str(&replay_text).map_err(|error| format!("invalid replay: {error}"))?;
    let verified =
        verify_replay_trace(&replay).map_err(|error| format!("replay verification: {error}"))?;

    let mut rows_file = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&out)
        .map_err(|error| format!("cannot open rows file {out}: {error}"))?;

    let winners: Vec<u8> = replay.result.winners.iter().map(|w| u8::from(*w)).collect();

    let mut policy = DeterminizationAgentPolicyV1::new(config).map_err(|e| e.to_string())?;

    for position in &verified.positions {
        if position.state.phase != Phase::Main {
            continue;
        }
        let actor = position.recorded_actor;
        if actor.index() != usize::from(n1_seat) {
            continue;
        }
        let legal = canonical_order(&position.state.legal_actions());
        if legal.len() < 2 {
            continue;
        }
        let observation = position.state.observation(actor);
        let visible_history =
            splendor_core::visible_events(&position.state.log, Audience::Player(actor));

        // Fixed context: base n1, H*, candidate — all on THIS context.
        let obs_hash = splendor_core::observation_hash(&observation).clone();
        let mut rng = StableRng::new(0);
        let context = DecisionContext {
            observation: observation.clone(),
            visible_history: &visible_history,
            legal_actions: &legal,
            meta: PublicRequestMeta {
                game_id: game_id.clone(),
                recipient_seat: actor,
                request_id: 1,
                observation_hash: obs_hash,
            },
            rng: &mut rng,
        };
        let base = policy
            .choose_action(context)
            .map_err(|e| format!("n1 decision failed at ply {}: {e}", position.ply))?;

        let totals: Vec<i64> = heuristic_term_scores(&observation, &legal)
            .iter()
            .map(|t| t.total())
            .collect();
        let max = *totals.iter().max().expect("non-empty legal actions");
        let h_star: Vec<Action> = legal
            .iter()
            .zip(totals.iter())
            .filter(|(_, s)| **s == max)
            .map(|(a, _)| *a)
            .collect();

        // The frozen overlay rule (identical logic to N1BuyOverlayPolicy).
        let (candidate, triggered) = match base {
            Action::TakeTokens { .. } if h_star.len() == 1 => match h_star[0] {
                Action::BuyMarket { .. } => (h_star[0], true),
                _ => (base, false),
            },
            _ => (base, false),
        };

        let row = serde_json::json!({
            "game_id": game_id,
            "ply": position.ply,
            "actor_seat": actor.index(),
            "recorded_action": position.recorded_action,
            "base_n1": base,
            "h_star": h_star,
            "h_star_size": h_star.len(),
            "candidate": candidate,
            "triggered": triggered,
            "legal_action_count": legal.len(),
            "winners": winners,
        });
        writeln!(rows_file, "{row}").map_err(|error| format!("write row: {error}"))?;
    }
    Ok(())
}
