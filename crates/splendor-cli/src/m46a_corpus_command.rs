//! M46A frozen corpus generator: replay -> per-game successor records.
//!
//! For one verified replay file, this command:
//! - reconstructs the game step by step;
//! - collects eligible roots (`Phase::Main` with >= 2 legal actions);
//! - requires at least 8 eligible roots (fail closed otherwise);
//! - selects exactly 8 roots at `i_k = floor((2k+1)N/16)`;
//! - for each root, rebuilds the viewer observation + visible history,
//!   builds the information set via `build_information_set_v1`, samples the
//!   4 frozen determinizations (`sample_seed = 20_260_703`), enumerates every
//!   canonical legal action, forces it in each determinization, and records
//!   the exact successor with StaticEvaluatorV1 teacher utilities,
//!   nonterminal progress labels, relational features, mechanics labels,
//!   and identity/state hashes.
//!
//! No search, no learning, no Arena. Deterministic output for a fixed replay.

use std::fs::File;
use std::path::PathBuf;

use serde::Serialize;
use splendor_belief::{build_information_set_v1, sample_determinization_v1};
use splendor_catalog::{all_nobles, card};
use splendor_core::{
    full_state_hash, observation_hash, visible_events, Action, Audience, FullState, GameConfig,
    GemColor, Phase, PlayerId, Ruleset,
};
use splendor_replay::{verify_replay, ReplayV1};
use splendor_search::{canonical_order, StaticEvaluatorV1};

const DETERMINIZATION_SEED: u64 = 20_260_703;
const DETERMINIZATION_COUNT: u64 = 4;
const ROOTS_PER_GAME: usize = 8;

#[derive(Debug, Clone, Serialize)]
struct IdentityTriple {
    observation_hash: String,
    visible_history_hash: String,
    information_set_hash: String,
}

#[derive(Debug, Clone, Serialize)]
struct CardFeat {
    cost: [u8; 5],
    prestige: u8,
    tier: u8,
    bonus: u8,
    role: u8,
    discounted: [u8; 5],
    shortfall: [u8; 5],
    gold_needed: u8,
    affordable: bool,
}

#[derive(Debug, Clone, Serialize)]
struct NobleFeat {
    req: [u8; 5],
    prestige: u8,
    deficit: [u8; 5],
    claimable: bool,
}

#[derive(Debug, Clone, Serialize)]
struct PlayerFeatures {
    cards: Vec<CardFeat>,
    nobles: Vec<NobleFeat>,
    player_raw: Vec<u8>,
    global_raw: Vec<u8>,
    affordable_count: u8,
    max_prestige: u8,
    claimable: u8,
    min_deficit: u8,
    has_nobles: bool,
}

#[derive(Debug, Clone, Serialize)]
struct SuccRecord {
    det_index: u64,
    terminal: bool,
    teacher_utility: Vec<i64>,
    progress: Vec<i64>,
    state_hash: String,
    players: Vec<PlayerFeatures>,
}

#[derive(Debug, Clone, Serialize)]
struct ActionRecord {
    action: Action,
    successors: Vec<SuccRecord>,
}

#[derive(Debug, Clone, Serialize)]
struct RootRecord {
    step_index: usize,
    decision_ply: u32,
    actor: PlayerId,
    identity: IdentityTriple,
    actions: Vec<ActionRecord>,
}

#[derive(Debug, Clone, Serialize)]
struct GameCorpus {
    game_seed: u64,
    player_count: u8,
    eligible_root_count: usize,
    roots: Vec<RootRecord>,
}

fn fail_closed(msg: String) -> ! {
    eprintln!("FAIL CLOSED: {msg}");
    std::process::exit(1);
}

