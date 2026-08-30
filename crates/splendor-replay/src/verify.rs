use splendor_core::{
    full_state_hash, ruleset_fingerprint, Action, FullState, GameConfig, PlayerId, Ruleset,
    CATALOG_VERSION, ENGINE_VERSION,
};

use crate::compat::check_ruleset_params;
use crate::error::{ReplayError, ReplayResult};
use crate::format::{
    ReplayV1, RolloutPrefixV1, REPLAY_FORMAT, REPLAY_VERSION, ROLLOUT_PREFIX_FORMAT,
    ROLLOUT_PREFIX_VERSION, SUPPORTED_RULESET_ID,
};

/// A replay that has been fully re-executed and confirmed against the engine.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VerifiedReplay {
    pub player_count: u8,
    pub steps: u32,
    pub final_state_hash: String,
    pub result: crate::format::ReplayGameResultV1,
}

/// One fully verified replay position: the referee `FullState` as it stood
/// *before* `replay.steps[ply]` was executed, together with the recorded
/// decision at that ply and the summary of the whole verified replay.
///
/// This value is only ever produced after the **entire** replay — prefix,
/// the captured position, and the full suffix through the terminal result —
/// has been re-executed and verified. A tampered step anywhere in the replay
/// (including after the captured ply) prevents this value from existing.
///
/// Information boundary: like the replay itself this carries a referee-only
/// `FullState` (deck order, blind reserves) and MUST NOT be sent to an agent.
#[derive(Debug, Clone)]
pub struct VerifiedReplayPosition {
    /// Summary of the fully verified replay (identical to [`verify_replay`]).
    pub verified: VerifiedReplay,
    /// The requested ply: `state` is the position before `steps[ply]`.
    pub ply: u32,
    /// `full_state_hash` of `state`; equals `steps[ply].state_hash_before`.
    pub state_hash: String,
    /// The rebuilt referee state before the recorded action at `ply`.
    pub state: FullState,
    /// The actor recorded at `steps[ply]`; equals `state.current_player`.
    pub recorded_actor: PlayerId,
    /// The action recorded at `steps[ply]`.
    pub recorded_action: Action,
}

/// Every decision state from one replay, captured during a single strict
/// verification pass. This is a referee/offline artifact and must be projected
/// before use in a player-view dataset.
#[derive(Debug, Clone)]
pub struct VerifiedReplayTrace {
    pub verified: VerifiedReplay,
    pub positions: Vec<VerifiedReplayTraceStep>,
}

#[derive(Debug, Clone)]
pub struct VerifiedReplayTraceStep {
    pub ply: u32,
    pub state_hash: String,
    pub state: FullState,
    pub recorded_actor: PlayerId,
    pub recorded_action: Action,
}

/// A position captured mid-verification by [`verify_replay_core`].
struct CapturedPosition {
    state: FullState,
    state_hash: String,
    actor: PlayerId,
    action: Action,
}

/// Re-execute and strictly verify a replay, ply by ply.
///
/// On any divergence the returned error names the exact `ply` (where relevant)
/// and the specific kind of mismatch. This never returns a bare "mismatch".
pub fn verify_replay(replay: &ReplayV1) -> ReplayResult<VerifiedReplay> {
    let (verified, _) = verify_replay_core(replay, None, false)?;
    Ok(verified)
}

/// Fully verify a replay and return the referee state *before*
/// `replay.steps[ply]` was executed, together with the recorded decision.
///
/// Frozen semantics:
/// - `ply` addresses the state before `replay.steps[ply]`; the legal range is
///   `0 <= ply < replay.steps.len()`. `ply == steps.len()` is rejected with
///   [`ReplayError::PlyOutOfRange`] — the complete replay is terminal and has
///   no pending recorded decision to analyze.
/// - The **whole** replay is verified, not just the prefix up to `ply`: the
///   position is cloned only after its before-hash check succeeds, and the
///   entire suffix (through the final hash and result) must also verify. A
///   tampered suffix after the target ply therefore fails this API too.
///
/// Both this function and [`verify_replay`] share one private verifier core;
/// there is deliberately no second replay verifier.
pub fn verify_replay_position(replay: &ReplayV1, ply: u32) -> ReplayResult<VerifiedReplayPosition> {
    let steps = replay.steps.len() as u32;
    if ply >= steps {
        return Err(ReplayError::PlyOutOfRange {
            requested: ply,
            steps,
        });
    }
    let (verified, captured) = verify_replay_core(replay, Some(ply), false)?;
    // The bounds check above guarantees the capture happened; stay fail-closed
    // rather than unwrap if that invariant is ever broken.
    let captured = captured
        .into_iter()
        .next()
        .ok_or(ReplayError::PlyOutOfRange {
            requested: ply,
            steps,
        })?;
    Ok(VerifiedReplayPosition {
        verified,
        ply,
        state_hash: captured.state_hash,
        state: captured.state,
        recorded_actor: captured.actor,
        recorded_action: captured.action,
    })
}

