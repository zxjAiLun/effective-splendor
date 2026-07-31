//! M06 fixed benchmark: replay-bound perfect-information search corpus.
//!
//! This test runs the checked-in, frozen corpus
//! (`benchmarks/m06-search-v1.corpus.json`) end to end through the real
//! `splendor analyze-replay` subprocess and enforces the M06 determinism and
//! offline strength gates. It is `#[ignore]`d so the default workspace test
//! passes stay fast; the release gate runs it explicitly:
//!
//! ```text
//! cargo test --locked -p splendor-cli --test search_benchmark -- --ignored --test-threads=1
//! ```
//!
//! Discipline (frozen at C5 authorization, before the first calibration run):
//! - the 12 `(players, game_seed, action_seed, ply, depth, nodes)` tuples, the
//!   heuristic identity/seed and the strength gate are frozen; a case that
//!   fails must be *reported*, never swapped for a friendlier position;
//! - the corpus manifest is a test-only schema; it is not part of any
//!   production crate's API;
//! - the heuristic comparison lives here, in an ignored post-game benchmark,
//!   precisely because `splendor-search` reads the referee `FullState` while
//!   `HeuristicAgentPolicy` may only read its `Observation`, the
//!   server-certified legal actions and its own `StableRng`. The search is not
//!   and must not be presented as a live Agent SDK policy.

use std::path::{Path, PathBuf};
use std::process::Command;

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use splendor_agent::{
    AgentPolicy, DecisionContext, HeuristicAgentPolicy, PublicRequestMeta, StableRng,
    HEURISTIC_AGENT_NAME, HEURISTIC_AGENT_VERSION,
};
use splendor_core::{
    observation_hash, Action, FullState, GameEvent, CATALOG_VERSION, ENGINE_VERSION,
};
use splendor_replay::{
    record_random_game, replay_document_hash_v1, verify_replay, verify_replay_position,
};
use splendor_search::{
    canonical_order, SearchAnalysisV1, SearchError, SearchStatsV1, SearchStopReasonV1,
    StaticEvaluatorV1, SEARCH_ALGORITHM_ID, SEARCH_ANALYSIS_FORMAT, SEARCH_ANALYSIS_VERSION,
    SEARCH_VERSION,
};

/// Domain-separated identity of the checked-in corpus. Any change to a tuple,
/// a search config, the heuristic block or a single expected value breaks this
/// constant on purpose.
const FROZEN_CORPUS_HASH: &str = "857fabcdca7d4eb7be49cadc4858deaa328c2b6fb96abb844058a803befe21c9";

/// Domain separation prefix for [`FROZEN_CORPUS_HASH`].
const CORPUS_HASH_DOMAIN: &[u8] = b"effective-splendor-search-benchmark-v1\0";

const CORPUS_FORMAT: &str = "effective-splendor-search-benchmark";
const CORPUS_VERSION: u32 = 1;
const BENCHMARK_ID: &str = "m06-search-v1";

/// The heuristic baseline's frozen RNG seed. Re-created per case; RNG state is
/// never carried across cases.
const HEURISTIC_RNG_SEED: u64 = 101;

/// Frozen strength gate: the search may never be worse than the heuristic at
/// the same exact depth, and must be strictly better in at least this many
/// cases. A zero strict-improvement count is a benchmark failure, never a
/// reason to re-pick the corpus.
const MIN_STRICT_HEURISTIC_IMPROVEMENTS: usize = 1;

/// The frozen corpus tuples: `(case_id, players, game_seed, action_seed, ply,
/// max_depth_turns, max_nodes)`. Asserted against the manifest so a seed, ply,
/// player count or config can never be silently swapped.
const FROZEN_CASES: [(&str, u8, u64, u64, u32, u8, u64); 12] = [
    ("2p-s42-a1001-p0", 2, 42, 1001, 0, 2, 500_000),
    ("2p-s42-a1001-p10", 2, 42, 1001, 10, 2, 500_000),
    ("2p-s7-a7001-p5", 2, 7, 7001, 5, 2, 500_000),
    ("2p-s7-a7001-p15", 2, 7, 7001, 15, 2, 500_000),
    ("3p-s12-a1201-p0", 3, 12, 1201, 0, 2, 500_000),
    ("3p-s12-a1201-p10", 3, 12, 1201, 10, 2, 500_000),
    ("3p-s21-a2101-p5", 3, 21, 2101, 5, 2, 500_000),
    ("3p-s21-a2101-p15", 3, 21, 2101, 15, 2, 500_000),
    ("4p-s99-a9901-p0", 4, 99, 9901, 0, 1, 500_000),
    ("4p-s99-a9901-p10", 4, 99, 9901, 10, 1, 500_000),
    ("4p-s123-a12301-p5", 4, 123, 12301, 5, 1, 500_000),
    ("4p-s123-a12301-p15", 4, 123, 12301, 15, 1, 500_000),
];