fn player_features(state: &FullState, player_idx: usize, ruleset: Ruleset) -> PlayerFeatures {
    let _ = ruleset;
    let player = &state.players[player_idx];
    let opp_idx = 1 - player_idx;

    // Cards: market (role 0) + acting player's own reserves (role 1).
    let mut cards = Vec::new();
    let mut affordable_count = 0u8;
    let mut max_prestige = 0u8;
    let mut consider =
        |cost: [u8; 5], pres: u8, tier: u8, bonus: u8, role: u8, cards: &mut Vec<CardFeat>| {
            let mut discounted = [0u8; 5];
            let mut shortfall = [0u8; 5];
            let mut gold_needed = 0u8;
            for c in GemColor::ALL {
                let ci = c.index();
                let need = cost[ci].saturating_sub(player.bonuses[ci]);
                let have = player.tokens.color(c);
                discounted[ci] = need;
                shortfall[ci] = need.saturating_sub(have);
                gold_needed = gold_needed.saturating_add(need.saturating_sub(have));
            }
            let affordable = player.tokens.gold >= gold_needed;
            // Cross-check against the authoritative affordability predicate.
            debug_assert_eq!(affordable, player.can_afford(cost));
            if affordable {
                affordable_count = affordable_count.saturating_add(1);
                max_prestige = max_prestige.max(pres);
            }
            cards.push(CardFeat {
                cost,
                prestige: pres,
                tier,
                bonus,
                role,
                discounted,
                shortfall,
                gold_needed,
                affordable,
            });
        };

    for card_id in state.market.iter().flat_map(|row| row.iter().flatten()) {
        let def = card(*card_id);
        consider(
            def.cost,
            def.prestige,
            def.tier.index() as u8,
            def.bonus.index() as u8,
            0,
            &mut cards,
        );
    }
    for reserved in &player.reserved {
        let def = card(reserved.card);
        consider(
            def.cost,
            def.prestige,
            def.tier.index() as u8,
            def.bonus.index() as u8,
            1,
            &mut cards,
        );
    }

    if affordable_count > 15 {
        fail_closed(format!(
            "affordable count {affordable_count} exceeds 16-class range"
        ));
    }
    if max_prestige > 5 {
        fail_closed(format!("max prestige {max_prestige} exceeds 6-class range"));
    }

    // Nobles visible on the board, scored for this player.
    let mut nobles = Vec::new();
    let mut claimable = 0u8;
    let mut min_deficit = u8::MAX;
    for &noble_id in &state.nobles {
        let def = &all_nobles()[noble_id.index()];
        let mut deficit = [0u8; 5];
        let mut total = 0u8;
        for c in GemColor::ALL {
            let ci = c.index();
            let d = def.requirements[ci].saturating_sub(player.bonuses[ci]);
            deficit[ci] = d;
            total = total.saturating_add(d);
        }
        let is_claimable = total == 0;
        if is_claimable {
            claimable = claimable.saturating_add(1);
        }
        min_deficit = min_deficit.min(total);
        nobles.push(NobleFeat {
            req: def.requirements,
            prestige: def.prestige,
            deficit,
            claimable: is_claimable,
        });
    }
    let has_nobles = !state.nobles.is_empty();
    if !has_nobles {
        min_deficit = 255;
    }
    if claimable > 5 {
        fail_closed(format!(
            "claimable nobles {claimable} exceeds 6-class range"
        ));
    }
    if has_nobles && min_deficit > 20 {
        fail_closed(format!(
            "min noble deficit {min_deficit} exceeds 21-class range"
        ));
    }

    // Player raw: self then opponent (2-player corpus only).
    let opp = &state.players[opp_idx];
    let mut player_raw = Vec::with_capacity(26);
    for p in [player, opp] {
        player_raw.push(p.prestige);
        player_raw.extend_from_slice(&p.bonuses);
        for c in GemColor::ALL {
            player_raw.push(p.tokens.color(c));
        }
        player_raw.push(p.tokens.gold);
        player_raw.push(p.reserved.len() as u8);
    }

    // Global raw: bank, deck counts, endgame state.
    let mut global_raw = Vec::with_capacity(14);
    for c in GemColor::ALL {
        global_raw.push(state.bank.color(c));
    }
    global_raw.push(state.bank.gold);
    for deck in &state.decks {
        global_raw.push(deck.len() as u8);
    }
    global_raw.push(u8::from(state.end_game_triggered));
    match state.turns_remaining_in_final_round {
        Some(t) => {
            global_raw.push(t);
            global_raw.push(1);
        }
        None => {
            global_raw.push(0);
            global_raw.push(0);
        }
    }
    global_raw.push(state.consecutive_forced_passes);

    PlayerFeatures {
        cards,
        nobles,
        player_raw,
        global_raw,
        affordable_count,
        max_prestige,
        claimable,
        min_deficit,
        has_nobles,
    }
}

