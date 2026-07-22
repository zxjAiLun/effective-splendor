use splendor_core::{
    full_state_hash, ruleset_fingerprint, FullState, GameConfig, Ruleset, CATALOG_VERSION,
    ENGINE_VERSION,
};

use crate::compat::check_ruleset_params;
use crate::error::{ReplayError, ReplayResult};
use crate::format::{ReplayV1, REPLAY_FORMAT, REPLAY_VERSION, SUPPORTED_RULESET_ID};

/// A replay that has been fully re-executed and confirmed against the engine.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VerifiedReplay {
    pub player_count: u8,
    pub steps: u32,
    pub final_state_hash: String,
    pub result: crate::format::ReplayGameResultV1,
}

/// Re-execute and strictly verify a replay, ply by ply.
///
/// On any divergence the returned error names the exact `ply` (where relevant)
/// and the specific kind of mismatch. This never returns a bare "mismatch".
pub fn verify_replay(replay: &ReplayV1) -> ReplayResult<VerifiedReplay> {
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

    // 7. Step-by-step verification.
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

    Ok(VerifiedReplay {
        player_count: replay.player_count,
        steps: replay.steps.len() as u32,
        final_state_hash: final_hash.as_str().to_string(),
        result: replay.result.clone(),
    })
}