// ---------------------------------------------------------------------------
// Test-only corpus schema
// ---------------------------------------------------------------------------

/// The checked-in benchmark manifest. Test-only: deliberately not exported by
/// any production crate.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct BenchmarkCorpusV1 {
    format: String,
    version: u32,
    benchmark_id: String,
    heuristic: BenchmarkHeuristicV1,
    positions: Vec<BenchmarkPositionV1>,
}

/// The frozen heuristic baseline identity.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct BenchmarkHeuristicV1 {
    name: String,
    version: String,
    rng_seed: u64,
}

/// One frozen replay position and its expected analysis.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct BenchmarkPositionV1 {
    case_id: String,
    player_count: u8,
    game_seed: u64,
    action_seed: u64,
    ply: u32,
    max_depth_turns: u8,
    max_nodes: u64,
    expected: BenchmarkExpectedV1,
}

/// The deterministic expected outcome of one case.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct BenchmarkExpectedV1 {
    /// `replay_document_hash_v1` of the rebuilt replay.
    replay_document_hash: String,
    /// SHA-256 of the published artifact's raw bytes, trailing LF included.
    analysis_sha256: String,
    action: Action,
    utility_by_player: Vec<i64>,
    principal_variation: Vec<Action>,
    completed_depth_turns: u8,
    stop_reason: SearchStopReasonV1,
    stats: SearchStatsV1,
}

// ---------------------------------------------------------------------------
// Paths and small helpers
// ---------------------------------------------------------------------------

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn corpus_path() -> PathBuf {
    repo_root().join("benchmarks/m06-search-v1.corpus.json")
}

fn bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_splendor"))
}

fn lower_hex(bytes: &[u8]) -> String {
    use std::fmt::Write as _;
    bytes.iter().fold(String::new(), |mut acc, b| {
        let _ = write!(acc, "{b:02x}");
        acc
    })
}

fn sha256_hex(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    lower_hex(&hasher.finalize())
}

/// Domain-separated identity hash of the parsed corpus DTO. The manifest holds
/// no `corpus_hash` field of its own, so the value can never be self-referential.
fn corpus_hash(corpus: &BenchmarkCorpusV1) -> String {
    let compact = serde_json::to_string(corpus).expect("corpus must serialize");
    let mut hasher = Sha256::new();
    hasher.update(CORPUS_HASH_DOMAIN);
    hasher.update(compact.as_bytes());
    lower_hex(&hasher.finalize())
}

fn no_temp_residue(dir: &Path) -> bool {
    std::fs::read_dir(dir)
        .expect("case dir is readable")
        .map(|e| {
            e.expect("dir entry")
                .file_name()
                .to_string_lossy()
                .into_owned()
        })
        .all(|n| !n.ends_with(".tmp"))
}

// ---------------------------------------------------------------------------
// Heuristic baseline
// ---------------------------------------------------------------------------

/// Ask the real `HeuristicAgentPolicy` for its root action through a genuine
/// `DecisionContext`. The context carries only what the Agent SDK boundary
/// permits: the mover's own `Observation`, the server-certified legal actions,
/// public request metadata, and a fresh `StableRng`. The heuristic's scoring
/// weights are never duplicated here.
fn heuristic_root_action(state: &FullState, case_id: &str, ply: u32) -> Action {
    let mut rng = StableRng::new(HEURISTIC_RNG_SEED);
    let legal = state.legal_actions();
    let observation = state.observation(state.current_player);
    let meta = PublicRequestMeta {
        game_id: case_id.to_string(),
        recipient_seat: state.current_player,
        request_id: u64::from(ply),
        observation_hash: observation_hash(&observation),
    };
    let mut policy = HeuristicAgentPolicy::new();
    policy
        .choose_action(DecisionContext {
            observation,
            legal_actions: &legal,
            meta,
            rng: &mut rng,
        })
        .expect("the heuristic policy is infallible")
}

