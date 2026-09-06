//! M43A P0 Semantic & Invariant Tests (H0, H1, H2, H3).
//!
//! Verifies:
//! - H0: Branch identity matches corpus probe and manifest fail-closed
//! - H1: One-action reconstruction s' = T(s, a) reproduces branch replay state_hash_after exactly
//! - H2: Successor observation is strictly player-view from root_actor perspective
//! - H3: Blind-information boundary: real hidden-state mutations (ReserveDeck, BuyMarket, ReserveMarket, opponent blind reserve)

use std::path::Path;
use splendor_core::{
    full_state_hash, observation_hash, Action, GameConfig, Gems, PlayerId, Ruleset, Tier,
};
use splendor_replay::{verify_replay, ReplayRecorder, ReplayV1};

#[test]
fn test_h0_h1_h2_branch_reconstruction() {
    let repo_root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let state_dir = repo_root.join("local-artifacts/m41a-corpus/train/game-0000/branch-ply0016");
    assert!(
        state_dir.exists(),
        "H0 fail-closed: corpus state directory must exist at {}",
        state_dir.display()
    );

    let probe_val: serde_json::Value = serde_json::from_str(
        &std::fs::read_to_string(state_dir.join("state-probe.json")).expect("read state-probe.json"),
    )
    .unwrap();
    let manifest_val: serde_json::Value = serde_json::from_str(
        &std::fs::read_to_string(state_dir.join("state-manifest.json")).expect("read state-manifest.json"),
    )
    .unwrap();

    let branch_ply = probe_val["branch_ply"].as_u64().unwrap() as usize;
    let root_actor = probe_val["acting_seat"].as_u64().unwrap() as u8;
    let expected_state_hash = probe_val["state_hash"].as_str().unwrap();
    let expected_obs_hash = probe_val["observation_hash"].as_str().unwrap();

    let source_replay_path = state_dir.parent().unwrap().join("replay.json");
    assert!(
        source_replay_path.is_file(),
        "source replay must exist at {}",
        source_replay_path.display()
    );
    let source_replay: ReplayV1 =
        serde_json::from_str(&std::fs::read_to_string(&source_replay_path).unwrap()).unwrap();
    verify_replay(&source_replay).unwrap();

    // Replay prefix
    let (mut rec, _) = ReplayRecorder::new_with_setup(GameConfig {
        player_count: source_replay.player_count,
        seed: source_replay.seed,
        ruleset: Ruleset::base_v1(),
    })
    .unwrap();

    for step in &source_replay.steps[..branch_ply] {
        rec.apply(step.action).unwrap();
    }
    let source_state = rec.state();

    // H0 check: source state and observation hash match
    assert_eq!(full_state_hash(source_state).as_str(), expected_state_hash);
    let source_obs = source_state.observation(PlayerId(root_actor));
    assert_eq!(observation_hash(&source_obs).as_str(), expected_obs_hash);

    // H1 and H2 check across actions
    let actions = manifest_val["actions"].as_array().unwrap();
    assert!(!actions.is_empty(), "H0 fail-closed: actions must not be empty");

    for item in actions {
        let action_index = item["action_index"].as_u64().unwrap() as usize;
        let forced_action: Action =
            serde_json::from_value(item["forced_action"].clone()).unwrap();

        let mut child = source_state.clone();
        child.apply(forced_action).unwrap();
        let post_hash = full_state_hash(&child);

        // H1 check against branch replay (fail-closed, report and replay must exist)
        let branch_replay_path = state_dir
            .join(format!("action-{action_index:03}"))
            .join("replay.json");
        let branch_report_path = state_dir
            .join(format!("action-{action_index:03}"))
            .join("report.json");

        assert!(
            branch_replay_path.is_file(),
            "H1 fail-closed: branch replay must exist at {}",
            branch_replay_path.display()
        );
        assert!(
            branch_report_path.is_file(),
            "H1 fail-closed: branch report must exist at {}",
            branch_report_path.display()
        );

        let br_replay: ReplayV1 =
            serde_json::from_str(&std::fs::read_to_string(&branch_replay_path).unwrap()).unwrap();
        let step_after = &br_replay.steps[branch_ply];
        assert_eq!(
            post_hash.as_str(),
            step_after.state_hash_after.as_str(),
            "H1 failure on action {action_index}"
        );

        // H2: Player-view observation from root_actor
        let post_obs = child.observation(PlayerId(root_actor));
        assert_eq!(post_obs.viewer.0, root_actor);
        assert!(post_obs.private.reserved.len() <= 3);
    }
}

