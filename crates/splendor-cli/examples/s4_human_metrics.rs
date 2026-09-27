//! Human Player Metrics Analyzer for Splendor.
//! Evaluates all recorded human games, computing human perspective
//! vs opponent perspective metrics across seats, victory margins, and actions.

use serde::{Deserialize, Serialize};
use serde_json::Value;
use splendor_catalog::{card, GemColor};
use splendor_core::Action;
use splendor_replay::{verify_replay_trace, ReplayV1};
use std::collections::BTreeMap;
use std::fs::{self, File};
use std::io::Write;
use std::path::{Path, PathBuf};

#[derive(Debug, Default, Clone, Serialize, Deserialize)]
pub struct PerspectiveMetrics {
    pub games_played: usize,
    pub wins: usize,
    pub ties: usize,
    pub losses: usize,
    pub win_rate_percent: f64,
    pub mean_prestige: f64,
    pub total_prestige: u64,
    pub total_turns: u64,
    pub vp_per_turn: f64,
    pub vp_per_ply: f64,
    pub mean_nobles: f64,
    pub games_with_nobles: usize,
    pub games_with_nobles_percent: f64,
    pub mean_cards_by_vp: BTreeMap<u8, f64>,
    pub total_cards_by_vp: BTreeMap<u8, usize>,
    pub mean_permanent_bonuses: f64,
    pub mean_bonuses_by_color: BTreeMap<String, f64>,
    pub mean_reserves_acquired: f64,
    pub mean_reserves_bought: f64,
    pub mean_reserves_stranded: f64,
    pub reserve_redemption_rate_percent: f64,
    pub action_distribution: BTreeMap<String, usize>,
    pub action_percentages: BTreeMap<String, f64>,
}

