//! M32A: InformationSetV1 to 212-dim Sidecar Exporter.
//! Reconstructs player-visible history from matches 0..255, validates InformationSetHashV1 against dataset examples,
//! and writes a strict, deterministic sidecar artifact without leaking hidden cards or hashes into features.

use std::collections::HashMap;
use std::fs::File;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use splendor_belief::{build_information_set_v1, InformationSetV1, ReservedKnowledgeV1};
use splendor_catalog::{card, Tier, CARD_COUNT};
use splendor_core::{visible_events, Audience, FullState, GameConfig, PlayerId, Ruleset};
use splendor_replay::{verify_replay_position, ReplayV1};

pub const BELIEF_FEATURES: usize = 212; // 90 (unseen mask) + 120 (reserved knowledge) + 2 (purchased count)

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct SidecarEntry {
    pub example_index: usize,
    pub source_id: String,
    pub match_index: usize,
    pub ply: u32,
    pub actor: usize,
    pub information_set_hash: String,
    pub belief_features: Vec<f32>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct SidecarArtifact {
    pub milestone: String,
    pub dataset_file: String,
    pub dataset_file_sha256: String,
    pub total_examples: usize,
    pub feature_dim: usize,
    pub entries: Vec<SidecarEntry>,
}

/// Project an InformationSetV1 into exact 212-dim belief features
pub fn project_information_set_to_features(
    info_set: &InformationSetV1,
    viewer: PlayerId,
) -> Vec<f32> {
    let mut features = Vec::with_capacity(BELIEF_FEATURES);

    // Part A: unseen_card_mask (90 dims, CardId 0..89)
    // 1.0 if card is in unseen_cards_by_tier, else 0.0
    let mut unseen_mask = vec![0.0f32; CARD_COUNT];
    for tier in Tier::ALL {
        for card_id in info_set.unseen_cards(tier) {
            unseen_mask[card_id.0 as usize] = 1.0;
        }
    }
    features.extend(unseen_mask);

    // Part B: reserved_knowledge (2 players * 3 slots * 20 dims = 120 dims)
    // Order: viewer slots first (relative index 0), then opponent slots (relative index 1)
    let player_count = info_set.observation().public.player_count as usize;
    assert_eq!(player_count, 2, "M32A is strictly 1v1 (2 players)");

    let reserved_by_player = info_set.reserved_knowledge();

    for rel_player in 0..2 {
        let actual_player_id = (viewer.index() + rel_player) % 2;
        let player_res = reserved_by_player
            .iter()
            .find(|p| p.player.index() == actual_player_id)
            .expect("player reserved knowledge not found");

        for slot_idx in 0..3 {
            let mut slot_features = vec![0.0f32; 20];
            if slot_idx < player_res.slots.len() {
                match player_res.slots[slot_idx] {
                    ReservedKnowledgeV1::Known {
                        card: card_id,
                        from_deck,
                    } => {
                        if from_deck {
                            // known_private_from_deck
                            slot_features[2] = 1.0;
                        } else {
                            // known_public
                            slot_features[1] = 1.0;
                        }
                        // Known card attributes (14 dims)
                        let def = card(card_id);
                        slot_features[6 + def.tier.index()] = 1.0; // tier one-hot (3)
                        slot_features[9 + def.bonus.index()] = 1.0; // bonus one-hot (5)
                        slot_features[14] = def.prestige as f32 / 5.0; // prestige (1)
                        for c_idx in 0..5 {
                            slot_features[15 + c_idx] = def.cost[c_idx] as f32 / 7.0;
                            // cost (5)
                        }
                    }
                    ReservedKnowledgeV1::HiddenDeck { tier } => {
                        // status: hidden_tier_1 (3), hidden_tier_2 (4), hidden_tier_3 (5)
                        slot_features[3 + tier.index()] = 1.0;
                        // Card attributes remain strictly ZERO for HiddenDeck
                    }
                }
            } else {
                // empty slot
                slot_features[0] = 1.0;
            }
            features.extend(slot_features);
        }
    }

    // Part C: purchased_count (viewer / opponent, 2 dims)
    let viewer_purchased = info_set.observation().public.players[viewer.index()]
        .purchased
        .len() as f32
        / 20.0;
    let opp_purchased = info_set.observation().public.players[1 - viewer.index()]
        .purchased
        .len() as f32
        / 20.0;
    features.push(viewer_purchased);
    features.push(opp_purchased);

    assert_eq!(
        features.len(),
        BELIEF_FEATURES,
        "projected features must match BELIEF_FEATURES exactly"
    );
    features
}

fn read_replay(path: &Path) -> ReplayV1 {
    let mut file = File::open(path).expect("cannot open replay");
    let mut text = String::new();
    file.read_to_string(&mut text).expect("read replay text");
    serde_json::from_str(&text).expect("parse replay JSON")
}

fn reconstruct_visible_history(
    replay: &ReplayV1,
    ply: u32,
    viewer: PlayerId,
) -> (FullState, Vec<splendor_core::VisibleEvent>) {
    let ruleset = Ruleset::base_v1();
    let (mut state, setup) = FullState::new(GameConfig {
        player_count: replay.player_count,
        seed: replay.seed,
        ruleset,
    })
    .expect("setup state");

    let audience = Audience::Player(viewer);
    let mut visible_history = visible_events(&setup.events, audience);
    for step in replay.steps.iter().take(ply as usize) {
        let step_result = state.apply(step.action).expect("apply step action");
        visible_history.extend(visible_events(&step_result.events, audience));
    }
    (state, visible_history)
}

fn main() {
    println!("M32A: Exporting 212-dim Belief Sidecar Features...");

    let ds_path = PathBuf::from("local-artifacts/m25-generation/m25-materialized-dataset.json");
    let ds_bytes = std::fs::read(&ds_path).expect("read dataset bytes");
    let ds_hash = {
        let mut hasher = Sha256::new();
        hasher.update(&ds_bytes);
        hex::encode(hasher.finalize())
    };
    println!("Dataset file SHA-256: {}", ds_hash);

    let ds_json: serde_json::Value = serde_json::from_slice(&ds_bytes).expect("parse dataset json");
    let examples = ds_json["examples"].as_array().expect("examples array");
    let total_examples = examples.len();
    assert_eq!(
        total_examples, 16282,
        "expected exactly 16,282 dataset examples"
    );

    // Group examples by match_index for replay caching: (example_index, &example_json)
    let mut by_match: HashMap<usize, Vec<(usize, &serde_json::Value)>> = HashMap::new();
    for (ex_idx, ex) in examples.iter().enumerate() {
        let match_idx = ex["evaluation_match_index"].as_u64().expect("match index") as usize;
        by_match.entry(match_idx).or_default().push((ex_idx, ex));
    }

    let mut sidecar_entries: Vec<Option<SidecarEntry>> = vec![None; total_examples];

    for match_idx in 0..256 {
        let match_examples = by_match.get(&match_idx).expect("missing match examples");
        let replay_path = format!(
            "local-artifacts/m25-generation/eval-run/matches/match-{:06}.replay.json",
            match_idx
        );
        let replay = read_replay(Path::new(&replay_path));

        for &(ex_idx, ex) in match_examples {
            let source_id = ex["source_id"].as_str().unwrap().to_string();
            let ply = ex["ply"].as_u64().unwrap() as u32;
            let actor = ex["actor"].as_u64().unwrap() as usize;
            let viewer = PlayerId(actor as u8);
            let expected_info_hash = ex["information_set_hash"].as_str().unwrap();

            let _pos = verify_replay_position(&replay, ply).expect("verify replay position");
            let (state, visible_history) = reconstruct_visible_history(&replay, ply, viewer);
            let observation = state.observation(viewer);

            let info_set =
                build_information_set_v1(Ruleset::base_v1(), &observation, &visible_history)
                    .expect("build information set");
            let actual_info_hash = info_set.information_set_hash().as_str().to_string();

            // Strict assertion: reconstructed information_set_hash must match dataset example exactly
            assert_eq!(
                actual_info_hash, expected_info_hash,
                "InformationSetHash mismatch for example index {} (match {}, ply {}, actor {})",
                ex_idx, match_idx, ply, actor
            );

            let belief_features = project_information_set_to_features(&info_set, viewer);

            sidecar_entries[ex_idx] = Some(SidecarEntry {
                example_index: ex_idx,
                source_id,
                match_index: match_idx,
                ply,
                actor,
                information_set_hash: actual_info_hash,
                belief_features,
            });
        }
    }

    let unwrapped_entries: Vec<SidecarEntry> = sidecar_entries
        .into_iter()
        .map(|e| e.expect("unpopulated entry"))
        .collect();
    assert_eq!(unwrapped_entries.len(), total_examples);

    let artifact = SidecarArtifact {
        milestone: "M32A".to_string(),
        dataset_file: "local-artifacts/m25-generation/m25-materialized-dataset.json".to_string(),
        dataset_file_sha256: ds_hash,
        total_examples,
        feature_dim: BELIEF_FEATURES,
        entries: unwrapped_entries,
    };

    let out_dir = PathBuf::from("local-artifacts/m32a-belief-sidecar");
    std::fs::create_dir_all(&out_dir).expect("create sidecar dir");
    let out_path = out_dir.join("m32a-belief-sidecar.json");

    let out_bytes = serde_json::to_vec_pretty(&artifact).expect("serialize artifact");
    let sidecar_sha256 = {
        let mut hasher = Sha256::new();
        hasher.update(&out_bytes);
        hex::encode(hasher.finalize())
    };

    let mut file = File::create(&out_path).expect("create sidecar file");
    file.write_all(&out_bytes).expect("write sidecar file");
    println!(
        "Successfully exported 16,282 sidecar entries to {}",
        out_path.display()
    );
    println!("Sidecar file SHA-256: {}", sidecar_sha256);
}
