//! Offline verified replay style profiles; never launches a game or agent.
use serde_json::{json, Value};
use splendor_core::{Action, Phase};
use splendor_replay::{verify_replay_trace, ReplayV1};
use std::{fs, path::Path};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 4 {
        return Err("usage: prism_rush_metrics manifest.json style.json output.json".into());
    }
    let manifest_path = Path::new(&args[1]);
    let manifest: Value = serde_json::from_slice(&fs::read(manifest_path)?)?;
    let style: Value = serde_json::from_slice(&fs::read(&args[2])?)?;
    if style["format"] != "prism-rush-style-v1" || style["terminal_only"] != true {
        return Err("unsupported style contract".into());
    }
    let window = style["window_main_actions"].as_u64().ok_or("window")? as usize;
    let cap = style["score_cap"].as_u64().ok_or("cap")? as f64;
    let horizon = style["diagnostic_horizon_main_actions"].as_u64().ok_or("horizon")? as usize;
    let threshold = style["diagnostic_score_threshold"].as_u64().ok_or("threshold")? as u8;
    if !(1..=256).contains(&window) || cap <= 0.0 || !(1..=256).contains(&horizon) {
        return Err("invalid style numeric contract".into());
    }
    let mut rows = Vec::new();
    for row in manifest["rows"].as_array().ok_or("rows")? {
        let path = manifest_path.parent().unwrap_or(Path::new(".")).join(row["replay_path"].as_str().ok_or("replay_path")?);
        let replay: ReplayV1 = serde_json::from_slice(&fs::read(path)?)?;
        let trace = verify_replay_trace(&replay)?;
        let mut curves: [Vec<u8>; 2] = [Vec::new(), Vec::new()];
        let mut high_vp_buys = [0u32; 2];
        for pos in &trace.positions {
            let actor = pos.recorded_actor.index();
            let mut next = pos.state.clone();
            next.apply(pos.recorded_action)?;
            if pos.state.phase == Phase::Main {
                curves[actor].push(next.players[actor].prestige);
                if curves[actor].len() <= window {
                    let purchased_vp = match pos.recorded_action {
                        Action::BuyMarket { tier, slot } => pos.state.market[tier.index()][slot as usize]
                            .map(|id| splendor_catalog::card(id).prestige),
                        Action::BuyReserved { slot } => pos.state.players[actor].reserved.get(slot as usize)
                            .map(|r| splendor_catalog::card(r.card).prestige),
                        _ => None,
                    };
                    if purchased_vp.is_some_and(|vp| vp >= 3) { high_vp_buys[actor] += 1; }
                }
            } else if pos.state.phase == Phase::ChooseNoble {
                *curves[actor].last_mut().ok_or("noble before Main")? = next.players[actor].prestige;
            } else {
                return Err("action after terminal".into());
            }
        }
        let mut profiles = Vec::new();
        for actor in 0..2 {
            let terminal = replay.result.scores[actor];
            let scores = &curves[actor];
            if scores.last().copied() != Some(terminal) { return Err("terminal Main score mismatch".into()); }
            let auc = (0..window).map(|i| (f64::from(*scores.get(i).unwrap_or(&terminal))).min(cap) / cap).sum::<f64>() / window as f64;
            let crossing = scores.iter().take(horizon).position(|&vp| vp >= threshold).map(|i| i+1);
            profiles.push(json!({"actor": actor, "rush_auc": auc, "after_main_prestige": scores,
                "main_actions": scores.len(), "terminal_prestige": terminal,
                "shorter_than_reward_window": scores.len() < window,
                "vp_threshold_by_horizon": crossing.is_some(), "first_main_to_threshold": crossing,
                "high_vp_buys_within_window": high_vp_buys[actor]}));
        }
        let mut result = row.clone();
        result["profiles"] = json!(profiles);
        rows.push(result);
    }
    fs::write(&args[3], serde_json::to_vec_pretty(&json!({"format": "prism-rush-replay-metrics-v1", "games": rows}))?)?;
    println!("PASS: verified {} saved replays", manifest["rows"].as_array().unwrap().len());
    Ok(())
}
