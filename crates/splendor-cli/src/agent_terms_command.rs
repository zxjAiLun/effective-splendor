//! NDJSON adapter exposing the existing, canonical heuristic term breakdown.
//!
//! This is a local helper for agents that want structured baseline features. It
//! receives only an Observation and server-certified legal actions, never arena
//! configuration, seed, replay, or referee state.

use std::io::{self, BufRead, Write};

use serde::Deserialize;
use splendor_agent::{heuristic_term_scores, HeuristicTermScores};
use splendor_core::{Action, Observation};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    observation: Observation,
    legal_actions: Vec<Action>,
}

#[derive(serde::Serialize)]
struct Response {
    terms: Vec<HeuristicTermScores>,
}

pub fn run(args: &[String]) -> i32 {
    if !args.is_empty() {
        eprintln!("agent-heuristic-terms accepts no command-line arguments");
        return 2;
    }
    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut out = stdout.lock();
    for line in stdin.lock().lines() {
        let line = match line {
            Ok(line) if !line.trim().is_empty() => line,
            Ok(_) => continue,
            Err(_) => {
                eprintln!("agent-heuristic-terms stdin read failed");
                return 1;
            }
        };
        let response = match serde_json::from_str::<Request>(&line) {
            Ok(request) if !request.legal_actions.is_empty() => Response {
                terms: heuristic_term_scores(&request.observation, &request.legal_actions),
            },
            Ok(_) => {
                eprintln!("agent-heuristic-terms requires legal actions");
                return 1;
            }
            Err(_) => {
                eprintln!("agent-heuristic-terms received invalid input");
                return 1;
            }
        };
        if serde_json::to_writer(&mut out, &response).is_err()
            || writeln!(out).is_err()
            || out.flush().is_err()
        {
            eprintln!("agent-heuristic-terms stdout write failed");
            return 1;
        }
    }
    0
}

#[cfg(test)]
mod tests {
    use super::*;
    use splendor_core::{FullState, GameConfig, PlayerId};

    #[test]
    fn outputs_canonical_term_vector_aligned_with_legal_actions() {
        let (state, _) = FullState::new(GameConfig {
            seed: 20260923,
            ..Default::default()
        })
        .unwrap();
        let observation = state.observation(PlayerId(0));
        let actions = state.legal_actions();
        let scores = heuristic_term_scores(&observation, &actions);
        assert_eq!(scores.len(), actions.len());
        let request = serde_json::json!({"observation": observation, "legal_actions": actions});
        let parsed: Request = serde_json::from_value(request).unwrap();
        assert_eq!(
            heuristic_term_scores(&parsed.observation, &parsed.legal_actions),
            scores
        );
        let value = serde_json::to_value(Response { terms: scores }).unwrap();
        let terms = value["terms"].as_array().unwrap();
        assert_eq!(terms.len(), actions.len());
        for key in [
            "category_base",
            "prestige",
            "noble_gain",
            "noble_direct",
            "bonus_usefulness",
            "cost_efficiency",
            "deficit_reduction",
            "new_target",
            "return_penalty",
            "gold_value",
            "reserve_proximity",
            "reserve_gold",
            "reserve_blind_gold",
        ] {
            assert!(terms[0].get(key).is_some(), "missing canonical term {key}");
        }
    }

    #[test]
    fn helper_input_rejects_unknown_referee_fields() {
        let value = serde_json::json!({"observation": {}, "legal_actions": [], "seed": 42});
        assert!(serde_json::from_value::<Request>(value).is_err());
    }
}
