//! M07 C5 frozen replay-bound player-view benchmark.
//!
//! The committed benchmark is read-only: it has no update, rewrite, or
//! environment-controlled calibration path.

use std::collections::BTreeSet;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::atomic::{AtomicU64, Ordering};

use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use splendor_core::{
    full_state_hash, observation_hash, visible_events, Action, Audience, FullState, GameConfig,
    Gems, PlayerId, Ruleset, Tier, VisibleEvent, CATALOG_VERSION, ENGINE_VERSION,
};
use splendor_imperfect_search::{
    analyze_player_view_v1, RootDeterminizationConfigV1, RootDeterminizationResultV1,
    DETERMINIZATION_VERSION, IMPERFECT_SEARCH_ALGORITHM_ID, IMPERFECT_SEARCH_VERSION,
    INFORMATION_SET_VERSION,
};
use splendor_replay::{
    replay_document_hash_v1, verify_replay, verify_replay_position, ReplayRecorder, ReplayV1,
};
use splendor_search::{canonical_order, SearchConfigV1, SEARCH_ALGORITHM_ID, SEARCH_VERSION};

const FROZEN_CORPUS_HASH: &str = "ac37627eb4c89ce1408a1bd1f33e1aff9e353b0f96fde92166f431db87b2470d";
const CORPUS_FORMAT: &str = "effective-splendor-determinization-benchmark";
const CORPUS_VERSION: u32 = 1;
const BENCHMARK_ID: &str = "m07-determinization-v1";
const CORPUS_HASH_DOMAIN: &[u8] = b"effective-splendor-determinization-benchmark-v1\0";
const SAMPLE_SEED: u64 = 20_260_703;
const SAMPLE_COUNT: u16 = 4;
const MAX_DEPTH_TURNS: u8 = 1;
const MAX_NODES: u64 = 2_000;

static TMP_SEQ: AtomicU64 = AtomicU64::new(0);

