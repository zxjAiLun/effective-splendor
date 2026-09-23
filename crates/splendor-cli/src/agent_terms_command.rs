//! NDJSON adapter exposing the existing, canonical heuristic term breakdown.
//!
//! This is a local helper for agents that want structured baseline features. It
//! receives only an Observation and server-certified legal actions, never arena
//! configuration, seed, replay, or referee state.

use std::io::{self, BufRead, Read, Write};

use serde::Deserialize;
use splendor_agent::{heuristic_term_scores, HeuristicTermScores};
use splendor_catalog::{all_cards, all_nobles, card};
use splendor_core::{Action, Gems, Observation};

const MAX_INPUT_BYTES: u64 = 2_000_000;

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

impl Request {
    // Structural validation only; the arena remains the authority for legality.
    // Guard every index/expect and small-count arithmetic used by heuristic_term_scores.
    fn validate(&self) -> Result<(), &'static str> {
        let obs = &self.observation;
        let board = &obs.public;
        let valid_card = |id: splendor_catalog::CardId| id.index() < all_cards().len();
        let valid_noble = |id: splendor_catalog::NobleId| id.index() < all_nobles().len();
        let bounded_gems = |g: Gems| {
            let total: u16 =
                g.colors_array().iter().map(|&v| u16::from(v)).sum::<u16>() + u16::from(g.gold);
            total <= 255
        };
        if !(2..=4).contains(&board.player_count)
            || board.players.len() != usize::from(board.player_count)
            || obs.viewer.0 >= board.player_count
            || board.current_player != obs.viewer
            || self.legal_actions.is_empty()
            || self.legal_actions.len() > 10000
            || !bounded_gems(board.bank)
        {
            return Err("invalid observation or action count");
        }
        for (i, p) in board.players.iter().enumerate() {
            if p.id.index() != i
                || !bounded_gems(p.tokens)
                || p.reserved_count > 3
                || p.bonuses.iter().map(|&v| u16::from(v)).sum::<u16>() > 90
                || p.purchased.len() > all_cards().len()
                || p.nobles.len() > all_nobles().len()
                || p.public_reserved
                    .iter()
                    .chain(&p.purchased)
                    .any(|&id| !valid_card(id))
                || p.nobles.iter().any(|&id| !valid_noble(id))
            {
                return Err("invalid player fields");
            }
        }
        if board
            .market
            .iter()
            .flatten()
            .flatten()
            .any(|&id| !valid_card(id))
            || board
                .nobles
                .iter()
                .chain(&board.pending_nobles)
                .any(|&id| !valid_noble(id))
            || obs.private.reserved.len() > 3
            || obs.private.reserved.iter().enumerate().any(|(i, r)| {
                usize::from(r.slot) != i || !valid_card(r.card) || card(r.card).tier != r.tier
            })
        {
            return Err("invalid catalog reference");
        }
        for action in &self.legal_actions {
            match *action {
                Action::BuyMarket { tier, slot } | Action::ReserveMarket { tier, slot, .. } => {
                    if board.market[tier.index()]
                        .get(usize::from(slot))
                        .copied()
                        .flatten()
                        .is_none()
                    {
                        return Err("invalid market slot");
                    }
                }
                Action::BuyReserved { slot } => {
                    if usize::from(slot) >= obs.private.reserved.len() {
                        return Err("invalid reserve slot");
                    }
                }
                Action::ChooseNoble { noble } => {
                    if !valid_noble(noble) || !board.pending_nobles.contains(&noble) {
                        return Err("invalid noble choice");
                    }
                }
                _ => {}
            }
            match *action {
                Action::TakeTokens { take, give_back }
                    if !bounded_gems(take) || !bounded_gems(give_back) =>
                {
                    return Err("invalid token action");
                }
                Action::ReserveMarket { give_back, .. } | Action::ReserveDeck { give_back, .. }
                    if !bounded_gems(give_back) =>
                {
                    return Err("invalid reserve return")
                }
                _ => {}
            }
        }
        Ok(())
    }
}

pub fn run(args: &[String]) -> i32 {
    if !args.is_empty() {
        eprintln!("agent-heuristic-terms accepts no command-line arguments");
        return 2;
    }
    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut out = stdout.lock();
    let mut input = stdin.lock();
    loop {
        let mut line = Vec::new();
        match (&mut input)
            .take(MAX_INPUT_BYTES + 1)
            .read_until(b'\n', &mut line)
        {
            Ok(0) => break,
            Ok(_) if line.len() as u64 <= MAX_INPUT_BYTES => {}
            _ => {
                eprintln!("agent-heuristic-terms input too large or unreadable");
                return 1;
            }
        }
        if line.iter().all(u8::is_ascii_whitespace) {
            continue;
        }
        let response = match serde_json::from_slice::<Request>(&line) {
            Ok(request) if request.validate().is_ok() => Response {
                terms: heuristic_term_scores(&request.observation, &request.legal_actions),
            },
            Ok(_) => {
                eprintln!("agent-heuristic-terms received invalid references");
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
        let (state, _) = FullState::new(GameConfig::default()).unwrap();
        let mut value = serde_json::json!({"observation": state.observation(PlayerId(0)), "legal_actions": state.legal_actions()});
        assert!(serde_json::from_value::<Request>(value.clone())
            .unwrap()
            .validate()
            .is_ok());
        value["seed"] = serde_json::json!(42);
        assert!(serde_json::from_value::<Request>(value).is_err());
    }

    #[test]
    fn malformed_references_are_rejected_before_scoring() {
        let (state, _) = FullState::new(GameConfig::default()).unwrap();
        let obs = state.observation(PlayerId(0));
        for action in [
            Action::BuyMarket {
                tier: splendor_catalog::Tier::One,
                slot: 255,
            },
            Action::BuyReserved { slot: 255 },
            Action::ChooseNoble {
                noble: splendor_catalog::NobleId(255),
            },
        ] {
            assert!(Request {
                observation: obs.clone(),
                legal_actions: vec![action]
            }
            .validate()
            .is_err());
        }
        let mut request = Request {
            observation: obs,
            legal_actions: state.legal_actions(),
        };
        request.observation.viewer = PlayerId(255);
        assert!(request.validate().is_err());
        request.observation.viewer = PlayerId(0);
        request.observation.public.market[0][0] = Some(splendor_catalog::CardId(255));
        assert!(request.validate().is_err());
    }
}
