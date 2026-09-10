//! M23 unified replay-wide reviewer trace (AnalysisTraceV2).
//!
//! `AnalysisTraceV1` remains the frozen M14A sidecar for M13. `AnalysisTraceV2`
//! is a separate, strictly validated contract that carries a `reviewer`
//! identity plus a discriminated `review_result` per decision ply:
//!
//! ```text
//! root_determinization   -> mean utility vectors (M07)
//! neural_ismcts          -> policy prior / visit / Q vectors (M13)
//! policy_recommendation  -> S3 proposal set + decision path (no utility/Q)
//! ```
//!
//! The result kinds are deliberately never merged: M07 utility is never
//! written into a `Q` field, M13 never fabricates a determinization utility,
//! and the S3 reviewer only reports its own proposal set and decision path
//! (never a fabricated utility or rank). A reviewer only ever receives the
//! recorded actor's `Observation` plus its visible history; the referee reveal
//! data carried here is for post-game display only and is never an analyzer
//! input.

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use splendor_core::{Action, Observation, PlayerId};
use splendor_determinization_agent::s3_agent::S3_ROOT_SEED;
use splendor_determinization_agent::s3_rollout::{
    s3_m07_config, s3_n1_config, S3_D, S3_P, S3_ROLLOUT_SAMPLE_SEED,
};
use splendor_imperfect_search::{
    RootDeterminizationConfigV1, RootDeterminizationStatsV1, IMPERFECT_SEARCH_ALGORITHM_ID,
};
use splendor_neural_search::{
    NeuralIsmctsConfigV1, NeuralIsmctsResultV1, NEURAL_ISMCTS_ALGORITHM_ID,
};
use splendor_replay::ReplayGameResultV1;

use crate::schema::{
    invalid, validate_action, validate_catalog, validate_hash, validate_projection,
};
use crate::{
    AnalysisCardV1, AnalysisCatalogV1, AnalysisError, AnalysisNobleV1, RefereeRevealV1,
    ANALYSIS_TRACE_FORMAT,
};

pub const REVIEW_TRACE_VERSION: u32 = 2;

pub const M07_REVIEWER_ID: &str = "m07-determinization-champion";
pub const M07_REVIEWER_DISPLAY_NAME: &str = "M07 Determinization Champion";
pub const M07_REVIEWER_ALGORITHM_VERSION: u32 = 1;
pub const M07_REVIEWER_SEED_DERIVATION: &str =
    "sha256(\"effective-splendor-root-determinization-v2\\0\" + base_seed + ply + replay_document_hash)";

pub const M13_REVIEWER_ID: &str = "m13-neural-ismcts";
pub const M13_REVIEWER_DISPLAY_NAME: &str = "M13 Neural ISMCTS";
pub const M13_REVIEWER_ALGORITHM_VERSION: u32 = 1;
pub const M13_REVIEWER_SEED_DERIVATION: &str =
    "frozen sample_seed from NeuralIsmctsConfigV1 (no referee seed reuse)";

pub const S3_REVIEWER_ID: &str = "s3-rollout-review";
pub const S3_REVIEWER_DISPLAY_NAME: &str = "S3 Rollout Review";
pub const S3_REVIEWER_ALGORITHM_VERSION: u32 = 1;
/// Algorithm identity shared with the live S3 rollout candidate
/// (`splendor_determinization_agent::s3_agent::S3_AGENT_NAME`).
pub const S3_REVIEWER_ALGORITHM_ID: &str = "effective-splendor-s3-rollout-v1";
pub const S3_REVIEWER_SEED_DERIVATION: &str =
    "per-seat persistent StableRng(20_260_812) advanced over replay plies in order; consumed only on root heuristic ties (unique maxima consume nothing)";