pub fn run_m46a_generate_corpus(args: &[String]) -> i32 {
    let replay_path = match args.iter().position(|a| a == "--replay") {
        Some(pos) => PathBuf::from(&args[pos + 1]),
        None => {
            eprintln!("usage: m46a-generate-corpus --replay <path> --out <path>");
            return 2;
        }
    };
    let out_path = match args.iter().position(|a| a == "--out") {
        Some(pos) => PathBuf::from(&args[pos + 1]),
        None => {
            eprintln!("usage: m46a-generate-corpus --replay <path> --out <path>");
            return 2;
        }
    };

    let ruleset = Ruleset::base_v1();
    let file = File::open(&replay_path).unwrap_or_else(|e| {
        fail_closed(format!("cannot open replay {}: {e}", replay_path.display()));
    });
    let replay: ReplayV1 = serde_json::from_reader(file).unwrap_or_else(|e| {
        fail_closed(format!(
            "cannot parse replay {}: {e}",
            replay_path.display()
        ));
    });
    if verify_replay(&replay).is_err() {
        fail_closed(format!(
            "replay verification failed: {}",
            replay_path.display()
        ));
    }
    if replay.player_count != 2 {
        fail_closed(format!(
            "M46A corpus requires 2-player games, got {}",
            replay.player_count
        ));
    }

    // Walk the game, collecting eligible root step indices.
    let (mut state, _setup) = FullState::new(GameConfig {
        player_count: replay.player_count,
        seed: replay.seed,
        ruleset,
    })
    .unwrap_or_else(|e| fail_closed(format!("setup failed: {e:?}")));
    let mut eligible: Vec<usize> = Vec::new();
    for (step_index, step) in replay.steps.iter().enumerate() {
        let _ = step;
        if state.phase == Phase::Main && state.legal_actions().len() >= 2 {
            eligible.push(step_index);
        }
        if state.apply(replay.steps[step_index].action).is_err() {
            fail_closed(format!("replay apply failed at step {step_index}"));
        }
    }

    let n = eligible.len();
    if n < ROOTS_PER_GAME {
        fail_closed(format!(
            "game {} has only {n} eligible roots (< {ROOTS_PER_GAME})",
            replay.seed
        ));
    }
    let selected: Vec<usize> = (0..ROOTS_PER_GAME)
        .map(|k| ((2 * k + 1) * n) / 16)
        .collect();

    let mut roots = Vec::with_capacity(ROOTS_PER_GAME);
    for &step_index in &selected {
        // Reconstruct state + viewer visible history at this step.
        let (mut st, setup) = FullState::new(GameConfig {
            player_count: replay.player_count,
            seed: replay.seed,
            ruleset,
        })
        .unwrap_or_else(|e| fail_closed(format!("setup failed: {e:?}")));
        let actor = replay.steps[step_index].actor;
        let mut visible_history = visible_events(&setup.events, Audience::Player(actor));
        for step in replay.steps.iter().take(step_index) {
            let res = st.apply(step.action).unwrap_or_else(|e| {
                fail_closed(format!("replay apply failed: {e:?}"));
            });
            visible_history.extend(visible_events(&res.events, Audience::Player(actor)));
        }

        let obs = st.observation(actor);
        let info_set =
            build_information_set_v1(ruleset, &obs, &visible_history).unwrap_or_else(|e| {
                fail_closed(format!(
                    "information set build failed at step {step_index}: {e:?}"
                ))
            });
        let identity = IdentityTriple {
            observation_hash: observation_hash(&obs).to_string(),
            visible_history_hash: info_set.visible_history_hash().as_str().to_string(),
            information_set_hash: info_set.information_set_hash().as_str().to_string(),
        };

        // Sample the 4 frozen determinizations.
        let mut det_states = Vec::new();
        let mut expected_actions: Option<Vec<Action>> = None;
        for det_index in 0..DETERMINIZATION_COUNT {
            let det = sample_determinization_v1(&info_set, DETERMINIZATION_SEED, det_index)
                .unwrap_or_else(|e| {
                    fail_closed(format!("determinization {det_index} failed: {e:?}"))
                });
            let actions = canonical_order(&det.state().legal_actions());
            if actions.is_empty() {
                fail_closed(format!("empty legal set in determinization {det_index}"));
            }
            match &expected_actions {
                None => expected_actions = Some(actions.clone()),
                Some(exp) => {
                    if exp != &actions {
                        fail_closed(format!(
                            "root action set mismatch across determinizations at step {step_index}"
                        ));
                    }
                }
            }
            det_states.push(det);
        }
        let actions = expected_actions.unwrap();

        let mut action_records = Vec::with_capacity(actions.len());
        for action in actions {
            let mut successors = Vec::with_capacity(DETERMINIZATION_COUNT as usize);
            for (det_index, det) in det_states.iter().enumerate() {
                let mut child = det.state().clone();
                child.apply(action).unwrap_or_else(|e| {
                    fail_closed(format!("force action failed: {e:?}"));
                });
                let terminal = child.is_terminal();
                let teacher_utility = StaticEvaluatorV1::utilities(&child).unwrap_or_else(|e| {
                    fail_closed(format!("teacher utility failed: {e:?}"));
                });
                let progress = StaticEvaluatorV1::nonterminal_progress(&child);
                let state_hash = full_state_hash(&child).as_str().to_string();
                let players = (0..2)
                    .map(|p| player_features(&child, p, ruleset))
                    .collect();
                successors.push(SuccRecord {
                    det_index: det_index as u64,
                    terminal,
                    teacher_utility,
                    progress,
                    state_hash,
                    players,
                });
            }
            action_records.push(ActionRecord { action, successors });
        }

        roots.push(RootRecord {
            step_index,
            decision_ply: step_index as u32 + 1,
            actor,
            identity,
            actions: action_records,
        });
    }

    let corpus = GameCorpus {
        game_seed: replay.seed,
        player_count: replay.player_count,
        eligible_root_count: n,
        roots,
    };

    let out_file = File::create(&out_path).unwrap_or_else(|e| {
        fail_closed(format!("cannot create {}: {e}", out_path.display()));
    });
    serde_json::to_writer(out_file, &corpus).unwrap_or_else(|e| {
        fail_closed(format!("cannot write {}: {e}", out_path.display()));
    });
    println!(
        "M46A corpus game written: {:?} ({} roots)",
        out_path,
        corpus.roots.len()
    );
    0
}
