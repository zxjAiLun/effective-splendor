//! M56 offline, rule-verified, actor-oriented purchase and score trajectories.
//! This executable never dispatches a game or an agent.
use serde_json::{json, Value};
use splendor_core::{Action, Phase};
use splendor_replay::{verify_replay_trace, ReplayV1};
use std::{fs, path::Path};

fn padded_value(scores: &[u16], terminal: u16, main: usize) -> u16 {
    *scores.get(main - 1).unwrap_or(&terminal)
}

fn auc(scores: &[u16], terminal: u16, window: usize, cap: f64) -> f64 {
    (1..=window)
        .map(|main| f64::from(padded_value(scores, terminal, main)).min(cap) / cap)
        .sum::<f64>() / window as f64
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 4 {
        return Err("usage: prism_bigcard_metrics manifest.json style.json output.json".into());
    }
    let manifest_path = Path::new(&args[1]);
    let manifest: Value = serde_json::from_slice(&fs::read(manifest_path)?)?;
    let style: Value = serde_json::from_slice(&fs::read(&args[2])?)?;
    if style["format"] != "prism-rush-style-v1"
        || style["terminal_only"] != true
        || style["phase_semantics"] != "choose_noble-belongs-to-preceding-main"
        || style["short_game_padding"] != "terminal-prestige"
    {
        return Err("unsupported style contract".into());
    }
    let window = style["window_main_actions"].as_u64().ok_or("window")? as usize;
    let cap = style["score_cap"].as_u64().ok_or("cap")? as f64;
    let horizon = style["diagnostic_horizon_main_actions"].as_u64().ok_or("horizon")? as usize;
    let threshold = style["diagnostic_score_threshold"].as_u64().ok_or("threshold")? as u16;
    if window != 24 || cap != 15.0 || !(1..=256).contains(&horizon) {
        return Err("M56 requires fixed 24 Main / 15 VP window".into());
    }
    let mut rows = Vec::new();
    for row in manifest["rows"].as_array().ok_or("rows")? {
        let path = manifest_path.parent().unwrap_or(Path::new(".")).join(
            row["replay_path"].as_str().ok_or("replay_path")?,
        );
        let replay: ReplayV1 = serde_json::from_slice(&fs::read(path)?)?;
        let trace = verify_replay_trace(&replay)?;
        let mut curves: [Vec<u16>; 2] = [Vec::new(), Vec::new()];
        let mut big_curves: [Vec<u16>; 2] = [Vec::new(), Vec::new()];
        let mut big_vp = [0u16; 2];
        let mut events: [Vec<Value>; 2] = [Vec::new(), Vec::new()];
        for pos in &trace.positions {
            let actor = pos.recorded_actor.index();
            let mut next = pos.state.clone();
            next.apply(pos.recorded_action)?;
            if pos.state.phase == Phase::Main {
                let own_main = curves[actor].len() + 1;
                let purchased_vp = match pos.recorded_action {
                    Action::BuyMarket { tier, slot } => pos.state.market[tier.index()][slot as usize]
                        .map(|id| splendor_catalog::card(id).prestige),
                    Action::BuyReserved { slot } => pos.state.players[actor].reserved.get(slot as usize)
                        .map(|r| splendor_catalog::card(r.card).prestige),
                    _ => None,
                };
                if let Some(vp) = purchased_vp {
                    events[actor].push(json!({"own_main": own_main, "printed_vp": vp}));
                    if vp >= 3 { big_vp[actor] += u16::from(vp); }
                }
                curves[actor].push(u16::from(next.players[actor].prestige));
                big_curves[actor].push(big_vp[actor]);
            } else if pos.state.phase == Phase::ChooseNoble {
                // The noble score belongs to its preceding Main; it never counts
                // as a purchased large card or an extra Main action.
                *curves[actor].last_mut().ok_or("noble before Main")? =
                    u16::from(next.players[actor].prestige);
            } else {
                return Err("action after terminal".into());
            }
        }
        let mut profiles = Vec::new();
        for actor in 0..2 {
            let terminal = u16::from(replay.result.scores[actor]);
            let scores = &curves[actor];
            if scores.last().copied() != Some(terminal) {
                return Err("terminal Main score mismatch".into());
            }
            let crossing = scores.iter().take(horizon).position(|&vp| vp >= threshold).map(|i| i + 1);
            let first = |minimum| events[actor].iter()
                .find(|e| e["printed_vp"].as_u64().unwrap() >= minimum)
                .map(|e| e["own_main"].as_u64().unwrap());
            let checkpoints: Vec<Value> = [8, 12, 16, 20, 24].into_iter().map(|main| {
                json!({"own_main": main, "vp": padded_value(scores, terminal, main),
                    "large_card_printed_vp": padded_value(&big_curves[actor], big_vp[actor], main),
                    "observed_before_terminal": scores.len() >= main})
            }).collect();
            profiles.push(json!({"actor": actor, "rush_auc": auc(scores, terminal, window, cap),
                "after_main_prestige": scores, "main_actions": scores.len(),
                "terminal_prestige": terminal, "shorter_than_reward_window": scores.len() < window,
                "vp_threshold_by_horizon": crossing.is_some(), "first_main_to_threshold": crossing,
                "high_vp_buys_within_window": events[actor].iter().filter(|e|
                    e["printed_vp"].as_u64().unwrap() >= 3 && e["own_main"].as_u64().unwrap() <= window as u64).count(),
                "large_card_vp_auc24": auc(&big_curves[actor], big_vp[actor], window, cap),
                "large_card_vp_after_main": big_curves[actor],
                "terminal_large_card_printed_vp": big_vp[actor],
                "purchase_events": events[actor], "first_large_card_main": first(3),
                "first_4plus_card_main": first(4), "score_checkpoints": checkpoints}));
        }
        let mut result = row.clone();
        result["profiles"] = json!(profiles);
        rows.push(result);
    }
    fs::write(&args[3], serde_json::to_vec_pretty(&json!({
        "format": "m56-prism-bigcard-replay-metrics-v1", "games": rows,
        "window_main_actions": window, "score_cap": cap,
        "checkpoint_padding": "terminal-player-score-or-terminal-large-card-printed-vp"
    }))?)?;
    println!("PASS: verified {} saved replays", manifest["rows"].as_array().unwrap().len());
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn short_game_pads_fixed_window_with_terminal() {
        assert_eq!(padded_value(&[0, 5], 5, 3), 5);
        assert!((auc(&[0, 5], 5, 24, 15.0) - 23.0 / 72.0).abs() < 1e-12);
    }
    #[test]
    fn score_cap_and_window_boundary() {
        assert_eq!(auc(&[20; 25], 20, 24, 15.0), 1.0);
        let mut scores = vec![0; 24]; scores.push(5);
        assert_eq!(auc(&scores, 5, 24, 15.0), 0.0);
    }
    #[test]
    fn no_large_card_does_not_inherit_noble_score() {
        assert_eq!(auc(&[0; 24], 0, 24, 15.0), 0.0);
        assert!(auc(&[3; 24], 3, 24, 15.0) > 0.0);
    }
}