/// Honest metric names: the S3 reviewer exposes its recommendation and the
/// decision path only. It never exposes mean utility, a rank, a prior, a
/// visit count, a Q value or any rollout outcome score.
pub const S3_REVIEWER_METRICS: [&str; 2] = ["recommended_action", "decision_path"];

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ReviewerStatusV2 {
    Champion,
    Experimental,
    Rejected,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ReviewerResultKindV2 {
    RootDeterminization,
    NeuralIsmcts,
    PolicyRecommendation,
}

/// Frozen S3 review configuration identity.
///
/// The S3 decision engine keeps D/P/seeds as frozen code constants and the
/// exact n1/M07 proposal configs in the agent crate's canonical
/// constructors; this config mirrors ALL of them so the trace is
/// self-describing and so [`review_cache_key_v2`] flips when any part of the
/// production S3 identity drifts (including a changed n1/M07 search budget).
/// `validate()` only accepts the exact frozen v1 values.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct S3ReviewConfigV2 {
    pub version: u32,
    /// Frozen rollout policy identity label.
    pub rollout_policy: String,
    /// D: shared hidden-world samples per decision.
    pub determinizations: u16,
    /// P: simulated action applications after the root candidate action.
    pub ply_cap: u16,
    /// Frozen evaluation (world sampling) stream seed.
    pub sample_seed: u64,
    /// Persistent per-seat root heuristic RNG seed.
    pub root_seed: u64,
    /// The exact n1 proposal config used in production (`s3_n1_config()`).
    pub n1_config: RootDeterminizationConfigV1,
    /// The exact M07 proposal config used in production (`s3_m07_config()`).
    pub m07_config: RootDeterminizationConfigV1,
}

pub const S3_REVIEW_CONFIG_VERSION: u32 = 1;
pub const S3_REVIEW_ROLLOUT_POLICY: &str = "s3-rollout-d4-p120-v1";

impl S3ReviewConfigV2 {
    /// The one frozen v1 identity (derived from the agent's canonical
    /// production constants and config constructors — never re-typed by
    /// hand).
    pub fn frozen_v1() -> Self {
        Self {
            version: S3_REVIEW_CONFIG_VERSION,
            rollout_policy: S3_REVIEW_ROLLOUT_POLICY.to_owned(),
            determinizations: u16::try_from(S3_D).expect("S3_D fits u16"),
            ply_cap: u16::try_from(S3_P).expect("S3_P fits u16"),
            sample_seed: S3_ROLLOUT_SAMPLE_SEED,
            root_seed: S3_ROOT_SEED,
            n1_config: s3_n1_config(),
            m07_config: s3_m07_config(),
        }
    }

    pub fn validate(&self) -> Result<(), String> {
        if self != &Self::frozen_v1() {
            return Err(
                "S3 review config is not the frozen v1 rollout identity (D/P/seeds or the exact n1/M07 configs drifted)"
                    .into(),
            );
        }
        Ok(())
    }
}

/// Reviewer-specific frozen configuration, discriminated by result kind.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ReviewerConfigV2 {
    RootDeterminization(RootDeterminizationConfigV1),
    NeuralIsmcts(NeuralIsmctsConfigV1),
    PolicyRecommendation(S3ReviewConfigV2),
}

