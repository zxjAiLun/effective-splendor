//! Match-side counters, per-seat handshake state, and pure message validation.
//!
//! These pieces are deliberately separable from the transport so they can be
//! unit-tested with an in-memory endpoint. The runner owns the global counters
//! and a `SeatState` per seat; the validation helpers turn a parsed client
//! message (plus the frozen server expectations) into either an extracted
//! intent or a categorised [`AgentFault`].
//!
//! Counters use checked arithmetic: a `u64`/`u32` overflow is an arena-internal
//! error, never a silent wrap.

use splendor_core::{Action, PlayerId};

use crate::error::ArenaInternalError;
use crate::report::{AgentFault, AgentIdentity};

/// Maximum UTF-8 byte length of an agent-declared `agent_name` / `agent_version`.
pub const MAX_AGENT_FIELD_BYTES: usize = 128;

/// Global match counters, owned by the runner.
///
/// - `server_seq` is assigned (and incremented) for every server message the
///   arena constructs, so messages addressed to different seats never reuse a
///   sequence.
/// - `request_id` is assigned only to a `RequestAction`; it advances after a
///   successfully processed action.
/// - `completed_plies` counts plies that actually drove the engine.
#[derive(Debug, Default)]
pub struct MatchCounters {
    server_seq: u64,
    request_id: u64,
    completed_plies: u32,
}

impl MatchCounters {
    /// Reserve and return the next globally-unique server sequence number.
    pub fn next_server_seq(&mut self) -> Result<u64, ArenaInternalError> {
        let value = self.server_seq;
        self.server_seq = self
            .server_seq
            .checked_add(1)
            .ok_or_else(|| ArenaInternalError::Engine("server_seq overflow".into()))?;
        Ok(value)
    }

    /// Reserve and return the next request id. The first `RequestAction` of a
    /// match therefore carries `1`.
    pub fn next_request_id(&mut self) -> Result<u64, ArenaInternalError> {
        self.request_id = self
            .request_id
            .checked_add(1)
            .ok_or_else(|| ArenaInternalError::Engine("request_id overflow".into()))?;
        Ok(self.request_id)
    }

    /// Record one successfully applied ply.
    pub fn inc_completed(&mut self) -> Result<(), ArenaInternalError> {
        self.completed_plies = self
            .completed_plies
            .checked_add(1)
            .ok_or_else(|| ArenaInternalError::Engine("completed_plies overflow".into()))?;
        Ok(())
    }

    /// Number of plies applied so far.
    pub fn completed_plies(&self) -> u32 {
        self.completed_plies
    }

    /// The request id currently in flight (the one a pending action must echo).
    pub fn current_request_id(&self) -> u64 {
        self.request_id
    }
}

/// Per-seat lifecycle state owned by the runner.
///
/// The seat is fixed at spawn time (`PlayerId(index)`) and never read from the
/// client; the client cannot claim or change a seat. Identity is populated only
/// after a successful handshake.
#[derive(Debug, Clone)]
pub struct SeatState {
    /// The runner-assigned seat (never from the client).
    pub seat: PlayerId,
    /// Whether this seat has completed the handshake.
    pub handshake_done: bool,
    /// Agent identity, filled in after handshake; `None` before that.
    pub identity: AgentIdentity,
}

impl SeatState {
    /// Create a fresh, not-yet-handshaken seat.
    pub fn new(seat: PlayerId) -> Self {
        SeatState {
            seat,
            handshake_done: false,
            identity: AgentIdentity {
                seat,
                agent_name: None,
                agent_version: None,
            },
        }
    }
}

/// Validate a single agent-declared identity field (name or version).
///
/// Rejects empty values, values longer than [`MAX_AGENT_FIELD_BYTES`] UTF-8
/// bytes, or any C0 control character (`< 0x20`). All such failures are
/// reported as [`AgentFault::MalformedMessage`].
pub fn validate_identity(field: &str) -> Result<(), AgentFault> {
    if field.trim().is_empty() {
        return Err(AgentFault::MalformedMessage);
    }
    let bytes = field.as_bytes();
    if bytes.len() > MAX_AGENT_FIELD_BYTES {
        return Err(AgentFault::MalformedMessage);
    }
    if bytes.iter().any(|b| *b < 0x20) {
        return Err(AgentFault::MalformedMessage);
    }
    Ok(())
}

/// Validate a client `hello` against the frozen server expectations.
///
/// Order of checks follows the spec: the message is already known to be a
/// `Hello`; we then check protocol version, game id, then identity fields.
pub fn validate_hello(
    protocol_version: &str,
    game_id: &str,
    agent_name: &str,
    agent_version: &str,
    expected_protocol: &str,
    expected_game_id: &str,
) -> Result<(String, String), AgentFault> {
    if protocol_version != expected_protocol {
        return Err(AgentFault::ProtocolVersionMismatch);
    }
    if game_id != expected_game_id {
        return Err(AgentFault::GameIdMismatch);
    }
    validate_identity(agent_name)?;
    validate_identity(agent_version)?;
    Ok((agent_name.to_string(), agent_version.to_string()))
}