/// Exact same-depth utility of *forcing* `action` at the root: apply it, then
/// solve the resulting subtree with the independent no-TT reference solver.
fn forced_root_utility(state: &FullState, action: Action, depth_turns: u8) -> Vec<i64> {
    let mut child = state.clone();
    let step = child
        .apply(action)
        .expect("the forced root action must be applicable");
    let advanced = step
        .events
        .iter()
        .any(|ev| matches!(ev, GameEvent::TurnAdvanced { .. }));
    let remaining = if advanced {
        depth_turns.saturating_sub(1)
    } else {
        depth_turns
    };
    let (utility, _) = reference_maxn(&child, remaining).expect("reference solve must succeed");
    utility
}

/// Independent reference MaxN solver, test-only.
///
/// No transposition table, no iterative deepening, no node budget, no pruning
/// and no randomness. It exists so the strength comparison never routes through
/// the production searcher it is meant to measure:
/// 1. terminal or `remaining_depth_turns == 0` → `StaticEvaluatorV1::utilities`;
/// 2. enumerate the complete canonical-order legal action set;
/// 3. clone + apply each action;
/// 4. a turn advances (depth - 1) only on a `TurnAdvanced` event;
/// 5. the moving player maximizes its own utility component;
/// 6. ties keep the earlier canonical action.
fn reference_maxn(
    state: &FullState,
    remaining_depth_turns: u8,
) -> Result<(Vec<i64>, Vec<Action>), SearchError> {
    if state.is_terminal() || remaining_depth_turns == 0 {
        return Ok((StaticEvaluatorV1::utilities(state)?, Vec::new()));
    }
    let ordered = canonical_order(&state.legal_actions());
    let current = state.current_player.index();
    let mut best: Option<(i64, Action, Vec<i64>, Vec<Action>)> = None;
    for action in ordered {
        let mut child = state.clone();
        let step = child
            .apply(action)
            .map_err(|e| SearchError::Engine(e.to_string()))?;
        let advanced = step
            .events
            .iter()
            .any(|ev| matches!(ev, GameEvent::TurnAdvanced { .. }));
        let child_remaining = if advanced {
            remaining_depth_turns.saturating_sub(1)
        } else {
            remaining_depth_turns
        };
        let (utility, pv) = reference_maxn(&child, child_remaining)?;
        let score = *utility
            .get(current)
            .ok_or(SearchError::InvalidUtilityShape {
                expected: state.player_count() as usize,
                found: utility.len(),
            })?;
        if best.as_ref().map(|(b, _, _, _)| score > *b).unwrap_or(true) {
            best = Some((score, action, utility, pv));
        }
    }
    let (_, action, utility, pv) = best.ok_or(SearchError::NoLegalActions)?;
    let mut full_pv = Vec::with_capacity(pv.len() + 1);
    full_pv.push(action);
    full_pv.extend(pv);
    Ok((utility, full_pv))
}

/// Replay a published principal variation from `state`, asserting every entry
/// is legal, applies, and never skips a required `ChooseNoble` continuation.
fn assert_pv_is_playable(state: &FullState, pv: &[Action], case_id: &str) {
    let mut cursor = state.clone();
    for (i, &action) in pv.iter().enumerate() {
        // In `ChooseNoble` only `ChooseNoble` actions are legal, so a skipped
        // continuation is caught by the legality assertion below.
        let phase = cursor.phase;
        let legal = cursor.legal_actions();
        assert!(
            legal.contains(&action),
            "{case_id}: principal_variation[{i}] = {action:?} is illegal in the state reached \
             after the previous prefix (phase = {phase:?})"
        );
        cursor
            .apply(action)
            .unwrap_or_else(|e| panic!("{case_id}: principal_variation[{i}] failed to apply: {e}"));
    }
}

// ---------------------------------------------------------------------------
// The benchmark
// ---------------------------------------------------------------------------