#[derive(Debug, Clone)]
struct FrozenCase {
    case_id: &'static str,
    player_count: u8,
    game_seed: u64,
    continuation_seed: u64,
    prefix_id: &'static str,
    ply: u32,
    prefix: Vec<Action>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct BenchmarkCorpusV1 {
    format: String,
    version: u32,
    benchmark_id: String,
    positions: Vec<BenchmarkPositionV1>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct BenchmarkPositionV1 {
    case_id: String,
    player_count: u8,
    game_seed: u64,
    continuation_seed: u64,
    prefix_id: String,
    ply: u32,
    sample_seed: u64,
    sample_count: u16,
    max_depth_turns: u8,
    max_nodes: u64,
    expected: BenchmarkExpectedV1,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct BenchmarkExpectedV1 {
    replay_document_hash: String,
    analysis_sha256: String,
    analyzed_state_hash: String,
    observation_hash: String,
    visible_event_count: u32,
    visible_history_hash: String,
    information_set_hash: String,
    recorded_actor: PlayerId,
    recorded_action: Action,
    recommended_matches_recorded: bool,
    result: RootDeterminizationResultV1,
}

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn corpus_path() -> PathBuf {
    repo_root().join("benchmarks/m07-determinization-v1.corpus.json")
}

fn bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_splendor"))
}

fn tmp_dir(label: &str) -> PathBuf {
    let seq = TMP_SEQ.fetch_add(1, Ordering::SeqCst);
    let dir = std::env::temp_dir().join(format!(
        "splendor-m07-benchmark-{}-{label}-{seq}",
        std::process::id()
    ));
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

fn lower_hex(bytes: &[u8]) -> String {
    use std::fmt::Write as _;

    bytes.iter().fold(String::new(), |mut output, byte| {
        let _ = write!(output, "{byte:02x}");
        output
    })
}

fn sha256_hex(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    lower_hex(&hasher.finalize())
}

fn corpus_hash(corpus: &BenchmarkCorpusV1) -> String {
    let compact = serde_json::to_string(corpus).unwrap();
    let mut hasher = Sha256::new();
    hasher.update(CORPUS_HASH_DOMAIN);
    hasher.update(compact.as_bytes());
    lower_hex(&hasher.finalize())
}

fn config() -> RootDeterminizationConfigV1 {
    RootDeterminizationConfigV1 {
        sample_seed: SAMPLE_SEED,
        sample_count: SAMPLE_COUNT,
        continuation_search: SearchConfigV1 {
            max_depth_turns: MAX_DEPTH_TURNS,
            max_nodes: MAX_NODES,
        },
    }
}

fn frozen_cases() -> Vec<FrozenCase> {
    let zero = Gems::ZERO;
    vec![
        FrozenCase {
            case_id: "m07-2p-p0",
            player_count: 2,
            game_seed: 7002,
            continuation_seed: 17002,
            prefix_id: "2p-reserve-mix-v1",
            ply: 0,
            prefix: vec![
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 0,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::One,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::Two,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 1,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::Two,
                    slot: 0,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::Two,
                    give_back: zero,
                },
            ],
        },
        FrozenCase {
            case_id: "m07-2p-p2",
            player_count: 2,
            game_seed: 7002,
            continuation_seed: 17002,
            prefix_id: "2p-reserve-mix-v1",
            ply: 2,
            prefix: vec![
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 0,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::One,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::Two,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 1,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::Two,
                    slot: 0,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::Two,
                    give_back: zero,
                },
            ],
        },
        FrozenCase {
            case_id: "m07-2p-p4",
            player_count: 2,
            game_seed: 7002,
            continuation_seed: 17002,
            prefix_id: "2p-reserve-mix-v1",
            ply: 4,
            prefix: vec![
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 0,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::One,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::Two,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 1,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::Two,
                    slot: 0,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::Two,
                    give_back: zero,
                },
            ],
        },
        FrozenCase {
            case_id: "m07-2p-p6",
            player_count: 2,
            game_seed: 7002,
            continuation_seed: 17002,
            prefix_id: "2p-reserve-mix-v1",
            ply: 6,
            prefix: vec![
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 0,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::One,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::Two,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 1,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::Two,
                    slot: 0,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::Two,
                    give_back: zero,
                },
            ],
        },
        FrozenCase {
            case_id: "m07-3p-p0",
            player_count: 3,
            game_seed: 7003,
            continuation_seed: 17003,
            prefix_id: "3p-reserve-mix-v1",
            ply: 0,
            prefix: vec![
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 0,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::Two,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::One,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::Two,
                    slot: 0,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 1,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 2,
                    give_back: zero,
                },
            ],
        },
        FrozenCase {
            case_id: "m07-3p-p3",
            player_count: 3,
            game_seed: 7003,
            continuation_seed: 17003,
            prefix_id: "3p-reserve-mix-v1",
            ply: 3,
            prefix: vec![
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 0,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::Two,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::One,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::Two,
                    slot: 0,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 1,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 2,
                    give_back: zero,
                },
            ],
        },
        FrozenCase {
            case_id: "m07-3p-p5",
            player_count: 3,
            game_seed: 7003,
            continuation_seed: 17003,
            prefix_id: "3p-reserve-mix-v1",
            ply: 5,
            prefix: vec![
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 0,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::Two,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::One,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::Two,
                    slot: 0,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 1,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 2,
                    give_back: zero,
                },
            ],
        },
        FrozenCase {
            case_id: "m07-3p-p6",
            player_count: 3,
            game_seed: 7003,
            continuation_seed: 17003,
            prefix_id: "3p-reserve-mix-v1",
            ply: 6,
            prefix: vec![
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 0,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::Two,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::One,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::Two,
                    slot: 0,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 1,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 2,
                    give_back: zero,
                },
            ],
        },
        FrozenCase {
            case_id: "m07-4p-p0",
            player_count: 4,
            game_seed: 7004,
            continuation_seed: 17004,
            prefix_id: "4p-reserve-mix-v1",
            ply: 0,
            prefix: vec![
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 0,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::One,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::Two,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::One,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::Two,
                    slot: 0,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 1,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 2,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 3,
                    give_back: zero,
                },
            ],
        },
        FrozenCase {
            case_id: "m07-4p-p4",
            player_count: 4,
            game_seed: 7004,
            continuation_seed: 17004,
            prefix_id: "4p-reserve-mix-v1",
            ply: 4,
            prefix: vec![
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 0,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::One,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::Two,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::One,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::Two,
                    slot: 0,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 1,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 2,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 3,
                    give_back: zero,
                },
            ],
        },
        FrozenCase {
            case_id: "m07-4p-p6",
            player_count: 4,
            game_seed: 7004,
            continuation_seed: 17004,
            prefix_id: "4p-reserve-mix-v1",
            ply: 6,
            prefix: vec![
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 0,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::One,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::Two,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::One,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::Two,
                    slot: 0,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 1,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 2,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 3,
                    give_back: zero,
                },
            ],
        },
        FrozenCase {
            case_id: "m07-4p-p8",
            player_count: 4,
            game_seed: 7004,
            continuation_seed: 17004,
            prefix_id: "4p-reserve-mix-v1",
            ply: 8,
            prefix: vec![
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 0,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::One,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::Two,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::One,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::Two,
                    slot: 0,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 1,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 2,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 3,
                    give_back: zero,
                },
            ],
        },
    ]
}