/// Validate a client action response against the in-flight request.
///
/// Returns the action to apply on success. The legality check is the final,
/// authoritative gate: an action not present in the sent `legal_actions` set
/// is [`AgentFault::IllegalAction`].
#[allow(clippy::too_many_arguments)]
pub fn validate_action(
    protocol_version: &str,
    game_id: &str,
    request_id: u64,
    action: Action,
    expected_protocol: &str,
    expected_game_id: &str,
    outstanding_request_id: u64,
    legal_actions: &[Action],
) -> Result<Action, AgentFault> {
    if protocol_version != expected_protocol {
        return Err(AgentFault::ProtocolVersionMismatch);
    }
    if game_id != expected_game_id {
        return Err(AgentFault::GameIdMismatch);
    }
    if request_id != outstanding_request_id {
        return Err(AgentFault::WrongRequestId);
    }
    if !legal_actions.contains(&action) {
        return Err(AgentFault::IllegalAction);
    }
    Ok(action)
}

#[cfg(test)]
mod tests {
    use super::*;
    use splendor_protocol::PROTOCOL_VERSION;

    #[test]
    fn server_seq_is_unique_and_monotonic() {
        let mut c = MatchCounters::default();
        let a = c.next_server_seq().unwrap();
        let b = c.next_server_seq().unwrap();
        let d = c.next_server_seq().unwrap();
        assert!(a < b && b < d);
        assert_eq!((a, b, d), (0, 1, 2));
    }

    #[test]
    fn request_id_starts_at_one() {
        let mut c = MatchCounters::default();
        assert_eq!(c.next_request_id().unwrap(), 1);
        assert_eq!(c.next_request_id().unwrap(), 2);
    }

    #[test]
    fn counters_overflow_is_internal_error() {
        let mut c = MatchCounters {
            server_seq: u64::MAX,
            request_id: 0,
            completed_plies: 0,
        };
        assert!(c.next_server_seq().is_err());
        let mut c = MatchCounters {
            server_seq: 0,
            request_id: u64::MAX,
            completed_plies: 0,
        };
        assert!(c.next_request_id().is_err());
    }

    #[test]
    fn identity_rejects_control_and_overlong() {
        assert!(validate_identity("ok").is_ok());
        assert!(validate_identity("").is_err());
        assert!(validate_identity(" ").is_err());
        assert!(validate_identity("bad\nname").is_err());
        let long = "x".repeat(MAX_AGENT_FIELD_BYTES + 1);
        assert!(validate_identity(&long).is_err());
    }

    #[test]
    fn hello_validation_orders_checks() {
        assert_eq!(
            validate_hello("0.4", "g1", "n", "v", PROTOCOL_VERSION, "g1"),
            Err(AgentFault::ProtocolVersionMismatch)
        );
        assert_eq!(
            validate_hello(PROTOCOL_VERSION, "other", "n", "v", PROTOCOL_VERSION, "g1"),
            Err(AgentFault::GameIdMismatch)
        );
        assert_eq!(
            validate_hello(PROTOCOL_VERSION, "g1", "", "v", PROTOCOL_VERSION, "g1"),
            Err(AgentFault::MalformedMessage)
        );
        assert_eq!(
            validate_hello(PROTOCOL_VERSION, "g1", "n", "v", PROTOCOL_VERSION, "g1"),
            Ok(("n".to_string(), "v".to_string()))
        );
    }

    #[test]
    fn action_validation_gates_request_and_legality() {
        let legal = vec![
            Action::Pass,
            Action::ReserveDeck {
                tier: splendor_core::Tier::One,
                give_back: splendor_core::Gems::ZERO,
            },
        ];
        // wrong request id
        assert_eq!(
            validate_action(
                PROTOCOL_VERSION,
                "g1",
                7,
                Action::Pass,
                PROTOCOL_VERSION,
                "g1",
                1,
                &legal
            ),
            Err(AgentFault::WrongRequestId)
        );
        // illegal action
        assert_eq!(
            validate_action(
                PROTOCOL_VERSION,
                "g1",
                1,
                Action::BuyMarket {
                    tier: splendor_core::Tier::One,
                    slot: 9
                },
                PROTOCOL_VERSION,
                "g1",
                1,
                &legal
            ),
            Err(AgentFault::IllegalAction)
        );
        // legal action, correct request id
        assert_eq!(
            validate_action(
                PROTOCOL_VERSION,
                "g1",
                1,
                Action::Pass,
                PROTOCOL_VERSION,
                "g1",
                1,
                &legal
            ),
            Ok(Action::Pass)
        );
    }
}
