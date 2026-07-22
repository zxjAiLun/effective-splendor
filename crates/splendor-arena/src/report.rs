//! Arena report schema, version 1.
//!
//! This module defines the *shape* of the arena report. Commit 2 only defines
//! and tests the schema; the runner that fills it in arrives later. All report
//! DTOs use `deny_unknown_fields` so a stray field fails loudly rather than
//! being silently ignored.
//!
//! `Aborted` is pinned: it never carries `winners` or a fabricated
//! `GameResult`. A match that did not reach a legal terminal state has no
//! result to report.

use serde::{Deserialize, Serialize};
use splendor_core::{GameResult, PlayerId};

use crate::seed_commitment::SeedCommitment;

/// Top-level report format tag written into every arena report.
pub const ARENA_REPORT_FORMAT: &str = "effective-splendor-arena-report";

/// Schema version of the arena report.
pub const ARENA_REPORT_VERSION: u32 = 1;

/// Identity of one agent bound to a seat.
///
/// `agent_name` and `agent_version` are populated from the client `hello`
/// once the handshake succeeds; before that (e.g. a pre-handshake abort) they
/// are `None`. Commit 3 writes the client-declared values here directly.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AgentIdentity {
    /// The seat this agent occupied.
    pub seat: PlayerId,
    /// Agent-declared name from `hello` (e.g. "random-agent").
    pub agent_name: Option<String>,
    /// Agent-declared version from `hello`.
    pub agent_version: Option<String>,
}

/// Lifecycle phases a match passes through, in order.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ArenaPhase {
    /// Agents spawned; awaiting `hello`.
    Handshake,
    /// A `request_action` was sent and is pending.
    ActionRequest,
    /// An action was received and accepted.
    ActionReceived,
    /// A turn concluded and the next began.
    TurnComplete,
    /// The match reached a terminal game state.
    GameEnd,
}

/// Categorised agent fault. Every variant is a stable, serializable
/// `snake_case` string.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AgentFault {
    /// Agent did not complete the handshake within `handshake_timeout_ms`.
    HandshakeTimeout,
    /// Agent did not return an action within `move_timeout_ms`.
    ActionTimeout,
    /// Agent sent a message of an unexpected type for the protocol state.
    UnexpectedMessage,
    /// Agent sent a line the strict parser rejected (unknown field, trailing
    /// data, non-object, etc.).
    MalformedMessage,
    /// Agent emitted a single stdout line exceeding [`MAX_AGENT_LINE_BYTES`].
    MessageTooLarge,
    /// Agent's declared `protocol_version` disagreed with the arena.
    ProtocolVersionMismatch,
    /// Agent's declared `game_id` disagreed with the arena.
    GameIdMismatch,
    /// Agent responded with a `request_id` the arena never issued.
    WrongRequestId,
    /// Agent returned an action the rules engine rejected.
    IllegalAction,
    /// Agent closed stdout before the match ended.
    AgentEof,
    /// Agent stdout/stderr I/O broke (read error, non-UTF-8, etc.).
    AgentIo,
}

/// Outcome of an arena match.
///
/// `Completed` carries the authoritative `GameResult` (which itself holds the
/// winners). `Aborted` carries no `GameResult` and no winners: a match that did
/// not reach a legal terminal state has nothing to fabricate.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case", tag = "status", deny_unknown_fields)]
pub enum ArenaOutcomeV1 {
    /// The match reached a terminal game state.
    Completed {
        /// The authoritative terminal result (winners live here).
        result: GameResult,
        /// Number of plies played before the terminal state.
        completed_plies: u32,
        /// Final replay hash, binding the recorded transcript to the result.
        replay_final_hash: String,
    },
    /// The match was halted by a fault before a terminal state.
    Aborted {
        /// The seat responsible for the abort, if attributable.
        seat: u8,
        /// The last phase reached before abort.
        phase: ArenaPhase,
        /// The categorised fault.
        reason: AgentFault,
        /// The `request_id` in flight when the fault occurred, if any.
        request_id: Option<u64>,
        /// Number of plies played before the abort.
        completed_plies: u32,
    },
}