#[test]
#[ignore = "M06 fixed replay-position search benchmark; run explicitly"]
fn m06_fixed_search_benchmark() {
    // 1. Read and strictly parse the checked-in corpus.
    let path = corpus_path();
    let text =
        std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("read {}: {e}", path.display()));
    let corpus: BenchmarkCorpusV1 =
        serde_json::from_str(&text).expect("benchmark corpus must strictly parse");

    // 2. Frozen manifest identity.
    assert_eq!(corpus.format, CORPUS_FORMAT);
    assert_eq!(corpus.version, CORPUS_VERSION);
    assert_eq!(corpus.benchmark_id, BENCHMARK_ID);
    assert_eq!(corpus.heuristic.name, HEURISTIC_AGENT_NAME);
    assert_eq!(corpus.heuristic.version, HEURISTIC_AGENT_VERSION);
    assert_eq!(corpus.heuristic.rng_seed, HEURISTIC_RNG_SEED);
    assert_eq!(
        corpus_hash(&corpus),
        FROZEN_CORPUS_HASH,
        "the checked-in corpus must hash to the frozen value"
    );

    // 3. The corpus tuples are frozen: no seed, ply, player count or config
    // may be swapped, in any order.
    assert_eq!(corpus.positions.len(), FROZEN_CASES.len());
    for (pos, frozen) in corpus.positions.iter().zip(FROZEN_CASES.iter()) {
        let actual = (
            pos.case_id.as_str(),
            pos.player_count,
            pos.game_seed,
            pos.action_seed,
            pos.ply,
            pos.max_depth_turns,
            pos.max_nodes,
        );
        assert_eq!(actual, *frozen, "corpus tuple must match the frozen table");
    }

    let root = std::env::temp_dir().join(format!("splendor-m06-benchmark-{}", std::process::id()));
    if root.exists() {
        std::fs::remove_dir_all(&root).expect("clear benchmark scratch dir");
    }

    let mut strict_improvements = 0usize;

    for pos in &corpus.positions {
        let case = pos.case_id.as_str();
        let dir = root.join(case);
        std::fs::create_dir_all(&dir).expect("create case dir");

        // 4. Rebuild the frozen replay and verify it strictly.
        let (_final_state, replay) =
            record_random_game(pos.player_count, pos.game_seed, pos.action_seed)
                .unwrap_or_else(|e| panic!("{case}: recording the frozen game failed: {e}"));
        verify_replay(&replay).unwrap_or_else(|e| panic!("{case}: replay must verify: {e}"));
        assert!(
            (pos.ply as usize) < replay.steps.len(),
            "{case}: frozen ply {} is out of range for a {}-step replay — report the failure, \
             do not re-pick the position",
            pos.ply,
            replay.steps.len()
        );

        // 5. Document hash matches the frozen expectation.
        let document_hash = replay_document_hash_v1(&replay)
            .unwrap_or_else(|e| panic!("{case}: document hash failed: {e}"));
        assert_eq!(
            document_hash, pos.expected.replay_document_hash,
            "{case}: replay document hash drifted"
        );

        // 6. Write the replay and drive the real CLI.
        let replay_path = dir.join("replay.json");
        let mut serialized =
            serde_json::to_string_pretty(&replay).expect("replay must serialize for the CLI");
        serialized.push('\n');
        std::fs::write(&replay_path, serialized).expect("write replay");
        let out_path = dir.join("analysis.json");

        let output = Command::new(bin())
            .arg("analyze-replay")
            .arg("--input")
            .arg(&replay_path)
            .args(["--ply", &pos.ply.to_string()])
            .args(["--max-depth-turns", &pos.max_depth_turns.to_string()])
            .args(["--max-nodes", &pos.max_nodes.to_string()])
            .arg("--out")
            .arg(&out_path)
            .output()
            .expect("spawn analyze-replay");
        assert_eq!(
            output.status.code(),
            Some(0),
            "{case}: analyze-replay must exit 0; stderr: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        assert!(output.stdout.is_empty(), "{case}: stdout must be empty");
        assert!(output.stderr.is_empty(), "{case}: stderr must be empty");

        // 7. Strictly parse the published artifact and hash its raw bytes.
        let raw = std::fs::read(&out_path).expect("read published artifact");
        assert_eq!(
            sha256_hex(&raw),
            pos.expected.analysis_sha256,
            "{case}: published artifact bytes drifted"
        );
        let analysis: SearchAnalysisV1 = serde_json::from_slice(&raw)
            .unwrap_or_else(|e| panic!("{case}: artifact must strictly parse: {e}"));

        // 8. Identity, replay, position and config bindings.
        assert_eq!(analysis.format, SEARCH_ANALYSIS_FORMAT);
        assert_eq!(analysis.version, SEARCH_ANALYSIS_VERSION);
        assert_eq!(analysis.search_algorithm_id, SEARCH_ALGORITHM_ID);
        assert_eq!(analysis.search_version, SEARCH_VERSION);
        assert_eq!(analysis.engine_version, ENGINE_VERSION);
        assert_eq!(analysis.catalog_version, CATALOG_VERSION);

        let step = &replay.steps[pos.ply as usize];
        assert_eq!(analysis.source.replay_document_hash, document_hash);
        assert_eq!(
            analysis.source.replay_final_state_hash,
            replay.final_state_hash.as_str()
        );
        assert_eq!(analysis.source.replay_version, replay.version);
        assert_eq!(
            analysis.source.ruleset_fingerprint,
            replay.ruleset_fingerprint.as_str()
        );
        assert_eq!(analysis.source.analyzed_ply, pos.ply);
        assert_eq!(
            analysis.source.analyzed_state_hash,
            step.state_hash_before.as_str()
        );
        assert_eq!(analysis.source.recorded_actor, step.actor);
        assert_eq!(analysis.source.recorded_action, step.action);
        assert_eq!(analysis.config.max_depth_turns, pos.max_depth_turns);
        assert_eq!(analysis.config.max_nodes, pos.max_nodes);
        assert_eq!(analysis.result.root_player, step.actor);
        assert_eq!(
            analysis.recommended_matches_recorded,
            analysis.result.action == step.action
        );

        // 9. Exact expected results.
        let expected = &pos.expected;
        assert_eq!(analysis.result.action, expected.action, "{case}: action");
        assert_eq!(
            analysis.result.utility_by_player, expected.utility_by_player,
            "{case}: utility vector"
        );
        assert_eq!(
            analysis.result.principal_variation, expected.principal_variation,
            "{case}: principal variation"
        );
        assert_eq!(
            analysis.result.completed_depth_turns, expected.completed_depth_turns,
            "{case}: completed depth"
        );
        assert_eq!(
            analysis.result.stop_reason, expected.stop_reason,
            "{case}: stop reason"
        );
        assert_eq!(analysis.result.stats, expected.stats, "{case}: stats");

        // 10. Completion gate: no fallback, no unfinished final iteration.
        assert_eq!(
            analysis.result.stop_reason,
            SearchStopReasonV1::DepthLimitReached,
            "{case}: the search must complete its final iteration"
        );
        assert_eq!(
            analysis.result.completed_depth_turns, pos.max_depth_turns,
            "{case}: the requested depth must be fully completed"
        );
        let stats = &analysis.result.stats;
        assert!(
            stats.nodes_visited <= pos.max_nodes,
            "{case}: nodes_visited {} exceeds the budget {}",
            stats.nodes_visited,
            pos.max_nodes
        );
        assert_eq!(
            stats.nodes_visited,
            stats.nodes_expanded + stats.leaf_evaluations + stats.transposition_hits,
            "{case}: node classification identity"
        );

        // 11. Replay the published PV from the independently rebuilt state.
        let position = verify_replay_position(&replay, pos.ply)
            .unwrap_or_else(|e| panic!("{case}: position must re-verify: {e}"));
        assert_eq!(position.state_hash, analysis.source.analyzed_state_hash);
        let pv = &analysis.result.principal_variation;
        assert!(!pv.is_empty(), "{case}: the PV must be non-empty");
        assert_eq!(
            pv[0], analysis.result.action,
            "{case}: principal_variation[0] must be the recommended action"
        );
        assert_pv_is_playable(&position.state, pv, case);

        // 12. No temp residue survives a successful publish.
        assert!(no_temp_residue(&dir), "{case}: temp residue remains");

        // 13. Offline strength gate at the exact same depth.
        let heuristic_action = heuristic_root_action(&position.state, case, pos.ply);
        let heuristic_utility =
            forced_root_utility(&position.state, heuristic_action, pos.max_depth_turns);
        let seat = position.state.current_player.index();
        let search_score = analysis.result.utility_by_player[seat];
        let heuristic_score = heuristic_utility[seat];
        assert!(
            search_score >= heuristic_score,
            "{case}: search utility {search_score} is worse than the heuristic's forced \
             utility {heuristic_score} at depth {} — report the failure, do not re-pick \
             the corpus",
            pos.max_depth_turns
        );
        if search_score > heuristic_score {
            strict_improvements += 1;
        }
    }

    assert!(
        strict_improvements >= MIN_STRICT_HEURISTIC_IMPROVEMENTS,
        "strength gate: {strict_improvements} strict improvements < \
         {MIN_STRICT_HEURISTIC_IMPROVEMENTS}"
    );

    let _ = std::fs::remove_dir_all(&root);
}
