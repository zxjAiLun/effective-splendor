//! S2 census harness: batched in-process three-policy disagreement census
//! over one verified S0 replay (DESIGN_V2 `82fc400`).
//!
//! For every eligible context (`Phase::Main`, `>= 2` legal actions) this
//! emits one JSONL row with:
//! - the heuristic score-optimal SET `H*` (never a counterfactual
//!   tie-break action) and its size;
//! - the frozen n1 and M07 actions (recomputed on the context);
//! - parity fields binding the recorded action to the mover's policy;
//! - stage bin, market flags, identity triple, actor role.
//!
//! No agent/search behavior is changed; this is analysis tooling.

use std::io::Write;

use splendor_agent::heuristic_term_scores;
use splendor_core::{Action, Audience, Phase};
use splendor_determinization_agent::DeterminizationAgentPolicyV1;
use splendor_imperfect_search::RootDeterminizationConfigV1;
use splendor_replay::{verify_replay_trace, ReplayV1};
use splendor_search::{canonical_order, SearchConfigV1};

use crate::arena_command::{print_stdout, wants_help};
use splendor_agent::{AgentPolicy, DecisionContext, PublicRequestMeta, StableRng};

const CENSUS_USAGE: &str = "Usage: splendor s2-census --input <replay.json> --out <rows.jsonl> \
--game-id <id> --heuristic-seed <u64> --sample-seed <u64> [--emit-terms]

Reconstruct every eligible (Phase::Main, >=2 legal actions) context of the
verified replay and emit one JSONL row per context with the heuristic
score-optimal set and the frozen n1 / M07 actions, plus parity fields.
Appends to --out. Deterministic; no behavior changes to any policy.
";

const N1_NODES: u64 = 1;
const N2000_NODES: u64 = 2000;

