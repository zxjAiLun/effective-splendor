//! Unified batch match metrics analyzer for Splendor.
//! Reconstructs verified state traces across all replays in a manifest,
//! computing standardized game-level, turn-level, and card-level metrics.

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use splendor_catalog::{all_nobles, card, CardId, GemColor, Tier};
use splendor_core::{Action, FullState, Gems, Phase, PlayerId};
use splendor_replay::{verify_replay_trace, ReplayV1};
use std::collections::BTreeMap;
use std::fs::{self, File};
use std::io::Write;
use std::path::{Path, PathBuf};

#[derive(Debug, Default, Clone, Serialize, Deserialize)]
pub struct SeatMetrics {
    pub wins: usize,
    pub ties: usize,
    pub losses: usize,
    pub win_rate_percent: f64,
    pub mean_prestige: f64,
    pub vp_per_turn: f64,
    pub vp_per_ply: f64,
    pub mean_nobles: f64,
    pub games_with_nobles: usize,
    pub games_with_nobles_percent: f64,
    pub mean_cards_by_vp: BTreeMap<u8, f64>,
    pub mean_permanent_bonuses: f64,
    pub mean_bonuses_by_color: BTreeMap<String, f64>,
    pub mean_reserves_acquired: f64,
    pub mean_reserves_bought: f64,
    pub mean_reserves_stranded: f64,
    pub action_distribution: BTreeMap<String, usize>,
    pub action_percentages: BTreeMap<String, f64>,
}

#[derive(Debug, Default, Clone, Serialize, Deserialize)]
pub struct BatchMetricsReport {
    pub format: String,
    pub version: u32,
    pub total_games: usize,
    pub total_plies: usize,
    pub mean_plies: f64,
    pub mean_turns: f64,
    pub min_turns: u32,
    pub max_turns: u32,
    pub median_turns: f64,
    pub std_turns: f64,
    pub mean_victory_margin: f64,
    pub close_games_margin_le_2_percent: f64,
    pub seat_p0_first: SeatMetrics,
    pub seat_p1_second: SeatMetrics,
    pub overall_mean_prestige_per_player: f64,
    pub overall_vp_per_turn: f64,
    pub overall_vp_per_ply: f64,
    pub overall_mean_nobles_per_player: f64,
    pub overall_mean_cards_by_vp_per_player: BTreeMap<u8, f64>,
}