fn next_xorshift64_star(state: &mut u64) -> u64 {
    let mut x = *state;
    x ^= x >> 12;
    x ^= x << 25;
    x ^= x >> 27;
    *state = x;
    x.wrapping_mul(0x2545_F491_4F6C_DD1D)
}

fn record_frozen_replay(case: &FrozenCase) -> ReplayV1 {
    let mut recorder = ReplayRecorder::new(GameConfig {
        player_count: case.player_count,
        seed: case.game_seed,
        ruleset: Ruleset::base_v1(),
    })
    .unwrap_or_else(|error| panic!("{}: setup failed: {error}", case.case_id));

    for action in &case.prefix {
        recorder
            .apply(*action)
            .unwrap_or_else(|error| panic!("{}: prefix action failed: {error}", case.case_id));
    }

    let mut state = case.continuation_seed;
    let mut plies = case.prefix.len() as u32;
    while !recorder.is_terminal() {
        assert!(
            plies < 10_000,
            "{}: continuation exceeded guard",
            case.case_id
        );
        let actions = canonical_order(&recorder.legal_actions());
        assert!(
            !actions.is_empty(),
            "{}: no legal continuation",
            case.case_id
        );
        let action = actions[(next_xorshift64_star(&mut state) % actions.len() as u64) as usize];
        recorder
            .apply(action)
            .unwrap_or_else(|error| panic!("{}: continuation failed: {error}", case.case_id));
        plies += 1;
    }

    let (_, replay) = recorder
        .finish()
        .unwrap_or_else(|error| panic!("{}: finish failed: {error}", case.case_id));
    replay
}

fn write_replay(path: &Path, replay: &ReplayV1) {
    let mut json = serde_json::to_string_pretty(replay).unwrap();
    json.push('\n');
    std::fs::write(path, json).unwrap();
}

fn rebuild_visible_prefix(
    replay: &ReplayV1,
    ply: u32,
    viewer: PlayerId,
) -> (FullState, Vec<VisibleEvent>) {
    let (mut state, setup) = FullState::new(GameConfig {
        player_count: replay.player_count,
        seed: replay.seed,
        ruleset: Ruleset::base_v1(),
    })
    .unwrap();
    assert_eq!(
        full_state_hash(&state).as_str(),
        replay.initial_state_hash.as_str()
    );

    let audience = Audience::Player(viewer);
    let mut history = visible_events(&setup.events, audience);
    for step in replay.steps.iter().take(ply as usize) {
        assert_eq!(state.current_player, step.actor);
        assert_eq!(
            full_state_hash(&state).as_str(),
            step.state_hash_before.as_str()
        );
        let result = state.apply(step.action).unwrap();
        state.assert_invariants().unwrap();
        assert_eq!(
            full_state_hash(&state).as_str(),
            step.state_hash_after.as_str()
        );
        history.extend(visible_events(&result.events, audience));
    }
    (state, history)
}