/// Strictly verify a replay once and capture every pre-action referee state.
/// Callers must project each state to its recorded actor before serialization.
pub fn verify_replay_trace(replay: &ReplayV1) -> ReplayResult<VerifiedReplayTrace> {
    let (verified, positions) = verify_replay_core(replay, None, true)?;
    let positions = positions
        .into_iter()
        .enumerate()
        .map(|(index, captured)| VerifiedReplayTraceStep {
            ply: index as u32,
            state_hash: captured.state_hash,
            state: captured.state,
            recorded_actor: captured.actor,
            recorded_action: captured.action,
        })
        .collect();
    Ok(VerifiedReplayTrace {
        verified,
        positions,
    })
}

/// A capped rollout prefix that has been fully re-executed and confirmed
/// against the engine, with every pre-action referee state captured.
///
/// This is the truncated-game counterpart of [`VerifiedReplayTrace`]: same
/// per-ply strictness, but the final state is the non-terminal cap state
/// instead of a terminal result. There is deliberately no `result` field.
#[derive(Debug, Clone)]
pub struct VerifiedRolloutPrefix {
    pub player_count: u8,
    pub steps: u32,
    pub cap_state_hash: String,
    pub positions: Vec<VerifiedReplayTraceStep>,
}

/// Strictly verify a capped rollout prefix: rebuild from seed + ruleset,
/// re-execute every step against the engine, check every before/after hash,
/// and require the rebuilt cap-state hash to match. The rebuilt state after
/// the last step must be non-terminal — a terminal prefix is a completed
/// game and must be represented as a [`ReplayV1`] instead.
pub fn verify_rollout_prefix(prefix: &RolloutPrefixV1) -> ReplayResult<VerifiedRolloutPrefix> {
    if prefix.format != ROLLOUT_PREFIX_FORMAT {
        return Err(ReplayError::WrongFormat {
            expected: ROLLOUT_PREFIX_FORMAT.to_string(),
            found: prefix.format.clone(),
        });
    }
    if prefix.version != ROLLOUT_PREFIX_VERSION {
        return Err(ReplayError::UnsupportedVersion {
            supported: ROLLOUT_PREFIX_VERSION,
            found: prefix.version,
        });
    }
    if prefix.engine_version != ENGINE_VERSION {
        return Err(ReplayError::EngineVersionMismatch {
            current: ENGINE_VERSION.to_string(),
            recorded: prefix.engine_version.clone(),
        });
    }
    if prefix.ruleset.catalog_version != CATALOG_VERSION {
        return Err(ReplayError::CatalogVersionMismatch {
            current: CATALOG_VERSION.to_string(),
            recorded: prefix.ruleset.catalog_version.clone(),
        });
    }
    if prefix.ruleset.id != SUPPORTED_RULESET_ID {
        return Err(ReplayError::UnsupportedRuleset(prefix.ruleset.id.clone()));
    }

    let engine_ruleset = Ruleset::base_v1();
    check_ruleset_params(&prefix.ruleset, &engine_ruleset)?;
    let engine_fingerprint = ruleset_fingerprint(&engine_ruleset);
    if prefix.ruleset_fingerprint.as_str() != engine_fingerprint.as_str() {
        return Err(ReplayError::RulesetFingerprintMismatch {
            current: engine_fingerprint.as_str().to_string(),
            recorded: prefix.ruleset_fingerprint.as_str().to_string(),
        });
    }

    if prefix.player_count < engine_ruleset.min_players
        || prefix.player_count > engine_ruleset.max_players
    {
        return Err(ReplayError::InvalidPlayerCount {
            recorded: prefix.player_count,
            min: engine_ruleset.min_players,
            max: engine_ruleset.max_players,
        });
    }

    if prefix.steps.is_empty() {
        return Err(ReplayError::EmptyPrefix);
    }
    if prefix.steps.len() as u32 != prefix.ply_cap {
        return Err(ReplayError::PrefixStepCountMismatch {
            steps: prefix.steps.len() as u32,
            ply_cap: prefix.ply_cap,
        });
    }

    let (mut state, _) = FullState::new(GameConfig {
        player_count: prefix.player_count,
        seed: prefix.seed,
        ruleset: engine_ruleset,
    })?;
    if state.player_count() != prefix.player_count {
        return Err(ReplayError::PlayerCountMismatch {
            recorded: prefix.player_count,
            rebuilt: state.player_count(),
        });
    }

    let initial = full_state_hash(&state);
    if initial.as_str() != prefix.initial_state_hash.as_str() {
        return Err(ReplayError::InitialHashMismatch {
            expected: prefix.initial_state_hash.as_str().to_string(),
            actual: initial.as_str().to_string(),
        });
    }

    let mut positions = Vec::with_capacity(prefix.steps.len());
    for (index, step) in prefix.steps.iter().enumerate() {
        let expected_ply = index as u32;
        if step.ply != expected_ply {
            return Err(ReplayError::NonContiguousPly {
                ply: step.ply,
                expected: expected_ply,
            });
        }
        if state.is_terminal() {
            return Err(ReplayError::StepAfterTerminal { ply: step.ply });
        }
        if state.current_player != step.actor {
            return Err(ReplayError::ActorMismatch {
                ply: step.ply,
                expected: state.current_player,
                recorded: step.actor,
            });
        }
        let before = full_state_hash(&state);
        if before.as_str() != step.state_hash_before.as_str() {
            return Err(ReplayError::BeforeHashMismatch {
                ply: step.ply,
                expected: step.state_hash_before.as_str().to_string(),
                actual: before.as_str().to_string(),
            });
        }
        positions.push(VerifiedReplayTraceStep {
            ply: step.ply,
            state_hash: before.as_str().to_string(),
            state: state.clone(),
            recorded_actor: step.actor,
            recorded_action: step.action,
        });
        if !state.legal_actions().contains(&step.action) {
            return Err(ReplayError::IllegalAction {
                ply: step.ply,
                action: step.action,
                source: splendor_core::EngineError::IllegalAction(format!("{:?}", step.action)),
            });
        }
        state
            .apply(step.action)
            .map_err(|source| ReplayError::IllegalAction {
                ply: step.ply,
                action: step.action,
                source,
            })?;
        state
            .assert_invariants()
            .map_err(|source| ReplayError::InvariantBroken {
                ply: step.ply,
                source,
            })?;
        let after = full_state_hash(&state);
        if after.as_str() != step.state_hash_after.as_str() {
            return Err(ReplayError::AfterHashMismatch {
                ply: step.ply,
                expected: step.state_hash_after.as_str().to_string(),
                actual: after.as_str().to_string(),
            });
        }
    }

    if state.is_terminal() {
        return Err(ReplayError::PrefixTerminal {
            plies: prefix.steps.len() as u32,
        });
    }
    let cap_hash = full_state_hash(&state);
    if cap_hash.as_str() != prefix.cap_state_hash.as_str() {
        return Err(ReplayError::CapHashMismatch {
            expected: prefix.cap_state_hash.as_str().to_string(),
            actual: cap_hash.as_str().to_string(),
        });
    }

    Ok(VerifiedRolloutPrefix {
        player_count: prefix.player_count,
        steps: prefix.steps.len() as u32,
        cap_state_hash: cap_hash.as_str().to_string(),
        positions,
    })
}