impl ArenaOutcomeV1 {
    /// Build a completed outcome.
    pub fn completed(result: GameResult, completed_plies: u32, replay_final_hash: String) -> Self {
        ArenaOutcomeV1::Completed {
            result,
            completed_plies,
            replay_final_hash,
        }
    }

    /// Build an aborted outcome (no result, no winners).
    pub fn aborted(
        seat: u8,
        phase: ArenaPhase,
        reason: AgentFault,
        request_id: Option<u64>,
        completed_plies: u32,
    ) -> Self {
        ArenaOutcomeV1::Aborted {
            seat,
            phase,
            reason,
            request_id,
            completed_plies,
        }
    }
}

/// The version-1 arena report. The frozen compatibility metadata lets a
/// verifier recompute the seed commitment and replay hash independently of the
/// agent transcripts.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ArenaReportV1 {
    /// Always [`ARENA_REPORT_FORMAT`].
    pub format: String,
    /// Always [`ARENA_REPORT_VERSION`].
    pub version: u32,
    /// The arena `game_id` this report belongs to.
    pub game_id: String,
    /// Engine version that produced this match.
    pub engine_version: String,
    /// Protocol version the agents spoke.
    pub protocol_version: String,
    /// Ruleset id (e.g. "base_v1").
    pub ruleset: String,
    /// Ruleset fingerprint hex (binds catalog/parameter compatibility).
    pub ruleset_fingerprint: String,
    /// Number of seats that participated.
    pub player_count: u8,
    /// Seed commitment published at `game_start`.
    pub seed_commitment: SeedCommitment,
    /// Bound agent identities, in seat order.
    pub agents: Vec<AgentIdentity>,
    /// Final outcome.
    pub outcome: ArenaOutcomeV1,
}