/// S3 decision path, mirrored from the agent crate's `S3Path` so the analysis
/// JSON schema stays independent of the agent crate's internal serialization.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum S3ReviewPathV2 {
    /// No rollout comparison ran (non-Main phase, <2 legal actions, or a
    /// root heuristic tie): the recommendation is the base heuristic action.
    HeuristicFastPath,
    /// All proposals agreed: the unique action was returned without rollouts.
    ProposalsAgreed,
    /// Some rollout was ply-capped: the decision kept the base heuristic action.
    PlyCapFallback,
    /// Complete comparison: integer terminal-score argmax with the full tie rule.
    RolloutComparison,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReviewerProvenanceV2 {
    /// Frozen, human-readable description of how per-ply sampling seeds are
    /// derived. Never reuses the referee replay seed directly.
    pub seed_derivation: String,
    /// Native, honest metric names this reviewer exposes. These are rendered as
    /// labels only; the UI must never relabel them as win probabilities.
    pub metrics: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReviewerIdentityV2 {
    pub id: String,
    pub display_name: String,
    pub competitive_status: ReviewerStatusV2,
    pub result_kind: ReviewerResultKindV2,
    pub algorithm_id: String,
    pub algorithm_version: u32,
    pub config: ReviewerConfigV2,
    pub checkpoint_hash: Option<String>,
    pub provenance: ReviewerProvenanceV2,
}

impl ReviewerIdentityV2 {
    /// Build a frozen reviewer identity. `algorithm_id`, `algorithm_version`
    /// and provenance (metrics + seed derivation) are derived from the result
    /// kind so every caller binds the same honest reviewer contract.
    pub fn new(
        id: impl Into<String>,
        display_name: impl Into<String>,
        competitive_status: ReviewerStatusV2,
        result_kind: ReviewerResultKindV2,
        config: ReviewerConfigV2,
        checkpoint_hash: Option<String>,
    ) -> Self {
        let (algorithm_id, algorithm_version, metrics, seed_derivation) = match result_kind {
            ReviewerResultKindV2::RootDeterminization => (
                IMPERFECT_SEARCH_ALGORITHM_ID,
                M07_REVIEWER_ALGORITHM_VERSION,
                vec!["mean_utility", "utility_gap", "action_rank"],
                M07_REVIEWER_SEED_DERIVATION,
            ),
            ReviewerResultKindV2::NeuralIsmcts => (
                NEURAL_ISMCTS_ALGORITHM_ID,
                M13_REVIEWER_ALGORITHM_VERSION,
                vec!["prior", "visit", "q"],
                M13_REVIEWER_SEED_DERIVATION,
            ),
            ReviewerResultKindV2::PolicyRecommendation => (
                S3_REVIEWER_ALGORITHM_ID,
                S3_REVIEWER_ALGORITHM_VERSION,
                S3_REVIEWER_METRICS.to_vec(),
                S3_REVIEWER_SEED_DERIVATION,
            ),
        };
        Self {
            id: id.into(),
            display_name: display_name.into(),
            competitive_status,
            result_kind,
            algorithm_id: algorithm_id.into(),
            algorithm_version,
            config,
            checkpoint_hash,
            provenance: ReviewerProvenanceV2 {
                seed_derivation: seed_derivation.into(),
                metrics: metrics.into_iter().map(str::to_owned).collect(),
            },
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RootDeterminizationActionStatsV2 {
    pub action: Action,
    /// Checked integer utility sum per player (seat order). Negative values are
    /// legal for the root player's own component in some continuations.
    pub utility_sum_by_player: Vec<i64>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RootDeterminizationReviewResultV2 {
    pub recommended_action: Action,
    pub sample_seed: u64,
    pub sample_count: u16,
    pub action_stats: Vec<RootDeterminizationActionStatsV2>,
    pub stats: RootDeterminizationStatsV1,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NeuralIsmctsReviewResultV2 {
    pub result: NeuralIsmctsResultV1,
}

/// The S3 reviewer's honest output: its recommendation, the three frozen
/// proposals that produced it, and the decision path. Deliberately minimal —
/// `recorded_action` / `recommended_matches_recorded` live on the frame and
/// are never duplicated here. No utility, rank, prior, visit, Q or rollout
/// outcome score is exposed.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PolicyRecommendationReviewResultV2 {
    pub recommended_action: Action,
    /// The base heuristic action (with its persistent root-RNG tie break).
    pub base_heuristic_action: Action,
    /// The n1 proposal; `None` exactly when the decision was a fast path that
    /// never evaluated proposals.
    pub n1_proposal: Option<Action>,
    /// The M07 proposal; `None` exactly when the decision was a fast path
    /// that never evaluated proposals.
    pub m07_proposal: Option<Action>,
    pub decision_path: S3ReviewPathV2,
    pub recommended_differs_from_base_heuristic: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ReviewResultV2 {
    RootDeterminization(RootDeterminizationReviewResultV2),
    NeuralIsmcts(NeuralIsmctsReviewResultV2),
    PolicyRecommendation(PolicyRecommendationReviewResultV2),
}

impl ReviewResultV2 {
    pub fn kind(&self) -> ReviewerResultKindV2 {
        match self {
            Self::RootDeterminization(_) => ReviewerResultKindV2::RootDeterminization,
            Self::NeuralIsmcts(_) => ReviewerResultKindV2::NeuralIsmcts,
            Self::PolicyRecommendation(_) => ReviewerResultKindV2::PolicyRecommendation,
        }
    }

    pub fn recommended_action(&self) -> Action {
        match self {
            Self::RootDeterminization(result) => result.recommended_action,
            Self::NeuralIsmcts(result) => result.result.action,
            Self::PolicyRecommendation(result) => result.recommended_action,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AnalysisFrameV2 {
    pub ply: u32,
    pub state_hash_before: String,
    pub actor: PlayerId,
    pub recorded_action: Action,
    pub observation_hash: String,
    pub visible_event_count: u32,
    pub visible_history_hash: String,
    pub information_set_hash: String,
    /// Default-safe projection: the recorded actor's Observation.
    pub player_view: Observation,
    /// Referee-only post-game data. Never an analyzer input.
    pub referee_reveal: RefereeRevealV1,
    pub legal_actions: Vec<Action>,
    pub review_result: ReviewResultV2,
    pub recommended_matches_recorded: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AnalysisTraceV2 {
    pub format: String,
    pub version: u32,
    pub engine_version: String,
    pub catalog_version: String,
    pub replay_version: u32,
    pub replay_document_hash: String,
    pub replay_final_state_hash: String,
    pub ruleset_fingerprint: String,
    pub player_count: u8,
    pub result: ReplayGameResultV1,
    pub reviewer: ReviewerIdentityV2,
    pub catalog: AnalysisCatalogV1,
    pub frames: Vec<AnalysisFrameV2>,
}

impl AnalysisTraceV2 {
    pub fn validate(&self) -> Result<(), AnalysisError> {
        if self.format != ANALYSIS_TRACE_FORMAT || self.version != REVIEW_TRACE_VERSION {
            return Err(invalid("unsupported format/version"));
        }
        if self.engine_version != splendor_core::ENGINE_VERSION
            || self.catalog_version != splendor_core::CATALOG_VERSION
            || self.replay_version != splendor_replay::REPLAY_VERSION
        {
            return Err(invalid("engine/catalog/replay version mismatch"));
        }
        if !(2..=4).contains(&self.player_count) || self.frames.is_empty() {
            return Err(invalid("player count or frame count is invalid"));
        }
        if self.result.scores.len() != self.player_count as usize
            || self.result.ranks.len() != self.player_count as usize
            || self
                .result
                .winners
                .iter()
                .any(|winner| usize::from(*winner) >= self.player_count as usize)
        {
            return Err(invalid("terminal result shape is invalid"));
        }
        for (label, hash) in [
            ("replay_document_hash", self.replay_document_hash.as_str()),
            (
                "replay_final_state_hash",
                self.replay_final_state_hash.as_str(),
            ),
            ("ruleset_fingerprint", self.ruleset_fingerprint.as_str()),
        ] {
            validate_hash(label, hash)?;
        }
        self.validate_reviewer()?;
        validate_catalog(&self.catalog)?;

        let seed = self.frames[0].referee_reveal.seed;
        if matches!(
            &self.reviewer.config,
            ReviewerConfigV2::NeuralIsmcts(config) if config.sample_seed == seed
        ) {
            return Err(invalid(
                "neural reviewer must not reuse the referee replay seed",
            ));
        }
        for (index, frame) in self.frames.iter().enumerate() {
            if frame.ply != index as u32
                || frame.actor != frame.player_view.viewer
                || frame.actor.index() >= self.player_count as usize
                || frame.player_view.public.current_player != frame.actor
                || frame.player_view.public.player_count != self.player_count
                || frame.player_view.public.players.len() != self.player_count as usize
                || frame.referee_reveal.players.len() != self.player_count as usize
                || frame.referee_reveal.seed != seed
                || frame.player_view.ruleset_fingerprint.as_str() != self.ruleset_fingerprint
                || frame.visible_event_count == 0
            {
                return Err(invalid(format!("frame {index} identity/shape mismatch")));
            }
            if splendor_core::observation_hash(&frame.player_view).as_str()
                != frame.observation_hash
            {
                return Err(invalid(format!("frame {index} observation hash mismatch")));
            }
            validate_projection(
                &frame.player_view,
                &frame.referee_reveal,
                frame.actor,
                index,
            )?;
            validate_action(frame.recorded_action, index)?;
            validate_action(frame.review_result.recommended_action(), index)?;
            for action in &frame.legal_actions {
                validate_action(*action, index)?;
            }
            for (label, hash) in [
                ("state_hash_before", frame.state_hash_before.as_str()),
                ("observation_hash", frame.observation_hash.as_str()),
                ("visible_history_hash", frame.visible_history_hash.as_str()),
                ("information_set_hash", frame.information_set_hash.as_str()),
            ] {
                validate_hash(label, hash)?;
            }
            if frame.legal_actions.is_empty()
                || !frame.legal_actions.contains(&frame.recorded_action)
                || !frame
                    .legal_actions
                    .contains(&frame.review_result.recommended_action())
                || frame.review_result.kind() != self.reviewer.result_kind
                || frame.recommended_matches_recorded
                    != (frame.review_result.recommended_action() == frame.recorded_action)
            {
                return Err(invalid(format!("frame {index} action binding mismatch")));
            }
            self.validate_review_result(frame, index)?;
        }
        Ok(())
    }

    fn validate_reviewer(&self) -> Result<(), AnalysisError> {
        let reviewer = &self.reviewer;
        if reviewer.id.trim().is_empty() || reviewer.display_name.trim().is_empty() {
            return Err(invalid("reviewer identity is empty"));
        }
        if reviewer.algorithm_id.trim().is_empty()
            || reviewer.algorithm_version == 0
            || reviewer.provenance.metrics.is_empty()
            || reviewer.provenance.seed_derivation.trim().is_empty()
        {
            return Err(invalid("reviewer provenance is incomplete"));
        }
        let (expected_algorithm, expected_version, expected_metrics, expected_seed_derivation) =
            match reviewer.result_kind {
                ReviewerResultKindV2::RootDeterminization => (
                    IMPERFECT_SEARCH_ALGORITHM_ID,
                    M07_REVIEWER_ALGORITHM_VERSION,
                    ["mean_utility", "utility_gap", "action_rank"].as_slice(),
                    M07_REVIEWER_SEED_DERIVATION,
                ),
                ReviewerResultKindV2::NeuralIsmcts => (
                    NEURAL_ISMCTS_ALGORITHM_ID,
                    M13_REVIEWER_ALGORITHM_VERSION,
                    ["prior", "visit", "q"].as_slice(),
                    M13_REVIEWER_SEED_DERIVATION,
                ),
                ReviewerResultKindV2::PolicyRecommendation => (
                    S3_REVIEWER_ALGORITHM_ID,
                    S3_REVIEWER_ALGORITHM_VERSION,
                    S3_REVIEWER_METRICS.as_slice(),
                    S3_REVIEWER_SEED_DERIVATION,
                ),
            };
        if reviewer.algorithm_id != expected_algorithm
            || reviewer.algorithm_version != expected_version
            || reviewer
                .provenance
                .metrics
                .iter()
                .map(String::as_str)
                .ne(expected_metrics.iter().copied())
            || reviewer.provenance.seed_derivation != expected_seed_derivation
        {
            return Err(invalid("reviewer algorithm/provenance binding mismatch"));
        }
        match reviewer.id.as_str() {
            M07_REVIEWER_ID
                if reviewer.competitive_status != ReviewerStatusV2::Champion
                    || reviewer.result_kind != ReviewerResultKindV2::RootDeterminization =>
            {
                return Err(invalid("M07 reviewer status/kind mismatch"));
            }
            M13_REVIEWER_ID
                if reviewer.competitive_status != ReviewerStatusV2::Rejected
                    || reviewer.result_kind != ReviewerResultKindV2::NeuralIsmcts =>
            {
                return Err(invalid("M13 reviewer status/kind mismatch"));
            }
            S3_REVIEWER_ID
                if reviewer.competitive_status != ReviewerStatusV2::Champion
                    || reviewer.result_kind != ReviewerResultKindV2::PolicyRecommendation =>
            {
                return Err(invalid("S3 reviewer status/kind mismatch"));
            }
            _ => {}
        }
        match (&reviewer.config, reviewer.checkpoint_hash.as_deref()) {
            (ReviewerConfigV2::RootDeterminization(config), None)
                if reviewer.result_kind == ReviewerResultKindV2::RootDeterminization =>
            {
                config
                    .validate()
                    .map_err(|error| invalid(format!("reviewer config: {error}")))?;
            }
            (ReviewerConfigV2::NeuralIsmcts(config), Some(checkpoint_hash))
                if reviewer.result_kind == ReviewerResultKindV2::NeuralIsmcts =>
            {
                validate_hash("checkpoint_hash", checkpoint_hash)?;
                config
                    .validate()
                    .map_err(|error| invalid(format!("reviewer config: {error}")))?;
                if config.expected_checkpoint_hash != checkpoint_hash {
                    return Err(invalid("reviewer checkpoint binding mismatch"));
                }
            }
            (ReviewerConfigV2::PolicyRecommendation(config), None)
                if reviewer.result_kind == ReviewerResultKindV2::PolicyRecommendation =>
            {
                config
                    .validate()
                    .map_err(|error| invalid(format!("reviewer config: {error}")))?;
            }
            _ => return Err(invalid("reviewer config/checkpoint/kind mismatch")),
        }
        Ok(())
    }

    fn validate_review_result(
        &self,
        frame: &AnalysisFrameV2,
        index: usize,
    ) -> Result<(), AnalysisError> {
        match &frame.review_result {
            ReviewResultV2::RootDeterminization(result) => {
                if result.sample_count == 0
                    || result.action_stats.len() != frame.legal_actions.len()
                    || result
                        .action_stats
                        .iter()
                        .map(|stats| stats.action)
                        .ne(frame.legal_actions.iter().copied())
                    || !frame.legal_actions.contains(&result.recommended_action)
                    || result.stats.samples != result.sample_count
                {
                    return Err(invalid(format!(
                        "frame {index} root-determinization binding mismatch"
                    )));
                }
                if let ReviewerConfigV2::RootDeterminization(config) = &self.reviewer.config {
                    let expected_seed = derive_determinization_ply_seed(
                        config.sample_seed,
                        frame.ply,
                        &self.replay_document_hash,
                    );
                    if result.sample_seed != expected_seed
                        || result.sample_count != config.sample_count
                    {
                        return Err(invalid(format!(
                            "frame {index} determinization config/seed mismatch"
                        )));
                    }
                }
                for stats in &result.action_stats {
                    if stats.utility_sum_by_player.len() != self.player_count as usize {
                        return Err(invalid(format!(
                            "frame {index} utility vector shape mismatch"
                        )));
                    }
                }
            }
            ReviewResultV2::NeuralIsmcts(result) => {
                let neural = &result.result;
                if neural.information_set_hash != frame.information_set_hash
                    || neural.checkpoint_hash.as_str()
                        != self.reviewer.checkpoint_hash.as_deref().unwrap_or("")
                    || neural.action_stats.len() != frame.legal_actions.len()
                    || neural
                        .action_stats
                        .iter()
                        .map(|stats| stats.action)
                        .ne(frame.legal_actions.iter().copied())
                    || !frame.legal_actions.contains(&neural.action)
                {
                    return Err(invalid(format!(
                        "frame {index} neural review binding mismatch"
                    )));
                }
                if let ReviewerConfigV2::NeuralIsmcts(config) = &self.reviewer.config {
                    if neural.stats.simulations != config.simulations
                        || neural.stats.sampled_determinizations != config.simulations
                        || neural.stats.root_visits != config.simulations
                    {
                        return Err(invalid(format!(
                            "frame {index} neural simulation binding mismatch"
                        )));
                    }
                }
                let visit_sum = neural
                    .action_stats
                    .iter()
                    .try_fold(0u32, |sum, stats| sum.checked_add(stats.visits))
                    .ok_or(AnalysisError::ArithmeticOverflow)?;
                if visit_sum != neural.stats.root_visits {
                    return Err(invalid(format!("frame {index} visit sum mismatch")));
                }
                let scale = splendor_neural_search::NEURAL_VALUE_SCALE_V1;
                for stats in &neural.action_stats {
                    if stats.prior_micros > scale
                        || stats.value_sum_by_player.len() != self.player_count as usize
                        || stats
                            .value_sum_by_player
                            .iter()
                            .any(|sum| *sum > u64::from(stats.visits) * u64::from(scale))
                    {
                        return Err(invalid(format!("frame {index} neural edge stats invalid")));
                    }
                }
            }
            ReviewResultV2::PolicyRecommendation(result) => {
                if !frame.legal_actions.contains(&result.recommended_action)
                    || !frame.legal_actions.contains(&result.base_heuristic_action)
                    || result.recommended_differs_from_base_heuristic
                        != (result.recommended_action != result.base_heuristic_action)
                {
                    return Err(invalid(format!(
                        "frame {index} policy recommendation binding mismatch"
                    )));
                }
                match result.decision_path {
                    S3ReviewPathV2::HeuristicFastPath => {
                        // The fast path never evaluates proposals: reporting
                        // one (even a backfilled a_H) is fabrication.
                        if result.n1_proposal.is_some()
                            || result.m07_proposal.is_some()
                            || result.recommended_differs_from_base_heuristic
                        {
                            return Err(invalid(format!(
                                "frame {index} fast-path policy recommendation mismatch"
                            )));
                        }
                    }
                    S3ReviewPathV2::ProposalsAgreed
                    | S3ReviewPathV2::PlyCapFallback
                    | S3ReviewPathV2::RolloutComparison => {
                        // Comparison paths always evaluated both proposals.
                        for proposal in [result.n1_proposal, result.m07_proposal] {
                            let Some(proposal) = proposal else {
                                return Err(invalid(format!(
                                    "frame {index} comparison path is missing an evaluated proposal"
                                )));
                            };
                            if !frame.legal_actions.contains(&proposal) {
                                return Err(invalid(format!(
                                    "frame {index} policy recommendation binding mismatch"
                                )));
                            }
                        }
                    }
                }
            }
        }
        Ok(())
    }
}

/// Deterministic cache identity for one replay + reviewer + full config.
///
/// Binds replay document hash, reviewer id, reviewer algorithm version, the
/// complete canonical reviewer config, and the checkpoint hash (when present).
/// This is what the Studio Host uses to reuse an existing artifact.
pub fn review_cache_key_v2(
    replay_document_hash: &str,
    reviewer: &ReviewerIdentityV2,
) -> Result<String, AnalysisError> {
    let config_json = serde_json::to_vec(&reviewer.config)
        .map_err(|error| AnalysisError::Serialization(error.to_string()))?;
    let mut hasher = Sha256::new();
    hasher.update(b"effective-splendor-review-cache-v2\0");
    hasher.update(replay_document_hash.as_bytes());
    hasher.update(reviewer.id.as_bytes());
    hasher.update(reviewer.algorithm_version.to_le_bytes());
    hasher.update(&config_json);
    if let Some(checkpoint_hash) = &reviewer.checkpoint_hash {
        hasher.update(checkpoint_hash.as_bytes());
    }
    Ok(hex::encode(hasher.finalize()))
}

pub fn analysis_trace_hash_v2(trace: &AnalysisTraceV2) -> Result<String, AnalysisError> {
    trace.validate()?;
    let json = serde_json::to_vec(trace)
        .map_err(|error| AnalysisError::Serialization(error.to_string()))?;
    let mut hasher = Sha256::new();
    hasher.update(b"effective-splendor-analysis-trace-v2\0");
    hasher.update(json);
    Ok(hex::encode(hasher.finalize()))
}

/// Derive the deterministic per-ply sampling seed for root determinization.
///
/// The referee replay seed is never used. The seed is a pure function of the
/// frozen base seed, the decision ply, and the verified replay document hash,
/// so every re-run of the same replay + reviewer + config reproduces the same
/// sample stream without hinting at the true hidden state.
pub(crate) fn derive_determinization_ply_seed(
    base_seed: u64,
    ply: u32,
    replay_document_hash: &str,
) -> u64 {
    let mut hasher = Sha256::new();
    hasher.update(b"effective-splendor-root-determinization-v2\0");
    hasher.update(base_seed.to_le_bytes());
    hasher.update(ply.to_le_bytes());
    hasher.update(replay_document_hash.as_bytes());
    let digest = hasher.finalize();
    let mut bytes = [0u8; 8];
    bytes.copy_from_slice(&digest[..8]);
    u64::from_le_bytes(bytes)
}

/// The frozen dense catalog shared by every trace.
pub(crate) fn build_catalog_v1() -> AnalysisCatalogV1 {
    AnalysisCatalogV1 {
        cards: splendor_catalog::all_cards()
            .iter()
            .map(|card| AnalysisCardV1 {
                id: card.id,
                tier: card.tier,
                bonus: card.bonus,
                prestige: card.prestige,
                cost: card.cost,
            })
            .collect(),
        nobles: splendor_catalog::all_nobles()
            .iter()
            .map(|noble| AnalysisNobleV1 {
                id: noble.id,
                prestige: noble.prestige,
                requirements: noble.requirements,
            })
            .collect(),
    }
}