pub fn run_s2_census(args: &[String]) -> i32 {
    if wants_help(args) {
        print_stdout(CENSUS_USAGE);
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
    let mut heuristic_seed: Option<String> = None;
    let mut sample_seed: Option<String> = None;
    let mut emit_terms = false;
    let mut i = 0;
    while i < args.len() {
        let arg = args[i].as_str();
        let slot = match arg {
            "--input" => &mut input,
            "--out" => &mut out,
            "--game-id" => &mut game_id,
            "--heuristic-seed" => &mut heuristic_seed,
            "--sample-seed" => &mut sample_seed,
            "--emit-terms" => {
                if emit_terms {
                    return Err("--emit-terms given more than once".to_owned());
                }
                emit_terms = true;
                i += 1;
                continue;
            }
            other if other.starts_with('-') => {
                return Err(format!("unknown flag `{other}`"))
            }
            other => return Err(format!("unexpected positional argument `{other}`")),
        };
        let value = args.get(i + 1).ok_or_else(|| format!("{arg} requires a value"))?;
        if slot.is_some() {
            return Err(format!("{arg} given more than once"));
        }
        *slot = Some(value.clone());
        i += 2;
    }
    let input = input.ok_or("--input is required")?;
    let out = out.ok_or("--out is required")?;
    let game_id = game_id.ok_or("--game-id is required")?;
    let heuristic_seed: u64 = heuristic_seed
        .as_ref()
        .and_then(|v| v.parse().ok())
        .ok_or("--heuristic-seed must be a u64")?;
    let sample_seed: u64 = sample_seed
        .as_ref()
        .and_then(|v| v.parse().ok())
        .ok_or("--sample-seed must be a u64")?;

    let n1_config = RootDeterminizationConfigV1 {
        sample_seed,
        sample_count: 4,
        continuation_search: SearchConfigV1 {
            max_depth_turns: 1,
            max_nodes: N1_NODES,
        },
    };
    let m07_config = RootDeterminizationConfigV1 {
        sample_seed,
        sample_count: 4,
        continuation_search: SearchConfigV1 {
            max_depth_turns: 1,
            max_nodes: N2000_NODES,
        },
    };
    n1_config.validate().map_err(|e| format!("n1 config: {e}"))?;
    m07_config.validate().map_err(|e| format!("m07 config: {e}"))?;

    let replay_text = std::fs::read_to_string(&input)
        .map_err(|error| format!("cannot read replay {input}: {error}"))?;
    let replay: ReplayV1 = serde_json::from_str(&replay_text)
        .map_err(|error| format!("invalid replay: {error}"))?;
    let verified =
        verify_replay_trace(&replay).map_err(|error| format!("replay verification: {error}"))?;

    // Final outcome from the replay: winner seats.
    let winners: Vec<u8> = replay
        .result
        .winners
        .iter()
        .map(|w| u8::from(*w))
        .collect();

    let mut rows_file = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&out)
        .map_err(|error| format!("cannot open rows file {out}: {error}"))?;

    let mut n1_policy = DeterminizationAgentPolicyV1::new(n1_config).map_err(|e| e.to_string())?;
    let mut m07_policy =
        DeterminizationAgentPolicyV1::new(m07_config).map_err(|e| e.to_string())?;

    for position in &verified.positions {
        let state = &position.state;
        if state.phase != Phase::Main {
            continue;
        }
        let legal = canonical_order(&state.legal_actions());
        if legal.len() < 2 {
            continue;
        }
        let actor = position.recorded_actor;
        let observation = state.observation(actor);
        let visible_history = splendor_core::visible_events(&state.log, Audience::Player(actor));

        // Heuristic score-optimal set (deterministic; no RNG).
        let term_scores = heuristic_term_scores(&observation, &legal);
        let totals: Vec<i64> = term_scores.iter().map(|t| t.total()).collect();
        let max_score = *totals.iter().max().expect("non-empty legal actions");
        let h_star: Vec<Action> = legal
            .iter()
            .zip(totals.iter())
            .filter(|(_, s)| **s == max_score)
            .map(|(a, _)| *a)
            .collect();

        // Frozen search actions (fresh policies per context: both are
        // stateless given their fixed configs; recomputation must equal the
        // recorded action for their own mover contexts — the parity fields
        // below bind this and the Python layer asserts it).
        let obs_hash = splendor_core::observation_hash(&observation).clone();
        let mut decide = |policy: &mut DeterminizationAgentPolicyV1| {
            let mut rng = StableRng::new(0);
            let context = DecisionContext {
                observation: state.observation(actor),
                visible_history: &visible_history,
                legal_actions: &legal,
                meta: PublicRequestMeta {
                    game_id: game_id.clone(),
                    recipient_seat: actor,
                    request_id: 1,
                    observation_hash: obs_hash.clone(),
                },
                rng: &mut rng,
            };
            policy.choose_action(context)
        };
        let a_n1 = decide(&mut n1_policy)
            .map_err(|e| format!("n1 decision failed at ply {}: {e}", position.ply))?;
        let a_m07 = decide(&mut m07_policy)
            .map_err(|e| format!("m07 decision failed at ply {}: {e}", position.ply))?;

        let stage = if position.ply <= 20 {
            "early"
        } else if position.ply <= 45 {
            "mid"
        } else {
            "late"
        };
        let gold_available = observation.public.bank.gold > 0;
        let any_buy_legal = legal
            .iter()
            .any(|a| matches!(a, Action::BuyMarket { .. } | Action::BuyReserved { .. }));

        let row = serde_json::json!({
            "game_id": game_id,
            "ply": position.ply,
            "actor_seat": actor.index(),
            "recorded_action": position.recorded_action,
            "stage": stage,
            "winners": winners,
            "legal_action_count": legal.len(),
            "h_star": h_star,
            "h_star_size": h_star.len(),
            "max_score": max_score,
            "a_n1": a_n1,
            "a_m07": a_m07,
            "gold_available": gold_available,
            "any_buy_legal": any_buy_legal,
        });
        writeln!(rows_file, "{row}")
            .map_err(|error| format!("write row: {error}"))?;

        if emit_terms {
            // Term-gap rows at STRICT divergences for BOTH search policies
            // (the Python layer filters to the game's actual opponent):
            // |H*| == 1 and the given search action differs from the unique
            // H action. Signed per-term deltas h - s with the score gap.
            let h_action = row["h_star"][0].clone();
            let term_of = |action: &serde_json::Value, want: &Action| -> Option<serde_json::Value> {
                // find the term vector for `want` among legal actions
                let idx = legal.iter().position(|a| a == want)?;
                let _ = action;
                serde_json::to_value(&term_scores[idx]).ok()
            };
            let h_terms = match term_of(&h_action, &h_star[0]) {
                Some(v) => v,
                None => continue,
            };
            for (label, s_action) in [("n1", &a_n1), ("m07", &a_m07)] {
                if *s_action == h_star[0] {
                    continue;
                }
                let s_terms = match term_of(&serde_json::Value::Null, s_action) {
                    Some(v) => v,
                    None => continue,
                };
                let mut delta = serde_json::Map::new();
                for field in [
                    "category_base", "prestige", "noble_gain", "noble_direct",
                    "bonus_usefulness", "cost_efficiency", "deficit_reduction",
                    "new_target", "return_penalty", "gold_value", "reserve_proximity",
                    "reserve_gold", "reserve_blind_gold",
                ] {
                    let hv = h_terms[field].as_i64().unwrap_or(0);
                    let sv = s_terms[field].as_i64().unwrap_or(0);
                    delta.insert(field.to_string(), serde_json::json!(hv - sv));
                }
                let score_gap = max_score
                    - totals
                        .iter()
                        .zip(legal.iter())
                        .find(|(_, a)| **a == *s_action)
                        .map(|(s, _)| *s)
                        .unwrap_or(max_score);
                let gap_row = serde_json::json!({
                    "game_id": game_id,
                    "ply": position.ply,
                    "actor_seat": actor.index(),
                    "stage": stage,
                    "policy": label,
                    "h_action": h_star[0],
                    "s_action": s_action,
                    "delta": delta,
                    "score_gap": score_gap,
                });
                writeln!(rows_file, "{gap_row}")
                    .map_err(|error| format!("write gap row: {error}"))?;
            }
        }
    }
    Ok(())
}
