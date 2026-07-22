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

/// Top-level report format tag written into every arena report.
pub const ARENA_REPORT_FORMAT: &str = "effective-splendor-arena-report";

/// Schema version of the arena report.
pub const ARENA_REPORT_VERSION: u32 = 1;

/// Identity of one agent bound to a seat.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AgentIdentity {
    /// The seat this agent occupied.
    pub seat: PlayerId,
    /// Human-readable agent label (program basename or configured name).
    pub label: String,
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
/// `Completed` carries the real `GameResult`. `Aborted` carries no winners and
/// no `GameResult`: a match that did not reach a legal terminal state has no
/// result to fabricate.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case", tag = "status")]
pub enum ArenaOutcomeV1 {
    /// The match reached a terminal game state.
    Completed {
        /// Winning seats (may be multiple on a tie).
        winners: Vec<PlayerId>,
        /// The authoritative terminal result.
        result: GameResult,
    },
    /// The match was halted by a fault before a terminal state.
    Aborted {
        /// The seat responsible for the abort, if attributable.
        at_fault_seat: Option<PlayerId>,
        /// The categorised fault.
        fault: AgentFault,
        /// The last phase reached before abort.
        phase: ArenaPhase,
    },
}

impl ArenaOutcomeV1 {
    /// Build a completed outcome.
    pub fn completed(winners: Vec<PlayerId>, result: GameResult) -> Self {
        ArenaOutcomeV1::Completed { winners, result }
    }

    /// Build an aborted outcome (no winners, no fabricated result).
    pub fn aborted(at_fault_seat: Option<PlayerId>, fault: AgentFault, phase: ArenaPhase) -> Self {
        ArenaOutcomeV1::Aborted {
            at_fault_seat,
            fault,
            phase,
        }
    }
}

/// The version-1 arena report. `report_format` and `report_version` make the
/// envelope self-describing; the arena pins them to [`ARENA_REPORT_FORMAT`] and
/// [`ARENA_REPORT_VERSION`].
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ArenaReportV1 {
    /// Always [`ARENA_REPORT_FORMAT`].
    pub report_format: String,
    /// Always [`ARENA_REPORT_VERSION`].
    pub report_version: u32,
    /// The arena `game_id` this report belongs to.
    pub game_id: String,
    /// Bound agent identities, in seat order.
    pub agents: Vec<AgentIdentity>,
    /// Final outcome.
    pub outcome: ArenaOutcomeV1,
}

impl ArenaReportV1 {
    /// Construct a report envelope with the frozen format/version tags.
    pub fn new(
        game_id: impl Into<String>,
        agents: Vec<AgentIdentity>,
        outcome: ArenaOutcomeV1,
    ) -> Self {
        ArenaReportV1 {
            report_format: ARENA_REPORT_FORMAT.to_string(),
            report_version: ARENA_REPORT_VERSION,
            game_id: game_id.into(),
            agents,
            outcome,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use splendor_core::TerminalReason;

    fn sample_result() -> GameResult {
        GameResult {
            scores: vec![15, 10],
            ranks: vec![1, 2],
            winners: vec![PlayerId(0)],
            reason: TerminalReason::PrestigeThreshold,
        }
    }

    #[test]
    fn completed_roundtrips_with_deny_unknown_fields() {
        let report = ArenaReportV1::new(
            "g1",
            vec![
                AgentIdentity {
                    seat: PlayerId(0),
                    label: "a".into(),
                },
                AgentIdentity {
                    seat: PlayerId(1),
                    label: "b".into(),
                },
            ],
            ArenaOutcomeV1::completed(vec![PlayerId(0)], sample_result()),
        );
        let json = serde_json::to_string(&report).unwrap();
        let back: ArenaReportV1 = serde_json::from_str(&json).unwrap();
        assert_eq!(report, back);

        // Unknown top-level field must be rejected.
        let noisy = json.trim_end_matches('}').to_string() + ",\"extra\":1}";
        assert!(serde_json::from_str::<ArenaReportV1>(&noisy).is_err());
    }

    #[test]
    fn aborted_carries_no_winners_or_result() {
        let json = serde_json::to_string(&ArenaOutcomeV1::aborted(
            Some(PlayerId(1)),
            AgentFault::ActionTimeout,
            ArenaPhase::ActionRequest,
        ))
        .unwrap();
        assert!(!json.contains("winners"));
        assert!(!json.contains("result"));
        assert!(json.contains("\"status\":\"aborted\""));
        assert!(json.contains("\"fault\":\"action_timeout\""));

        let back: ArenaOutcomeV1 = serde_json::from_str(&json).unwrap();
        match back {
            ArenaOutcomeV1::Aborted {
                at_fault_seat,
                fault,
                phase,
            } => {
                assert_eq!(at_fault_seat, Some(PlayerId(1)));
                assert_eq!(fault, AgentFault::ActionTimeout);
                assert_eq!(phase, ArenaPhase::ActionRequest);
            }
            ArenaOutcomeV1::Completed { .. } => panic!("aborted deserialized as completed"),
        }
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