#[test]
fn test_h3_blind_information_boundary() {
    let (state, _) = splendor_core::FullState::new(GameConfig {
        player_count: 2,
        seed: 42,
        ruleset: Ruleset::base_v1(),
    })
    .unwrap();

    // -----------------------------------------------------------------------
    // Fixture 1: ReserveDeck
    // -----------------------------------------------------------------------
    let act_reserve_deck = Action::ReserveDeck {
        tier: Tier::One,
        give_back: Gems::ZERO,
    };

    // Base post-action state
    let mut s1 = state.clone();
    s1.apply(act_reserve_deck).unwrap();
    let obs_base = s1.observation(PlayerId(0));
    let hash_base = observation_hash(&obs_base);

    // Mutation 1A: Mutate deeper unseen cards (swap bottom two cards in Tier 1 deck)
    let mut s_deeper = state.clone();
    let dlen = s_deeper.decks[0].len();
    assert!(dlen >= 3, "deck must have >= 3 cards for deeper mutation test");
    s_deeper.decks[0].swap(0, 1); // swap bottom two cards
    s_deeper.apply(act_reserve_deck).unwrap();
    let obs_deeper = s_deeper.observation(PlayerId(0));
    let hash_deeper = observation_hash(&obs_deeper);
    // Deeper unseen deck order mutation must NOT change root actor observation
    assert_eq!(
        hash_base, hash_deeper,
        "H3 fail: deeper deck mutation leaked into player-view observation"
    );

    // Mutation 1B: Mutate drawn top card (swap top card with another card)
    let mut s_drawn = state.clone();
    s_drawn.decks[0].swap(dlen - 1, 0); // swap top card with bottom card
    s_drawn.apply(act_reserve_deck).unwrap();
    let obs_drawn = s_drawn.observation(PlayerId(0));
    let hash_drawn = observation_hash(&obs_drawn);
    // Mutating the card drawn into private reserve MUST change root actor observation
    assert_ne!(
        hash_base, hash_drawn,
        "H3 fail: drawn card identity was not visible to root actor"
    );

    // -----------------------------------------------------------------------
    // Fixture 2: ReserveMarket
    // -----------------------------------------------------------------------
    let act_reserve_market = Action::ReserveMarket {
        tier: Tier::One,
        slot: 0,
        give_back: Gems::ZERO,
    };

    let mut s2 = state.clone();
    s2.apply(act_reserve_market).unwrap();
    let obs_rm_base = s2.observation(PlayerId(0));
    let hash_rm_base = observation_hash(&obs_rm_base);

    // Deeper deck mutation: swap bottom cards of deck 0 -> market refill is from top, so deeper is invisible
    let mut s2_deeper = state.clone();
    s2_deeper.decks[0].swap(0, 1);
    s2_deeper.apply(act_reserve_market).unwrap();
    let obs_rm_deeper = s2_deeper.observation(PlayerId(0));
    assert_eq!(
        hash_rm_base, observation_hash(&obs_rm_deeper),
        "H3 fail: deeper deck mutation leaked in ReserveMarket"
    );

    // Refill card mutation: swap top card of deck 0 -> changes market refill card visible to player
    let mut s2_refill = state.clone();
    s2_refill.decks[0].swap(dlen - 1, 0);
    s2_refill.apply(act_reserve_market).unwrap();
    let obs_rm_refill = s2_refill.observation(PlayerId(0));
    assert_ne!(
        hash_rm_base, observation_hash(&obs_rm_refill),
        "H3 fail: market refill card mutation must change player-view observation"
    );

    // -----------------------------------------------------------------------
    // Fixture 3: BuyMarket
    // -----------------------------------------------------------------------
    // Give player 0 enough gold/tokens to afford buying market tier 0 slot 0
    let mut state_buyable = state.clone();
    state_buyable.players[0].tokens.gold = 10;
    let act_buy_market = Action::BuyMarket {
        tier: Tier::One,
        slot: 0,
    };

    let mut s_bm = state_buyable.clone();
    s_bm.apply(act_buy_market).unwrap();
    let obs_bm_base = s_bm.observation(PlayerId(0));
    let hash_bm_base = observation_hash(&obs_bm_base);

    // Deeper deck mutation: swap bottom cards of deck 0 -> market refill is from top, deeper is invisible
    let mut s_bm_deeper = state_buyable.clone();
    s_bm_deeper.decks[0].swap(0, 1);
    s_bm_deeper.apply(act_buy_market).unwrap();
    let obs_bm_deeper = s_bm_deeper.observation(PlayerId(0));
    assert_eq!(
        hash_bm_base, observation_hash(&obs_bm_deeper),
        "H3 fail: deeper deck mutation leaked in BuyMarket"
    );

    // Refill card mutation: swap top card of deck 0 -> changes market refill card visible to player
    let mut s_bm_refill = state_buyable.clone();
    s_bm_refill.decks[0].swap(dlen - 1, 0);
    s_bm_refill.apply(act_buy_market).unwrap();
    let obs_bm_refill = s_bm_refill.observation(PlayerId(0));
    assert_ne!(
        hash_bm_base, observation_hash(&obs_bm_refill),
        "H3 fail: BuyMarket refill card mutation must change player-view observation"
    );

    // -----------------------------------------------------------------------
    // Fixture 4: Opponent blind reserve
    // -----------------------------------------------------------------------
    // State where Player 1 (opponent) has a blind reserve card
    let mut s_opp = state.clone();
    s_opp.apply(Action::TakeTokens {
        take: Gems::from_colors([1, 1, 1, 0, 0]),
        give_back: Gems::ZERO,
    }).unwrap(); // P0 takes tokens
    s_opp.apply(Action::ReserveDeck {
        tier: Tier::One,
        give_back: Gems::ZERO,
    }).unwrap(); // P1 blind reserves

    let obs_p0_base = s_opp.observation(PlayerId(0));
    let hash_p0_base = observation_hash(&obs_p0_base);

    // Mutate the card ID stored inside P1's blind reserve
    let mut s_opp_mutated = s_opp.clone();
    assert_eq!(s_opp_mutated.players[1].reserved.len(), 1);
    s_opp_mutated.players[1].reserved[0].card = splendor_catalog::CardId(88);
    let obs_p0_mutated = s_opp_mutated.observation(PlayerId(0));
    let hash_p0_mutated = observation_hash(&obs_p0_mutated);

    // Mutating opponent's hidden blind reserve must NOT leak to root actor observation
    assert_eq!(
        hash_p0_base, hash_p0_mutated,
        "H3 fail: opponent blind reserve leaked to root actor observation"
    );
}
