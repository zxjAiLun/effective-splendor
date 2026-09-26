//! Offline-only S4 replay economics diagnostic. No new matches or policy RNG.
//! Usage: cargo run --release -p splendor-cli --example s4_replay_economics --
//!        <pilot-dir> <expected-scorer-version> <create-only-output.json>
//! A complete manifest is required. Every file hash, whole replay, final state,
//! candidate identity and recorded candidate action's argmax membership is checked.
//! FullState stays in this offline host; the scorer only receives Observation/legal.
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use splendor_agent::{heuristic_v02_term_scores, HeuristicV02Terms, HEURISTIC_V02_AGENT_VERSION};
use splendor_catalog::{all_nobles, card, CardDef, CardId, GemColor};
use splendor_core::{full_state_hash, Action, Gems, Observation, Phase, PlayerId};
use splendor_replay::{verify_replay_trace, ReplayV1};
use std::{collections::BTreeSet, fs, io::Write, path::Path};

fn digest(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}

fn gap(def: &CardDef, tokens: Gems, bonuses: [u8; 5]) -> i64 {
    let missing: i64 = GemColor::ALL
        .iter()
        .map(|c| {
            i64::from(
                def.cost[c.index()]
                    .saturating_sub(bonuses[c.index()])
                    .saturating_sub(tokens.color(*c)),
            )
        })
        .sum();
    (missing - i64::from(tokens.gold)).max(0)
}

fn affordable_vp(targets: &[CardId], tokens: Gems, bonuses: [u8; 5]) -> u8 {
    targets
        .iter()
        .filter(|id| gap(card(**id), tokens, bonuses) == 0)
        .map(|id| card(*id).prestige)
        .max()
        .unwrap_or(0)
}

fn noble_gap(id: splendor_catalog::NobleId, bonuses: [u8; 5]) -> u16 {
    GemColor::ALL
        .iter()
        .map(|c| {
            u16::from(
                all_nobles()[id.index()]
                    .requires(*c)
                    .saturating_sub(bonuses[c.index()]),
            )
        })
        .sum()
}

fn kind(action: Action) -> &'static str {
    match action {
        Action::TakeTokens { .. } => "take",
        Action::BuyMarket { .. } => "buy_market",
        Action::BuyReserved { .. } => "buy_reserved",
        Action::ReserveMarket { .. } => "reserve_market",
        Action::ReserveDeck { .. } => "reserve_deck",
        Action::ChooseNoble { .. } => "choose_noble",
        Action::Pass => "pass",
    }
}

fn action_card(obs: &Observation, action: Action) -> Option<CardId> {
    match action {
        Action::BuyMarket { tier, slot } | Action::ReserveMarket { tier, slot, .. } => {
            obs.public.market[tier.index()][slot as usize]
        }
        Action::BuyReserved { slot } => Some(obs.private.reserved[slot as usize].card),
        _ => None,
    }
}

fn detail(obs: &Observation, action: Action, terms: &HeuristicV02Terms) -> Value {
    json!({"action": action, "kind": kind(action), "card": action_card(obs, action).map(|id| {
        let d = card(id); json!({"id": id.0, "tier": d.tier.level(), "vp": d.prestige, "bonus": d.bonus.name(), "cost": d.cost})
    }), "score": terms.total(), "terms": terms})
}