fn run_player_view(replay_path: &Path, out_path: &Path, ply: u32) -> Vec<u8> {
    let output = Command::new(bin())
        .arg("analyze-replay-player-view")
        .arg("--input")
        .arg(replay_path)
        .args(["--ply", &ply.to_string()])
        .args(["--sample-seed", &SAMPLE_SEED.to_string()])
        .args(["--sample-count", &SAMPLE_COUNT.to_string()])
        .args(["--max-depth-turns", &MAX_DEPTH_TURNS.to_string()])
        .args(["--max-nodes", &MAX_NODES.to_string()])
        .arg("--out")
        .arg(out_path)
        .output()
        .expect("spawn analyze-replay-player-view");
    assert_eq!(
        output.status.code(),
        Some(0),
        "benchmark CLI failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(output.stdout.is_empty());
    assert!(output.stderr.is_empty());
    std::fs::read(out_path).unwrap()
}

fn expected_snapshot(replay: &ReplayV1, ply: u32, raw_artifact: &[u8]) -> BenchmarkExpectedV1 {
    let position = verify_replay_position(replay, ply).unwrap();
    let viewer = position.recorded_actor;
    let (state, history) = rebuild_visible_prefix(replay, ply, viewer);
    assert_eq!(state.current_player, viewer);
    assert_eq!(
        full_state_hash(&state).as_str(),
        position.state_hash.as_str()
    );
    let observation = state.observation(viewer);
    let composed =
        analyze_player_view_v1(Ruleset::base_v1(), &observation, &history, config()).unwrap();
    let result = composed.result();
    let step = &replay.steps[ply as usize];
    assert!(state.legal_actions().contains(&result.action));
    assert!(result
        .action_aggregates
        .iter()
        .any(|aggregate| aggregate.action == result.action));

    BenchmarkExpectedV1 {
        replay_document_hash: replay_document_hash_v1(replay).unwrap(),
        analysis_sha256: sha256_hex(raw_artifact),
        analyzed_state_hash: position.state_hash,
        observation_hash: observation_hash(&observation).as_str().to_string(),
        visible_event_count: history.len() as u32,
        visible_history_hash: composed.visible_history_hash().as_str().to_string(),
        information_set_hash: composed.information_set_hash().as_str().to_string(),
        recorded_actor: viewer,
        recorded_action: step.action,
        recommended_matches_recorded: result.action == step.action,
        result: result.clone(),
    }
}

fn assert_no_forbidden_exact_keys(value: &Value) {
    const FORBIDDEN: &[&str] = &[
        "seed",
        "state",
        "deck",
        "blind",
        "principal_variation",
        "visible_history",
        "sample_index",
        "sample_state_hash",
        "sample_utility",
    ];
    match value {
        Value::Object(object) => {
            for (key, child) in object {
                assert!(
                    !FORBIDDEN.contains(&key.as_str()),
                    "forbidden artifact key {key}"
                );
                assert_no_forbidden_exact_keys(child);
            }
        }
        Value::Array(array) => {
            for child in array {
                assert_no_forbidden_exact_keys(child);
            }
        }
        Value::Null | Value::Bool(_) | Value::Number(_) | Value::String(_) => {}
    }
}

fn read_corpus() -> BenchmarkCorpusV1 {
    let raw = std::fs::read_to_string(corpus_path()).unwrap();
    serde_json::from_str(&raw).expect("M07 corpus must strictly deserialize")
}

fn assert_lower_hex64(value: &str, label: &str) {
    assert_eq!(value.len(), 64, "{label} must be 64 characters");
    assert!(
        value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte)),
        "{label} must be lowercase hexadecimal"
    );
}

fn assert_frozen_position(position: &BenchmarkPositionV1, case: &FrozenCase) {
    assert_eq!(position.case_id, case.case_id);
    assert_eq!(position.player_count, case.player_count);
    assert_eq!(position.game_seed, case.game_seed);
    assert_eq!(position.continuation_seed, case.continuation_seed);
    assert_eq!(position.prefix_id, case.prefix_id);
    assert_eq!(position.ply, case.ply);
    assert_eq!(position.sample_seed, SAMPLE_SEED);
    assert_eq!(position.sample_count, SAMPLE_COUNT);
    assert_eq!(position.max_depth_turns, MAX_DEPTH_TURNS);
    assert_eq!(position.max_nodes, MAX_NODES);

    let expected = &position.expected;
    assert_lower_hex64(&expected.replay_document_hash, "replay_document_hash");
    assert_lower_hex64(&expected.analysis_sha256, "analysis_sha256");
    assert_lower_hex64(&expected.analyzed_state_hash, "analyzed_state_hash");
    assert_lower_hex64(&expected.observation_hash, "observation_hash");
    assert_lower_hex64(&expected.visible_history_hash, "visible_history_hash");
    assert_lower_hex64(&expected.information_set_hash, "information_set_hash");
}

