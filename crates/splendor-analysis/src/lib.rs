//! M14A replay-bound analysis traces and Replay Studio projections.
//!
//! `ReplayV1` remains the objective referee audit record. This crate verifies
//! it once, projects each decision to the recorded actor, runs a separately
//! identified analyzer, and emits an immutable sidecar. Referee reveal data is
//! explicitly segregated from the default player-view observation.

mod error;
mod evaluation_diagnostic;
mod neural_trace;
mod schema;

pub use error::AnalysisError;
pub use evaluation_diagnostic::{
    analyze_evaluation_neural_v1, evaluation_diagnostic_hash_v1, AgentDecisionMetricsV1,
    AnalyzedEvaluationMatchV1, CandidateOutcomeSummaryV1, EvaluationDiagnosticOutputV1,
    NeuralEvaluationDiagnosticV1, SeatOutcomeSummaryV1, SeedBlockSummaryV1,
    ANALYSIS_EVALUATION_FORMAT, ANALYSIS_EVALUATION_VERSION,
};
pub use neural_trace::analyze_replay_neural_v1;
pub use schema::{
    analysis_trace_hash_v1, AnalysisCardV1, AnalysisCatalogV1, AnalysisFrameV1, AnalysisNobleV1,
    AnalysisTraceV1, RefereeRevealV1, ANALYSIS_TRACE_FORMAT, ANALYSIS_TRACE_VERSION,
};