impl ArenaReportV1 {
    /// Construct a report envelope with the frozen format/version tags.
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        game_id: impl Into<String>,
        engine_version: impl Into<String>,
        protocol_version: impl Into<String>,
        ruleset: impl Into<String>,
        ruleset_fingerprint: impl Into<String>,
        player_count: u8,
        seed_commitment: SeedCommitment,
        agents: Vec<AgentIdentity>,
        outcome: ArenaOutcomeV1,
    ) -> Self {
        ArenaReportV1 {
            format: ARENA_REPORT_FORMAT.to_string(),
            version: ARENA_REPORT_VERSION,
            game_id: game_id.into(),
            engine_version: engine_version.into(),
            protocol_version: protocol_version.into(),
            ruleset: ruleset.into(),
            ruleset_fingerprint: ruleset_fingerprint.into(),
            player_count,
            seed_commitment,
            agents,
            outcome,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::seed_commitment::seed_commitment_v1;
    use splendor_core::{GameResult, PlayerId, RulesetFingerprint, TerminalReason};
    use std::str::FromStr;

    const CONTROL_FP: &str = "00000000000000000000000000000000000000000000000000000000000000aa";

    fn sample_result() -> GameResult {
        GameResult {
            scores: vec![15, 10],
            ranks: vec![1, 2],
            winners: vec![PlayerId(0)],
            reason: TerminalReason::PrestigeThreshold,
        }
    }

    fn sample_seed() -> SeedCommitment {
        seed_commitment_v1(
            "g1",
            2,
            42,
            &RulesetFingerprint::from_str(CONTROL_FP).unwrap(),
        )
    }

    fn sample_report() -> ArenaReportV1 {
        ArenaReportV1::new(
            "g1",
            "0.4.0",
            "0.5",
            "base_v1",
            CONTROL_FP,
            2,
            sample_seed(),
            vec![
                AgentIdentity {
                    seat: PlayerId(0),
                    agent_name: Some("random-agent".into()),
                    agent_version: Some("1.0".into()),
                },
                AgentIdentity {
                    seat: PlayerId(1),
                    agent_name: None,
                    agent_version: None,
                },
            ],
            ArenaOutcomeV1::completed(sample_result(), 30, "deadbeef".repeat(8)),
        )
    }

    #[test]
    fn report_contains_frozen_compatibility_metadata() {
        let report = sample_report();
        let json = serde_json::to_string(&report).unwrap();
        for key in [
            "\"format\"",
            "\"version\"",
            "\"game_id\"",
            "\"engine_version\"",
            "\"protocol_version\"",
            "\"ruleset\"",
            "\"ruleset_fingerprint\"",
            "\"player_count\"",
            "\"seed_commitment\"",
            "\"agents\"",
            "\"outcome\"",
        ] {
            assert!(json.contains(key), "missing key {key} in {json}");
        }
        assert!(json.contains("\"effective-splendor-arena-report\""));
        assert!(json.contains("\"version\":1"));
        let back: ArenaReportV1 = serde_json::from_str(&json).unwrap();
        assert_eq!(report, back);

        // Unknown top-level field must be rejected.
        let noisy = json.trim_end_matches('}').to_string() + ",\"extra\":1}";
        assert!(serde_json::from_str::<ArenaReportV1>(&noisy).is_err());
    }

    #[test]
    fn completed_outcome_rejects_unknown_fields() {
        let json = serde_json::to_string(&ArenaOutcomeV1::completed(
            sample_result(),
            30,
            "deadbeef".repeat(8),
        ))
        .unwrap();
        let noisy = json.trim_end_matches('}').to_string() + ",\"bogus\":1}";
        assert!(serde_json::from_str::<ArenaOutcomeV1>(&noisy).is_err());
    }

    #[test]
    fn aborted_outcome_rejects_unknown_fields() {
        let json = serde_json::to_string(&ArenaOutcomeV1::aborted(
            PlayerId(1).0,
            ArenaPhase::ActionRequest,
            AgentFault::ActionTimeout,
            Some(7),
            12,
        ))
        .unwrap();
        let noisy = json.trim_end_matches('}').to_string() + ",\"bogus\":1}";
        assert!(serde_json::from_str::<ArenaOutcomeV1>(&noisy).is_err());
    }

    #[test]
    fn aborted_contains_no_result_or_replay_hash() {
        let json = serde_json::to_string(&ArenaOutcomeV1::aborted(
            PlayerId(1).0,
            ArenaPhase::ActionRequest,
            AgentFault::ActionTimeout,
            Some(7),
            12,
        ))
        .unwrap();
        assert!(json.contains("\"status\":\"aborted\""));
        assert!(json.contains("\"reason\":\"action_timeout\""));
        assert!(json.contains("\"seat\":1"));
        assert!(json.contains("\"phase\":\"action_request\""));
        assert!(json.contains("\"request_id\":7"));
        assert!(json.contains("\"completed_plies\":12"));
        assert!(
            !json.contains("\"result\""),
            "aborted must not carry a result"
        );
        assert!(
            !json.contains("\"replay_final_hash\""),
            "aborted must not carry a replay hash"
        );
        assert!(
            !json.contains("\"winners\""),
            "aborted must not carry winners (authoritative winners live in GameResult)"
        );
    }

    #[test]
    fn fault_strings_are_snake_case() {
        let cases = [
            (AgentFault::HandshakeTimeout, "handshake_timeout"),
            (AgentFault::ActionTimeout, "action_timeout"),
            (AgentFault::UnexpectedMessage, "unexpected_message"),
            (AgentFault::MalformedMessage, "malformed_message"),
            (AgentFault::MessageTooLarge, "message_too_large"),
            (
                AgentFault::ProtocolVersionMismatch,
                "protocol_version_mismatch",
            ),
            (AgentFault::GameIdMismatch, "game_id_mismatch"),
            (AgentFault::WrongRequestId, "wrong_request_id"),
            (AgentFault::IllegalAction, "illegal_action"),
            (AgentFault::AgentEof, "agent_eof"),
            (AgentFault::AgentIo, "agent_io"),
        ];
        for (fault, want) in cases {
            let json = serde_json::to_string(&fault).unwrap();
            assert_eq!(json, format!("\"{want}\""), "fault {fault:?}");
        }
    }
}