#[test]
fn frozen_m07_corpus_identity() {
    let corpus = read_corpus();
    assert_eq!(corpus.format, CORPUS_FORMAT);
    assert_eq!(corpus.version, CORPUS_VERSION);
    assert_eq!(corpus.benchmark_id, BENCHMARK_ID);
    assert_eq!(corpus.positions.len(), 12);

    let cases = frozen_cases();
    assert_eq!(cases.len(), 12);
    let mut ids = BTreeSet::new();
    let mut player_counts = BTreeSet::new();
    for (position, case) in corpus.positions.iter().zip(cases.iter()) {
        assert_frozen_position(position, case);
        assert!(
            ids.insert(position.case_id.clone()),
            "case ID is not unique"
        );
        player_counts.insert(position.player_count);
    }
    assert_eq!(player_counts, BTreeSet::from([2, 3, 4]));
    assert_eq!(
        corpus_hash(&corpus),
        FROZEN_CORPUS_HASH,
        "parsed corpus identity drifted"
    );
}

fn assert_artifact_bindings(
    artifact: &Value,
    replay: &ReplayV1,
    expected: &BenchmarkExpectedV1,
    position: &splendor_replay::VerifiedReplayPosition,
) {
    assert_eq!(
        artifact["format"],
        "effective-splendor-imperfect-search-analysis"
    );
    assert_eq!(artifact["version"], 1);
    assert_eq!(artifact["engine_version"], ENGINE_VERSION);
    assert_eq!(artifact["catalog_version"], CATALOG_VERSION);
    assert_eq!(artifact["information_set_version"], INFORMATION_SET_VERSION);
    assert_eq!(artifact["determinization_version"], DETERMINIZATION_VERSION);
    assert_eq!(
        artifact["imperfect_search_algorithm_id"],
        IMPERFECT_SEARCH_ALGORITHM_ID
    );
    assert_eq!(
        artifact["imperfect_search_version"],
        IMPERFECT_SEARCH_VERSION
    );
    assert_eq!(
        artifact["continuation_search_algorithm_id"],
        SEARCH_ALGORITHM_ID
    );
    assert_eq!(artifact["continuation_search_version"], SEARCH_VERSION);
    assert_eq!(
        artifact["config"],
        serde_json::json!({
            "sample_seed": SAMPLE_SEED,
            "sample_count": SAMPLE_COUNT,
            "continuation_search": {
                "max_depth_turns": MAX_DEPTH_TURNS,
                "max_nodes": MAX_NODES,
            },
        })
    );

    let source = &artifact["source"];
    assert_eq!(
        source["replay_document_hash"],
        expected.replay_document_hash
    );
    assert_eq!(
        source["replay_final_state_hash"],
        replay.final_state_hash.as_str()
    );
    assert_eq!(source["replay_version"], replay.version);
    assert_eq!(
        source["ruleset_fingerprint"],
        replay.ruleset_fingerprint.as_str()
    );
    assert_eq!(source["analyzed_ply"], position.ply);
    assert_eq!(source["analyzed_state_hash"], expected.analyzed_state_hash);
    assert_eq!(source["viewer"], expected.recorded_actor.0);
    assert_eq!(source["observation_hash"], expected.observation_hash);
    assert_eq!(source["visible_event_count"], expected.visible_event_count);
    assert_eq!(
        source["visible_history_hash"],
        expected.visible_history_hash
    );
    assert_eq!(
        source["information_set_hash"],
        expected.information_set_hash
    );
    assert_eq!(source["recorded_actor"], expected.recorded_actor.0);
    assert_eq!(
        source["recorded_action"],
        serde_json::to_value(expected.recorded_action).unwrap()
    );
    assert_eq!(
        artifact["result"],
        serde_json::to_value(&expected.result).unwrap()
    );
    assert_eq!(
        artifact["recommended_matches_recorded"],
        expected.recommended_matches_recorded
    );
}

fn no_temp_residue(dir: &Path) -> bool {
    std::fs::read_dir(dir)
        .unwrap()
        .map(|entry| entry.unwrap().file_name().to_string_lossy().into_owned())
        .all(|name| !name.ends_with(".tmp"))
}

