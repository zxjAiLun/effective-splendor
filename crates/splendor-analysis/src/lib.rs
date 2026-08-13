//! M14A replay-bound analysis traces and Replay Studio projections.
//!
//! `ReplayV1` remains the objective referee audit record. This crate verifies
//! it once, projects each decision to the recorded actor, runs a separately
//! identified analyzer, and emits an immutable sidecar. Referee reveal data is
//! explicitly segregated from the default player-view observation.

mod determinization_trace;
mod error;
mod evaluation_diagnostic;
mod neural_trace;
mod review_trace;
mod reviewer_registry;
mod schema;

pub use determinization_trace::{
    analyze_replay_determinization_v2, analyze_replay_determinization_v2_with_progress,
};
pub use error::AnalysisError;
pub use evaluation_diagnostic::{
    analyze_evaluation_neural_v1, evaluation_diagnostic_hash_v1, AgentDecisionMetricsV1,
    AnalyzedEvaluationMatchV1, CandidateOutcomeSummaryV1, EvaluationDiagnosticOutputV1,
    NeuralEvaluationDiagnosticV1, SeatOutcomeSummaryV1, SeedBlockSummaryV1,
    ANALYSIS_EVALUATION_FORMAT, ANALYSIS_EVALUATION_VERSION,
};
pub use neural_trace::{
    analyze_replay_neural_v1, analyze_replay_neural_v2, analyze_replay_neural_v2_with_progress,
};
pub use review_trace::{
    analysis_trace_hash_v2, review_cache_key_v2, AnalysisFrameV2, AnalysisTraceV2,
    NeuralIsmctsReviewResultV2, ReviewResultV2, ReviewerConfigV2, ReviewerIdentityV2,
    ReviewerProvenanceV2, ReviewerResultKindV2, ReviewerStatusV2, RootDeterminizationActionStatsV2,
    RootDeterminizationReviewResultV2, M07_REVIEWER_ALGORITHM_VERSION, M07_REVIEWER_DISPLAY_NAME,
    M07_REVIEWER_ID, M07_REVIEWER_SEED_DERIVATION, M13_REVIEWER_ALGORITHM_VERSION,
    M13_REVIEWER_DISPLAY_NAME, M13_REVIEWER_ID, M13_REVIEWER_SEED_DERIVATION, REVIEW_TRACE_VERSION,
};
pub use reviewer_registry::{
    ReviewerEntryV1, ReviewerRegistryV1, REVIEWER_REGISTRY_FORMAT, REVIEWER_REGISTRY_VERSION,
};
pub use schema::{
    analysis_trace_hash_v1, AnalysisCardV1, AnalysisCatalogV1, AnalysisFrameV1, AnalysisNobleV1,
    AnalysisTraceV1, RefereeRevealV1, ANALYSIS_TRACE_FORMAT, ANALYSIS_TRACE_VERSION,
};