fn color_name(idx: usize) -> &'static str {
    match idx {
        0 => "White",
        1 => "Blue",
        2 => "Green",
        3 => "Red",
        4 => "Black",
        _ => "Unknown",
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

pub fn analyze_manifest_replays(
    manifest_path: &Path,
) -> Result<BatchMetricsReport, Box<dyn std::error::Error>> {
    let base_dir = manifest_path.parent().unwrap_or(Path::new("."));
    let manifest_bytes = fs::read(manifest_path)?;
    let manifest: Value = serde_json::from_slice(&manifest_bytes)?;
    let rows = manifest["rows"]
        .as_array()
        .ok_or("manifest missing rows array")?;

    let total_games = rows.len();
    if total_games == 0 {
        return Err("no games in manifest".into());
    }

    let mut p0_wins = 0;
    let mut p1_wins = 0;
    let mut ties = 0;

    let mut game_turns_list = Vec::with_capacity(total_games);
    let mut game_margins_list = Vec::with_capacity(total_games);

    let mut p0_scores = Vec::with_capacity(total_games);
    let mut p1_scores = Vec::with_capacity(total_games);

    let mut p0_turns = Vec::with_capacity(total_games);
    let mut p1_turns = Vec::with_capacity(total_games);

    let mut p0_nobles = Vec::with_capacity(total_games);
    let mut p1_nobles = Vec::with_capacity(total_games);

    let mut p0_cards_by_vp: BTreeMap<u8, usize> = BTreeMap::new();
    let mut p1_cards_by_vp: BTreeMap<u8, usize> = BTreeMap::new();
    for vp in 0..=5 {
        p0_cards_by_vp.insert(vp, 0);
        p1_cards_by_vp.insert(vp, 0);
    }

    let mut p0_bonuses_sum = [0u64; 5];
    let mut p1_bonuses_sum = [0u64; 5];

    let mut p0_res_acquired = 0usize;
    let mut p0_res_bought = 0usize;
    let mut p1_res_acquired = 0usize;
    let mut p1_res_bought = 0usize;

    let mut p0_actions: BTreeMap<String, usize> = BTreeMap::new();
    let mut p1_actions: BTreeMap<String, usize> = BTreeMap::new();

    let mut total_plies = 0usize;

    for (row_idx, row) in rows.iter().enumerate() {
        let replay_path = if let Some(p) = row.get("replay_path").and_then(|v| v.as_str()) {
            base_dir.join(p)
        } else if let (Some(opp), Some(seed), Some(rot)) = (
            row.get("opponent").and_then(|v| v.as_str()),
            row.get("seed").and_then(|v| v.as_u64()),
            row.get("rotation").and_then(|v| v.as_u64()),
        ) {
            base_dir
                .join("games")
                .join(opp)
                .join(format!("seed-{seed}"))
                .join(format!("r{rot}"))
                .join("match-replay.json")
        } else if let Some(p) = row.get("rel_path").and_then(|v| v.as_str()) {
            base_dir.join(p)
        } else {
            return Err(format!("row {row_idx} lacks replay path identifier").into());
        };

        let replay_bytes = fs::read(&replay_path)
            .map_err(|e| format!("failed reading {}: {e}", replay_path.display()))?;
        let replay: ReplayV1 = serde_json::from_slice(&replay_bytes)?;
        let trace = verify_replay_trace(&replay)?;

        let plies = trace.positions.len();
        total_plies += plies;

        let turns = (plies + 1) / 2;
        game_turns_list.push(turns as u32);

        let mut p0_actor_turns = 0u32;
        let mut p1_actor_turns = 0u32;

        for pos in &trace.positions {
            let s = &pos.state;
            let actor = pos.recorded_actor;
            let action = pos.recorded_action;
            let me = &s.players[actor.index()];

            let act_kind = action_kind(&action).to_string();
            if actor.0 == 0 {
                p0_actor_turns += 1;
                *p0_actions.entry(act_kind).or_default() += 1;
            } else {
                p1_actor_turns += 1;
                *p1_actions.entry(act_kind).or_default() += 1;
            }

            match action {
                Action::BuyMarket { tier, slot } => {
                    if let Some(cid) = s.market[tier.index()][slot as usize] {
                        let vp = card(cid).prestige;
                        if actor.0 == 0 {
                            *p0_cards_by_vp.entry(vp).or_default() += 1;
                        } else {
                            *p1_cards_by_vp.entry(vp).or_default() += 1;
                        }
                    }
                }
                Action::BuyReserved { slot } => {
                    if (slot as usize) < me.reserved.len() {
                        let cid = me.reserved[slot as usize].card;
                        let vp = card(cid).prestige;
                        if actor.0 == 0 {
                            p0_res_bought += 1;
                            *p0_cards_by_vp.entry(vp).or_default() += 1;
                        } else {
                            p1_res_bought += 1;
                            *p1_cards_by_vp.entry(vp).or_default() += 1;
                        }
                    }
                }
                Action::ReserveMarket { .. } | Action::ReserveDeck { .. } => {
                    if actor.0 == 0 {
                        p0_res_acquired += 1;
                    } else {
                        p1_res_acquired += 1;
                    }
                }
                _ => {}
            }
        }

        p0_turns.push(p0_actor_turns);
        p1_turns.push(p1_actor_turns);

        let mut final_state = trace.positions.last().unwrap().state.clone();
        final_state.apply(trace.positions.last().unwrap().recorded_action)?;

        let s0 = final_state.players[0].prestige;
        let s1 = final_state.players[1].prestige;
        p0_scores.push(s0);
        p1_scores.push(s1);

        let margin = (s0 as i32 - s1 as i32).abs() as f64;
        game_margins_list.push(margin);

        let n0 = final_state.players[0].nobles.len();
        let n1 = final_state.players[1].nobles.len();
        p0_nobles.push(n0);
        p1_nobles.push(n1);

        for c in 0..5 {
            p0_bonuses_sum[c] += final_state.players[0].bonuses[c] as u64;
            p1_bonuses_sum[c] += final_state.players[1].bonuses[c] as u64;
        }

        let winners = &replay.result.winners;
        if winners.len() > 1 || (winners.contains(&0) && winners.contains(&1)) {
            ties += 1;
        } else if winners.contains(&0) {
            p0_wins += 1;
        } else if winners.contains(&1) {
            p1_wins += 1;
        }
    }

    game_turns_list.sort_unstable();
    let min_turns = game_turns_list.first().copied().unwrap_or(0);
    let max_turns = game_turns_list.last().copied().unwrap_or(0);
    let median_turns = if total_games % 2 == 1 {
        game_turns_list[total_games / 2] as f64
    } else {
        (game_turns_list[total_games / 2 - 1] as f64 + game_turns_list[total_games / 2] as f64)
            / 2.0
    };
    let mean_turns = game_turns_list.iter().map(|&x| x as f64).sum::<f64>() / total_games as f64;
    let var_turns = game_turns_list
        .iter()
        .map(|&x| (x as f64 - mean_turns).powi(2))
        .sum::<f64>()
        / total_games as f64;
    let std_turns = var_turns.sqrt();

    let mean_victory_margin = game_margins_list.iter().sum::<f64>() / total_games as f64;
    let close_games_count = game_margins_list.iter().filter(|&&m| m <= 2.0).count();
    let close_games_margin_le_2_percent = 100.0 * close_games_count as f64 / total_games as f64;

    let build_seat_metrics = |wins: usize,
                              ties: usize,
                              losses: usize,
                              scores: &[u8],
                              turns_list: &[u32],
                              nobles_list: &[usize],
                              cards_map: &BTreeMap<u8, usize>,
                              bonuses_sum: &[u64; 5],
                              res_acq: usize,
                              res_bought: usize,
                              act_map: &BTreeMap<String, usize>|
     -> SeatMetrics {
        let win_rate_percent = 100.0 * wins as f64 / total_games as f64;
        let total_score: u64 = scores.iter().map(|&s| s as u64).sum();
        let mean_prestige = total_score as f64 / total_games as f64;

        let total_turns: u64 = turns_list.iter().map(|&t| t as u64).sum();
        let vp_per_turn = total_score as f64 / total_turns.max(1) as f64;
        let vp_per_ply = total_score as f64 / total_plies.max(1) as f64;

        let total_nobles: usize = nobles_list.iter().sum();
        let mean_nobles = total_nobles as f64 / total_games as f64;
        let games_with_nobles = nobles_list.iter().filter(|&&n| n > 0).count();
        let games_with_nobles_percent = 100.0 * games_with_nobles as f64 / total_games as f64;

        let mean_cards_by_vp: BTreeMap<u8, f64> = cards_map
            .iter()
            .map(|(&vp, &count)| (vp, count as f64 / total_games as f64))
            .collect();

        let total_bonuses: u64 = bonuses_sum.iter().sum();
        let mean_permanent_bonuses = total_bonuses as f64 / total_games as f64;

        let mean_bonuses_by_color: BTreeMap<String, f64> = bonuses_sum
            .iter()
            .enumerate()
            .map(|(c, &sum)| (color_name(c).to_string(), sum as f64 / total_games as f64))
            .collect();

        let mean_reserves_acquired = res_acq as f64 / total_games as f64;
        let mean_reserves_bought = res_bought as f64 / total_games as f64;
        let mean_reserves_stranded =
            (res_acq.saturating_sub(res_bought)) as f64 / total_games as f64;

        let total_seat_actions: usize = act_map.values().sum();
        let action_percentages: BTreeMap<String, f64> = act_map
            .iter()
            .map(|(k, &v)| {
                (
                    k.clone(),
                    100.0 * v as f64 / total_seat_actions.max(1) as f64,
                )
            })
            .collect();

        SeatMetrics {
            wins,
            ties,
            losses,
            win_rate_percent,
            mean_prestige,
            vp_per_turn,
            vp_per_ply,
            mean_nobles,
            games_with_nobles,
            games_with_nobles_percent,
            mean_cards_by_vp,
            mean_permanent_bonuses,
            mean_bonuses_by_color,
            mean_reserves_acquired,
            mean_reserves_bought,
            mean_reserves_stranded,
            action_distribution: act_map.clone(),
            action_percentages,
        }
    };

    let seat_p0_first = build_seat_metrics(
        p0_wins,
        ties,
        total_games - p0_wins - ties,
        &p0_scores,
        &p0_turns,
        &p0_nobles,
        &p0_cards_by_vp,
        &p0_bonuses_sum,
        p0_res_acquired,
        p0_res_bought,
        &p0_actions,
    );

    let seat_p1_second = build_seat_metrics(
        p1_wins,
        ties,
        total_games - p1_wins - ties,
        &p1_scores,
        &p1_turns,
        &p1_nobles,
        &p1_cards_by_vp,
        &p1_bonuses_sum,
        p1_res_acquired,
        p1_res_bought,
        &p1_actions,
    );

    let total_all_vp: u64 = p0_scores.iter().map(|&s| s as u64).sum::<u64>()
        + p1_scores.iter().map(|&s| s as u64).sum::<u64>();
    let overall_mean_prestige_per_player =
        (seat_p0_first.mean_prestige + seat_p1_second.mean_prestige) / 2.0;
    let overall_vp_per_turn = total_all_vp as f64
        / (p0_turns.iter().sum::<u32>() + p1_turns.iter().sum::<u32>()).max(1) as f64;
    let overall_vp_per_ply = total_all_vp as f64 / (total_plies * 2).max(1) as f64;
    let overall_mean_nobles_per_player =
        (seat_p0_first.mean_nobles + seat_p1_second.mean_nobles) / 2.0;

    let mut overall_mean_cards_by_vp_per_player = BTreeMap::new();
    for vp in 0..=5 {
        let m = (seat_p0_first
            .mean_cards_by_vp
            .get(&vp)
            .copied()
            .unwrap_or(0.0)
            + seat_p1_second
                .mean_cards_by_vp
                .get(&vp)
                .copied()
                .unwrap_or(0.0))
            / 2.0;
        overall_mean_cards_by_vp_per_player.insert(vp, m);
    }

    Ok(BatchMetricsReport {
        format: "effective-splendor-batch-metrics-v1".to_string(),
        version: 1,
        total_games,
        total_plies,
        mean_plies: total_plies as f64 / total_games as f64,
        mean_turns,
        min_turns,
        max_turns,
        median_turns,
        std_turns,
        mean_victory_margin,
        close_games_margin_le_2_percent,
        seat_p0_first,
        seat_p1_second,
        overall_mean_prestige_per_player,
        overall_vp_per_turn,
        overall_vp_per_ply,
        overall_mean_nobles_per_player,
        overall_mean_cards_by_vp_per_player,
    })
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 2 {
        eprintln!("Usage: s4_batch_metrics <manifest.json> [out_metrics.json]");
        std::process::exit(1);
    }
    let manifest_path = Path::new(&args[1]);
    let report = analyze_manifest_replays(manifest_path)?;

    if args.len() >= 3 {
        let out_path = Path::new(&args[2]);
        if let Some(parent) = out_path.parent() {
            fs::create_dir_all(parent)?;
        }
        let mut file = File::create(out_path)?;
        file.write_all(serde_json::to_string_pretty(&report)?.as_bytes())?;
        file.write_all(b"\n")?;
        println!("Metrics successfully saved to {}", out_path.display());
    } else {
        println!("{}", serde_json::to_string_pretty(&report)?);
    }
    Ok(())
}