#[test]
#[ignore = "M07 frozen 12-position reproducibility benchmark; run explicitly"]
fn m07_determinization_benchmark_is_reproducible() {
    let corpus = read_corpus();
    let cases = frozen_cases();
    let mut first_run: Option<Vec<(String, Vec<u8>)>> = None;
    let mut zero_ply_action_histories = 0usize;
    let mut hidden_opponent_cases = 0usize;
    let mut viewer_owned_blind_cases = 0usize;
    let mut multiple_hidden_cases = 0usize;
    let mut viewers = BTreeSet::new();
    let mut player_counts = BTreeSet::new();

    for run in 0..2 {
        let root = tmp_dir(&format!("run-{run}"));
        let mut snapshots = Vec::new();
        for (position, case) in corpus.positions.iter().zip(cases.iter()) {
            assert_frozen_position(position, case);
            let replay = record_frozen_replay(case);
            verify_replay(&replay).unwrap_or_else(|error| {
                panic!(
                    "{}: frozen replay verification failed: {error}",
                    case.case_id
                )
            });
            let document_hash = replay_document_hash_v1(&replay).unwrap();
            assert_eq!(document_hash, position.expected.replay_document_hash);
            assert!((position.ply as usize) < replay.steps.len());

            let case_dir = root.join(case.case_id);
            std::fs::create_dir_all(&case_dir).unwrap();
            let replay_path = case_dir.join("replay.json");
            write_replay(&replay_path, &replay);
            let artifact_path = case_dir.join("analysis.json");
            let raw_artifact = run_player_view(&replay_path, &artifact_path, position.ply);
            assert_eq!(
                sha256_hex(&raw_artifact),
                position.expected.analysis_sha256,
                "{}: artifact bytes drifted",
                case.case_id
            );

            let artifact: Value = serde_json::from_slice(&raw_artifact).unwrap();
            assert_no_forbidden_exact_keys(&artifact);
            let verified_position = verify_replay_position(&replay, position.ply).unwrap();
            let derived = expected_snapshot(&replay, position.ply, &raw_artifact);
            assert_eq!(
                derived, position.expected,
                "{}: direct result drifted",
                case.case_id
            );
            assert_artifact_bindings(&artifact, &replay, &position.expected, &verified_position);

            let (state, history) =
                rebuild_visible_prefix(&replay, position.ply, position.expected.recorded_actor);
            assert_eq!(state.current_player, position.expected.recorded_actor);
            assert!(state
                .legal_actions()
                .contains(&position.expected.result.action));
            assert!(position
                .expected
                .result
                .action_aggregates
                .iter()
                .any(|aggregate| aggregate.action == position.expected.result.action));
            assert!(no_temp_residue(&case_dir));

            if run == 0 {
                let action_events = history
                    .iter()
                    .filter(|event| matches!(event, VisibleEvent::ActionApplied { .. }))
                    .count();
                if position.ply == 0 {
                    assert_eq!(action_events, 0, "ply-zero history has prior actions");
                    zero_ply_action_histories += 1;
                }
                let hidden_opponent = history
                    .iter()
                    .filter(|event| {
                        matches!(
                            event,
                            VisibleEvent::CardReserved {
                                card: None,
                                public_identity: false,
                                ..
                            }
                        )
                    })
                    .count();
                let viewer_owned_blind = history
                    .iter()
                    .filter(|event| {
                        matches!(
                            event,
                            VisibleEvent::CardReserved {
                                card: Some(_),
                                public_identity: false,
                                ..
                            }
                        )
                    })
                    .count();
                if hidden_opponent > 0 {
                    hidden_opponent_cases += 1;
                }
                if viewer_owned_blind > 0 {
                    viewer_owned_blind_cases += 1;
                }
                if hidden_opponent >= 2 {
                    multiple_hidden_cases += 1;
                }
                viewers.insert(position.expected.recorded_actor.0);
                player_counts.insert(position.player_count);
            }

            snapshots.push((document_hash, raw_artifact));
        }

        if let Some(previous) = &first_run {
            assert_eq!(snapshots, *previous, "two benchmark runs diverged");
        } else {
            first_run = Some(snapshots);
        }
        let _ = std::fs::remove_dir_all(root);
    }

    assert_eq!(zero_ply_action_histories, 3);
    assert!(hidden_opponent_cases >= 6);
    assert!(viewer_owned_blind_cases >= 3);
    assert!(multiple_hidden_cases >= 2);
    assert!(viewers.contains(&0));
    assert!(viewers.iter().any(|viewer| *viewer != 0));
    assert_eq!(player_counts, BTreeSet::from([2, 3, 4]));
}