fn inspect(root: &Path, row: &Value) -> Result<Value, Box<dyn std::error::Error>> {
    let opponent = row["opponent"].as_str().ok_or("opponent missing")?;
    let seed = row["seed"].as_u64().ok_or("seed missing")?;
    let seat = row["candidate_seat"].as_u64().ok_or("seat missing")? as u8;
    assert!(seat < 2 && row["rotation"] == seat);
    let dir = root
        .join("games")
        .join(opponent)
        .join(format!("seed-{seed}"))
        .join(format!("r{seat}"));
    for (file, key) in [
        ("match-config.json", "config_sha256"),
        ("arena-report.json", "report_sha256"),
        ("match-replay.json", "replay_sha256"),
    ] {
        assert_eq!(
            digest(&fs::read(dir.join(file))?),
            row[key].as_str().ok_or("hash missing")?,
            "{file}"
        );
    }
    let replay: ReplayV1 = serde_json::from_slice(&fs::read(dir.join("match-replay.json"))?)?;
    let report: Value = serde_json::from_slice(&fs::read(dir.join("arena-report.json"))?)?;
    assert_eq!(
        report["agents"][seat as usize]["agent_version"],
        HEURISTIC_V02_AGENT_VERSION
    );
    assert_eq!(report["outcome"]["status"], "completed");
    assert_eq!(replay.seed, seed);
    let trace = verify_replay_trace(&replay)?;
    assert_eq!(
        trace.verified.result.winners,
        serde_json::from_value::<Vec<u8>>(row["winners"].clone())?
    );
    assert_eq!(trace.verified.final_state_hash, row["replay_final_hash"]);
    assert_eq!(
        trace.positions.len(),
        row["completed_plies"].as_u64().ok_or("plies missing")? as usize
    );
    let candidate = PlayerId(seat);
    let mut decisions = Vec::new();
    let mut actions = Vec::new();
    let mut main_turns = [0usize; 2];
    for pos in &trace.positions {
        let actor = pos.recorded_actor;
        let s = &pos.state;
        let obs = s.observation(actor);
        let me = &obs.public.players[actor.index()];
        let action = pos.recorded_action;
        if s.phase == Phase::Main {
            main_turns[actor.index()] += 1;
        }
        let mut child = s.clone();
        child.apply(action)?;
        // Use actual recorded transitions only; never invent a pending noble choice.
        assert_eq!(
            full_state_hash(&child).as_str(),
            replay.steps[pos.ply as usize].state_hash_after.as_str()
        );
        actions.push(json!({"ply": pos.ply, "actor": actor.0, "main_turn": main_turns[actor.index()], "kind": kind(action), "action": action,
            "card": action_card(&obs, action).map(|id| json!({"id": id.0, "vp": card(id).prestige, "tier": card(id).tier.level(), "gap": gap(card(id), me.tokens, me.bonuses)})),
            "gold_before": me.tokens.gold, "gold_after": child.players[actor.index()].tokens.gold,
            "reserved_before": me.reserved_count, "reserved_after": child.players[actor.index()].reserved.len(),
            "prestige_before": me.prestige, "prestige_after": child.players[actor.index()].prestige,
            "bonuses_before": me.bonuses, "bonuses_after": child.players[actor.index()].bonuses,
            "nobles_before": me.nobles, "nobles_after": child.players[actor.index()].nobles}));
        if actor != candidate {
            continue;
        }
        let legal = s.legal_actions();
        let scores = heuristic_v02_term_scores(&obs, &legal);
        let chosen = legal
            .iter()
            .position(|a| *a == action)
            .ok_or("recorded action illegal")?;
        let max_score = scores
            .iter()
            .map(HeuristicV02Terms::total)
            .max()
            .ok_or("no scores")?;
        assert_eq!(
            scores[chosen].total(),
            max_score,
            "candidate policy mismatch: seed={seed} seat={seat} ply={}",
            pos.ply
        );
        let discounts: u16 = me.bonuses.iter().map(|x| u16::from(*x)).sum();
        let lead = obs
            .public
            .players
            .iter()
            .map(|p| p.prestige)
            .max()
            .unwrap_or(0);
        let phase = if obs.public.end_game_triggered || lead >= 12 || discounts >= 9 {
            "Score"
        } else if discounts <= 4 {
            "Ultra"
        } else {
            "Build"
        };
        let targets: Vec<_> = obs
            .public
            .market
            .iter()
            .flatten()
            .flatten()
            .copied()
            .chain(obs.private.reserved.iter().map(|r| r.card))
            .collect();
        let held: Vec<_> = obs.private.reserved.iter().map(|r| r.card).collect();
        let ready_vp_before = affordable_vp(&targets, me.tokens, me.bonuses);
        let held_vp_before = affordable_vp(&held, me.tokens, me.bonuses);
        let mut ready_takes = Vec::new();
        for (index, a) in legal.iter().enumerate() {
            if let Action::TakeTokens { take, give_back } = a {
                let tokens = me
                    .tokens
                    .saturating_add(*take)
                    .checked_sub(*give_back)
                    .ok_or("invalid return")?;
                let vp = affordable_vp(&targets, tokens, me.bonuses);
                if vp > ready_vp_before {
                    ready_takes.push(json!({"index": index, "ready_vp": vp, "held_ready_vp": affordable_vp(&held, tokens, me.bonuses),
                        "became_ready": targets.iter().filter(|id| gap(card(**id), me.tokens, me.bonuses) > 0 && gap(card(**id), tokens, me.bonuses) == 0).map(|id| json!({"id": id.0, "vp": card(*id).prestige, "reserved": held.contains(id)})).collect::<Vec<_>>(),
                        "detail": detail(&obs, *a, &scores[index])}));
                }
            }
        }
        ready_takes.sort_by_key(|x| {
            (
                -x["ready_vp"].as_i64().unwrap(),
                -x["detail"]["score"].as_i64().unwrap(),
                x["index"].as_u64().unwrap(),
            )
        });
        // For reserves include the actual gold/return effects too, but assess
        // only PRE-existing visible targets (never the new blind-reserved card).
        let chosen_ready_vp = if matches!(
            action,
            Action::TakeTokens { .. } | Action::ReserveMarket { .. } | Action::ReserveDeck { .. }
        ) {
            affordable_vp(&targets, child.players[actor.index()].tokens, me.bonuses)
        } else {
            ready_vp_before
        };
        let best_buy = legal
            .iter()
            .enumerate()
            .filter(|(_, a)| matches!(a, Action::BuyMarket { .. } | Action::BuyReserved { .. }))
            .max_by_key(|(i, _)| scores[*i].total())
            .map(|(i, a)| detail(&obs, *a, &scores[i]));
        let reserved: Vec<_> = obs.private.reserved.iter().map(|r| {
            let d = card(r.card);
            json!({"id": r.card.0, "tier": d.tier.level(), "vp": d.prestige, "gap": gap(d, me.tokens, me.bonuses),
                "buyable": legal.contains(&Action::BuyReserved { slot: r.slot }), "from_deck": r.from_deck})
        }).collect();
        let nobles: Vec<_> = obs.public.nobles.iter().map(|id| json!({"id": id.0, "my_gap": noble_gap(*id, me.bonuses),
            "opponent_gap": obs.public.players.iter().filter(|p| p.id != actor).map(|p| noble_gap(*id, p.bonuses)).min()})).collect();
        let effect = |field: fn(&HeuristicV02Terms) -> i64| {
            let no_term_best = scores.iter().map(|t| t.total() - field(t)).max().unwrap();
            scores[chosen].total() - field(&scores[chosen]) < no_term_best
        };
        decisions.push(json!({"ply": pos.ply, "main_turn": main_turns[actor.index()], "phase": phase, "discounts": discounts,
            "end_game_triggered": obs.public.end_game_triggered, "prestige": me.prestige, "lead_prestige": lead, "tokens": me.tokens, "bonuses": me.bonuses,
            "reserved": reserved, "nobles": nobles, "chosen": detail(&obs, action, &scores[chosen]), "best_buy": best_buy,
            "ready_vp_before": ready_vp_before, "held_ready_vp_before": held_vp_before, "chosen_ready_vp": chosen_ready_vp,
            "best_ready_take": ready_takes.first(), "ready_take_count": ready_takes.len(),
            "remove_three_vp_changes_chosen_argmax": effect(|t| t.noble_race_three_vp),
            "remove_reserved_bonus_changes_chosen_argmax": effect(|t| t.noble_race_reserved),
            "argmax_count": scores.iter().filter(|t| t.total() == max_score).count()}));
    }
    let last = trace.positions.last().ok_or("empty replay")?;
    let mut final_state = last.state.clone();
    final_state.apply(last.recorded_action)?;
    assert!(final_state.is_terminal());
    assert_eq!(
        full_state_hash(&final_state).as_str(),
        trace.verified.final_state_hash
    );
    let final_players: Vec<_> = final_state.players.iter().map(|p| json!({"seat": p.id.0, "prestige": p.prestige,
        "purchased_count": p.purchased.len(), "card_vp": p.purchased.iter().map(|id| u32::from(card(*id).prestige)).sum::<u32>(),
        "nobles": p.nobles, "reserved": p.reserved.iter().map(|r| r.card.0).collect::<Vec<_>>(), "main_turns": main_turns[p.id.index()]})).collect();
    Ok(
        json!({"opponent": opponent, "seed": seed, "rotation": seat, "score_bps": row["score_bps"], "final_players": final_players, "actions": actions, "decisions": decisions}),
    )
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args().collect();
    if args.len() != 4 {
        return Err("need pilot-dir expected-scorer-version new-output.json".into());
    }
    assert_eq!(
        args[2], HEURISTIC_V02_AGENT_VERSION,
        "rebuild/mismatch: use the exact recorded policy"
    );
    let root = Path::new(&args[1]);
    assert!(!Path::new(&args[3]).exists(), "output already exists");
    let bytes = fs::read(root.join("manifest.json"))?;
    let manifest: Value = serde_json::from_slice(&bytes)?;
    let rows = manifest["rows"].as_array().ok_or("manifest rows missing")?;
    let mut keys = BTreeSet::new();
    let mut games = Vec::new();
    for row in rows {
        assert!(
            keys.insert(row["game_id"].as_str().ok_or("id missing")?.to_owned()),
            "duplicate game"
        );
        games.push(inspect(root, row)?);
    }
    let output = json!({"format": "s4-replay-economics-diagnostic-v1", "scorer_version": HEURISTIC_V02_AGENT_VERSION, "manifest_sha256": digest(&bytes), "games": games,
        "semantics": "complete verified recorded trajectories; observation-only scoring; argmax check without RNG reproduction; no new games/counterfactual outcomes"});
    let mut file = fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&args[3])?;
    file.write_all(serde_json::to_string(&output)?.as_bytes())?;
    file.write_all(b"\n")?;
    println!(
        "PASS: {} replays; {} candidate decisions; scorer {}; manifest {}",
        rows.len(),
        output["games"]
            .as_array()
            .unwrap()
            .iter()
            .map(|g| g["decisions"].as_array().unwrap().len())
            .sum::<usize>(),
        HEURISTIC_V02_AGENT_VERSION,
        digest(&bytes)
    );
    Ok(())
}