/// The single verifier core shared by [`verify_replay`] and
/// [`verify_replay_position`].
///
/// Runs the complete strict verification; when `capture_ply` is `Some(p)` it
/// additionally clones the state at ply `p` immediately after that step's
/// before-hash check succeeds, then keeps verifying the rest of the replay.
fn verify_replay_core(
    replay: &ReplayV1,
    capture_ply: Option<u32>,
    capture_all: bool,
) -> ReplayResult<(VerifiedReplay, Vec<CapturedPosition>)> {
    // 1. Format + replay version.
    if replay.format != REPLAY_FORMAT {
        return Err(ReplayError::WrongFormat {
            expected: REPLAY_FORMAT.to_string(),
            found: replay.format.clone(),
        });
    }
    if replay.version != REPLAY_VERSION {
        return Err(ReplayError::UnsupportedVersion {
            supported: REPLAY_VERSION,
            found: replay.version,
        });
    }

    // 2. Engine + catalog + ruleset compatibility.
    if replay.engine_version != ENGINE_VERSION {
        return Err(ReplayError::EngineVersionMismatch {
            current: ENGINE_VERSION.to_string(),
            recorded: replay.engine_version.clone(),
        });
    }
    if replay.ruleset.catalog_version != CATALOG_VERSION {
        return Err(ReplayError::CatalogVersionMismatch {
            current: CATALOG_VERSION.to_string(),
            recorded: replay.ruleset.catalog_version.clone(),
        });
    }
    if replay.ruleset.id != SUPPORTED_RULESET_ID {
        return Err(ReplayError::UnsupportedRuleset(replay.ruleset.id.clone()));
    }

    let engine_ruleset = Ruleset::base_v1();
    check_ruleset_params(&replay.ruleset, &engine_ruleset)?;

    // 3. Ruleset fingerprint.
    let engine_fingerprint = ruleset_fingerprint(&engine_ruleset);
    if replay.ruleset_fingerprint.as_str() != engine_fingerprint.as_str() {
        return Err(ReplayError::RulesetFingerprintMismatch {
            current: engine_fingerprint.as_str().to_string(),
            recorded: replay.ruleset_fingerprint.as_str().to_string(),
        });
    }

    // 4. Player count: validate the recorded count is in range *before*
    //    rebuilding, so an out-of-range count yields a precise
    //    `InvalidPlayerCount` rather than a generic engine error surfacing from
    //    `FullState::new`.
    if replay.player_count < engine_ruleset.min_players
        || replay.player_count > engine_ruleset.max_players
    {
        return Err(ReplayError::InvalidPlayerCount {
            recorded: replay.player_count,
            min: engine_ruleset.min_players,
            max: engine_ruleset.max_players,
        });
    }

    // 5. Rebuild the initial state from ruleset + seed + player count.
    let (mut state, _) = FullState::new(GameConfig {
        player_count: replay.player_count,
        seed: replay.seed,
        ruleset: engine_ruleset,
    })?;

    // Defense in depth: guard against engine clamping differences between the
    // recorded count and the rebuilt state.
    if state.player_count() != replay.player_count {
        return Err(ReplayError::PlayerCountMismatch {
            recorded: replay.player_count,
            rebuilt: state.player_count(),
        });
    }

    // 6. Initial state hash.
    let initial = full_state_hash(&state);
    if initial.as_str() != replay.initial_state_hash.as_str() {
        return Err(ReplayError::InitialHashMismatch {
            expected: replay.initial_state_hash.as_str().to_string(),
            actual: initial.as_str().to_string(),
        });
    }

    // 7. Step-by-step verification (capturing the requested position, if any,
    //    once its before-hash check has succeeded).
    let mut captured: Vec<CapturedPosition> = Vec::new();
    for (index, step) in replay.steps.iter().enumerate() {
        let expected_ply = index as u32;
        if step.ply != expected_ply {
            return Err(ReplayError::NonContiguousPly {
                ply: step.ply,
                expected: expected_ply,
            });
        }

        if state.is_terminal() {
            return Err(ReplayError::StepAfterTerminal { ply: step.ply });
        }

        if state.current_player != step.actor {
            return Err(ReplayError::ActorMismatch {
                ply: step.ply,
                expected: state.current_player,
                recorded: step.actor,
            });
        }

        let before = full_state_hash(&state);
        if before.as_str() != step.state_hash_before.as_str() {
            return Err(ReplayError::BeforeHashMismatch {
                ply: step.ply,
                expected: step.state_hash_before.as_str().to_string(),
                actual: before.as_str().to_string(),
            });
        }

        if capture_all || capture_ply == Some(step.ply) {
            captured.push(CapturedPosition {
                state: state.clone(),
                state_hash: before.as_str().to_string(),
                actor: step.actor,
                action: step.action,
            });
        }

        if !state.legal_actions().contains(&step.action) {
            return Err(ReplayError::IllegalAction {
                ply: step.ply,
                action: step.action,
                source: splendor_core::EngineError::IllegalAction(format!("{:?}", step.action)),
            });
        }

        state
            .apply(step.action)
            .map_err(|source| ReplayError::IllegalAction {
                ply: step.ply,
                action: step.action,
                source,
            })?;

        state
            .assert_invariants()
            .map_err(|source| ReplayError::InvariantBroken {
                ply: step.ply,
                source,
            })?;

        let after = full_state_hash(&state);
        if after.as_str() != step.state_hash_after.as_str() {
            return Err(ReplayError::AfterHashMismatch {
                ply: step.ply,
                expected: step.state_hash_after.as_str().to_string(),
                actual: after.as_str().to_string(),
            });
        }
    }

    // 8. Must be terminal after the recorded steps.
    if !state.is_terminal() {
        return Err(ReplayError::NotTerminal {
            plies: replay.steps.len() as u32,
        });
    }

    // 10. Final state hash.
    let final_hash = full_state_hash(&state);
    if final_hash.as_str() != replay.final_state_hash.as_str() {
        return Err(ReplayError::FinalHashMismatch {
            expected: replay.final_state_hash.as_str().to_string(),
            actual: final_hash.as_str().to_string(),
        });
    }

    // 11. Final result.
    let result = state.result.as_ref().ok_or(ReplayError::ResultMismatch)?;
    if !replay.result.matches(result) {
        return Err(ReplayError::ResultMismatch);
    }

    Ok((
        VerifiedReplay {
            player_count: replay.player_count,
            steps: replay.steps.len() as u32,
            final_state_hash: final_hash.as_str().to_string(),
            result: replay.result.clone(),
        },
        captured,
    ))
}