#[derive(Debug, Default, Clone, Serialize, Deserialize)]
pub struct HumanPlayerReport {
    pub format: String,
    pub version: u32,
    pub total_games: usize,
    pub total_plies: usize,
    pub mean_plies: f64,
    pub mean_turns: f64,
    pub median_turns: f64,
    pub min_turns: u32,
    pub max_turns: u32,
    pub mean_victory_margin: f64,
    pub human_first_p0_games: usize,
    pub human_second_p1_games: usize,
    pub human_overall: PerspectiveMetrics,
    pub human_as_p0_first: PerspectiveMetrics,
    pub human_as_p1_second: PerspectiveMetrics,
    pub opponents_overall: PerspectiveMetrics,
    pub opponents_breakdown: BTreeMap<String, String>,
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

pub fn analyze_human_games(
    human_dir: &Path,
) -> Result<HumanPlayerReport, Box<dyn std::error::Error>> {
    let mut replay_files: Vec<PathBuf> = fs::read_dir(human_dir)?
        .filter_map(|e| e.ok())
        .map(|e| e.path())
        .filter(|p| {
            let name = p.file_name().and_then(|n| n.to_str()).unwrap_or("");
            name.starts_with("human-") && name.ends_with(".replay.json")
        })
        .collect();

    replay_files.sort();

    let mut game_turns_list = Vec::new();
    let mut game_margins_list = Vec::new();
    let mut total_plies = 0usize;

    struct GameSample {
        human_seat: usize,
        opp_name: String,
        human_score: u8,
        opp_score: u8,
        human_won: bool,
        is_tie: bool,
        human_turns: u32,
        opp_turns: u32,
        human_nobles: usize,
        opp_nobles: usize,
        human_cards: BTreeMap<u8, usize>,
        opp_cards: BTreeMap<u8, usize>,
        human_bonuses: [u8; 5],
        opp_bonuses: [u8; 5],
        human_res_acq: usize,
        human_res_bought: usize,
        opp_res_acq: usize,
        opp_res_bought: usize,
        human_actions: BTreeMap<String, usize>,
        opp_actions: BTreeMap<String, usize>,
    }

    let mut samples = Vec::new();

    for r_path in &replay_files {
        let meta_path = r_path.with_file_name(
            r_path
                .file_name()
                .unwrap()
                .to_str()
                .unwrap()
                .replace(".replay.json", ".replay.meta.json"),
        );
        let (human_seat, opp_name) = if meta_path.exists() {
            let m: Value = serde_json::from_slice(&fs::read(&meta_path)?)?;
            let seat = m["human_seat"]
                .as_u64()
                .map(|v| v as usize)
                .unwrap_or_else(|| {
                    let parts: Vec<&str> = r_path
                        .file_name()
                        .unwrap()
                        .to_str()
                        .unwrap()
                        .split('-')
                        .collect();
                    parts[2].parse().unwrap_or(0)
                });
            let opp = m["opponent"].as_str().unwrap_or("Unknown").to_string();
            (seat, opp)
        } else {
            let parts: Vec<&str> = r_path
                .file_name()
                .unwrap()
                .to_str()
                .unwrap()
                .split('-')
                .collect();
            let seat: usize = parts[2].parse().unwrap_or(0);
            (seat, "Unknown (legacy session)".to_string())
        };

        let replay: ReplayV1 = serde_json::from_slice(&fs::read(r_path)?)?;
        let trace = verify_replay_trace(&replay)?;
        let plies = trace.positions.len();
        total_plies += plies;
        let turns = (plies + 1) / 2;
        game_turns_list.push(turns as u32);

        let opp_seat = 1 - human_seat;
        let mut human_actor_turns = 0u32;
        let mut opp_actor_turns = 0u32;

        let mut human_cards: BTreeMap<u8, usize> = (0..=5).map(|v| (v, 0)).collect();
        let mut opp_cards: BTreeMap<u8, usize> = (0..=5).map(|v| (v, 0)).collect();

        let mut human_res_acq = 0usize;
        let mut human_res_bought = 0usize;
        let mut opp_res_acq = 0usize;
        let mut opp_res_bought = 0usize;

        let mut human_actions: BTreeMap<String, usize> = BTreeMap::new();
        let mut opp_actions: BTreeMap<String, usize> = BTreeMap::new();

        for pos in &trace.positions {
            let s = &pos.state;
            let actor = pos.recorded_actor;
            let action = pos.recorded_action;
            let me = &s.players[actor.index()];
            let is_human = actor.0 as usize == human_seat;
            let act_kind = action_kind(&action).to_string();

            if is_human {
                human_actor_turns += 1;
                *human_actions.entry(act_kind).or_default() += 1;
            } else {
                opp_actor_turns += 1;
                *opp_actions.entry(act_kind).or_default() += 1;
            }

            match action {
                Action::BuyMarket { tier, slot } => {
                    if let Some(cid) = s.market[tier.index()][slot as usize] {
                        let vp = card(cid).prestige;
                        if is_human {
                            *human_cards.entry(vp).or_default() += 1;
                        } else {
                            *opp_cards.entry(vp).or_default() += 1;
                        }
                    }
                }
                Action::BuyReserved { slot } => {
                    if (slot as usize) < me.reserved.len() {
                        let cid = me.reserved[slot as usize].card;
                        let vp = card(cid).prestige;
                        if is_human {
                            human_res_bought += 1;
                            *human_cards.entry(vp).or_default() += 1;
                        } else {
                            opp_res_bought += 1;
                            *opp_cards.entry(vp).or_default() += 1;
                        }
                    }
                }
                Action::ReserveMarket { .. } | Action::ReserveDeck { .. } => {
                    if is_human {
                        human_res_acq += 1;
                    } else {
                        opp_res_acq += 1;
                    }
                }
                _ => {}
            }
        }

        let mut final_state = trace.positions.last().unwrap().state.clone();
        final_state.apply(trace.positions.last().unwrap().recorded_action)?;

        let hs = final_state.players[human_seat].prestige;
        let os = final_state.players[opp_seat].prestige;
        let margin = (hs as i32 - os as i32).abs() as f64;
        game_margins_list.push(margin);

        let hn = final_state.players[human_seat].nobles.len();
        let on = final_state.players[opp_seat].nobles.len();

        let winners = &replay.result.winners;
        let is_tie = winners.len() > 1 || (winners.contains(&0) && winners.contains(&1));
        let human_won = !is_tie && winners.contains(&(human_seat as u8));

        samples.push(GameSample {
            human_seat,
            opp_name,
            human_score: hs,
            opp_score: os,
            human_won,
            is_tie,
            human_turns: human_actor_turns,
            opp_turns: opp_actor_turns,
            human_nobles: hn,
            opp_nobles: on,
            human_cards,
            opp_cards,
            human_bonuses: final_state.players[human_seat].bonuses,
            opp_bonuses: final_state.players[opp_seat].bonuses,
            human_res_acq,
            human_res_bought,
            opp_res_acq,
            opp_res_bought,
            human_actions,
            opp_actions,
        });
    }

    let total_games = samples.len();
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
    let mean_victory_margin = game_margins_list.iter().sum::<f64>() / total_games as f64;

    let build_perspective = |subset: &[&GameSample], is_human_target: bool| -> PerspectiveMetrics {
        let n = subset.len();
        if n == 0 {
            return PerspectiveMetrics::default();
        }
        let mut wins = 0;
        let mut ties = 0;
        let mut losses = 0;
        let mut total_score = 0u64;
        let mut total_turns = 0u64;
        let mut total_nobles = 0usize;
        let mut games_with_nobles = 0usize;
        let mut cards_by_vp: BTreeMap<u8, usize> = (0..=5).map(|v| (v, 0)).collect();
        let mut bonuses_sum = [0u64; 5];
        let mut res_acq = 0usize;
        let mut res_bought = 0usize;
        let mut action_dist: BTreeMap<String, usize> = BTreeMap::new();

        for s in subset {
            let won = if is_human_target {
                s.human_won
            } else {
                !s.human_won && !s.is_tie
            };
            if s.is_tie {
                ties += 1;
            } else if won {
                wins += 1;
            } else {
                losses += 1;
            }

            let sc = if is_human_target {
                s.human_score as u64
            } else {
                s.opp_score as u64
            };
            total_score += sc;

            let tr = if is_human_target {
                s.human_turns as u64
            } else {
                s.opp_turns as u64
            };
            total_turns += tr;

            let nb = if is_human_target {
                s.human_nobles
            } else {
                s.opp_nobles
            };
            total_nobles += nb;
            if nb > 0 {
                games_with_nobles += 1;
            }

            let cmap = if is_human_target {
                &s.human_cards
            } else {
                &s.opp_cards
            };
            for (&vp, &cnt) in cmap {
                *cards_by_vp.entry(vp).or_default() += cnt;
            }

            let b_arr = if is_human_target {
                &s.human_bonuses
            } else {
                &s.opp_bonuses
            };
            for c in 0..5 {
                bonuses_sum[c] += b_arr[c] as u64;
            }

            if is_human_target {
                res_acq += s.human_res_acq;
                res_bought += s.human_res_bought;
            } else {
                res_acq += s.opp_res_acq;
                res_bought += s.opp_res_bought;
            }

            let adist = if is_human_target {
                &s.human_actions
            } else {
                &s.opp_actions
            };
            for (k, &cnt) in adist {
                *action_dist.entry(k.clone()).or_default() += cnt;
            }
        }

        let mean_prestige = total_score as f64 / n as f64;
        let vp_per_turn = total_score as f64 / total_turns.max(1) as f64;
        let vp_per_ply = total_score as f64 / (total_turns * 2).max(1) as f64;
        let mean_nobles = total_nobles as f64 / n as f64;
        let games_with_nobles_percent = 100.0 * games_with_nobles as f64 / n as f64;

        let mean_cards_by_vp: BTreeMap<u8, f64> = cards_by_vp
            .iter()
            .map(|(&vp, &cnt)| (vp, cnt as f64 / n as f64))
            .collect();

        let total_bonuses: u64 = bonuses_sum.iter().sum();
        let mean_permanent_bonuses = total_bonuses as f64 / n as f64;

        let mean_bonuses_by_color: BTreeMap<String, f64> = bonuses_sum
            .iter()
            .enumerate()
            .map(|(c, &sum)| (color_name(c).to_string(), sum as f64 / n as f64))
            .collect();

        let mean_reserves_acquired = res_acq as f64 / n as f64;
        let mean_reserves_bought = res_bought as f64 / n as f64;
        let mean_reserves_stranded = (res_acq.saturating_sub(res_bought)) as f64 / n as f64;
        let reserve_redemption_rate_percent = 100.0 * res_bought as f64 / res_acq.max(1) as f64;

        let total_acts: usize = action_dist.values().sum();
        let action_percentages: BTreeMap<String, f64> = action_dist
            .iter()
            .map(|(k, &cnt)| (k.clone(), 100.0 * cnt as f64 / total_acts.max(1) as f64))
            .collect();

        PerspectiveMetrics {
            games_played: n,
            wins,
            ties,
            losses,
            win_rate_percent: 100.0 * wins as f64 / n as f64,
            mean_prestige,
            total_prestige: total_score,
            total_turns,
            vp_per_turn,
            vp_per_ply,
            mean_nobles,
            games_with_nobles,
            games_with_nobles_percent,
            mean_cards_by_vp,
            total_cards_by_vp: cards_by_vp,
            mean_permanent_bonuses,
            mean_bonuses_by_color,
            mean_reserves_acquired,
            mean_reserves_bought,
            mean_reserves_stranded,
            reserve_redemption_rate_percent,
            action_distribution: action_dist,
            action_percentages,
        }
    };

    let all_refs: Vec<&GameSample> = samples.iter().collect();
    let p0_refs: Vec<&GameSample> = samples.iter().filter(|s| s.human_seat == 0).collect();
    let p1_refs: Vec<&GameSample> = samples.iter().filter(|s| s.human_seat == 1).collect();

    let human_overall = build_perspective(&all_refs, true);
    let human_as_p0 = build_perspective(&p0_refs, true);
    let human_as_p1 = build_perspective(&p1_refs, true);
    let opponents_overall = build_perspective(&all_refs, false);

    let mut opponents_breakdown: BTreeMap<String, String> = BTreeMap::new();
    let mut opp_groups: BTreeMap<String, (usize, usize)> = BTreeMap::new();
    for s in &samples {
        let entry = opp_groups.entry(s.opp_name.clone()).or_insert((0, 0));
        entry.0 += 1;
        if s.human_won {
            entry.1 += 1;
        }
    }
    for (name, (tot, hw)) in opp_groups {
        opponents_breakdown.insert(
            name,
            format!(
                "{hw} wins / {tot} games ({:.1}%)",
                100.0 * hw as f64 / tot as f64
            ),
        );
    }

    Ok(HumanPlayerReport {
        format: "effective-splendor-human-performance-metrics-v1".to_string(),
        version: 1,
        total_games,
        total_plies,
        mean_plies: total_plies as f64 / total_games as f64,
        mean_turns,
        median_turns,
        min_turns,
        max_turns,
        mean_victory_margin,
        human_first_p0_games: p0_refs.len(),
        human_second_p1_games: p1_refs.len(),
        human_overall,
        human_as_p0_first: human_as_p0,
        human_as_p1_second: human_as_p1,
        opponents_overall,
        opponents_breakdown,
    })
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let human_dir = Path::new("local-artifacts/m20-human-play");
    let report = analyze_human_games(human_dir)?;

    let out_json_path = human_dir.join("human-metrics-summary.json");
    let mut f = File::create(&out_json_path)?;
    f.write_all(serde_json::to_string_pretty(&report)?.as_bytes())?;
    f.write_all(b"\n")?;
    println!("Saved human metrics to: {}", out_json_path.display());

    let tracked_path = Path::new("benchmarks/human-expert-metrics-v1.json");
    let mut tf = File::create(tracked_path)?;
    tf.write_all(serde_json::to_string_pretty(&report)?.as_bytes())?;
    tf.write_all(b"\n")?;
    println!(
        "Saved tracked human benchmark metrics to: {}",
        tracked_path.display()
    );

    println!("{}", serde_json::to_string_pretty(&report)?);
    Ok(())
}
