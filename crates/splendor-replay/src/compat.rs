//! Single source of truth for Replay v1 ruleset compatibility.
//!
//! The recorder and the verifier both need to answer the same question — "is
//! this ruleset the canonical `splendor-base-v1`?" — but at different points:
//! the recorder checks a *runtime* `Ruleset` before it drives the engine, while
//! the verifier checks a recorded `ReplayRulesetV1` DTO. Keeping one field list
//! here guarantees the two sides can never drift apart, so the recorder can
//! only ever emit documents the verifier accepts.

use splendor_core::Ruleset;

use crate::error::{ReplayError, ReplayResult};
use crate::format::{ReplayRulesetV1, SUPPORTED_RULESET_ID};

/// Compare a recorded ruleset DTO against the engine's canonical ruleset,
/// field by field. This is the only place the field list lives.
pub(crate) fn check_ruleset_params(
    recorded: &ReplayRulesetV1,
    engine: &Ruleset,
) -> ReplayResult<()> {
    macro_rules! check {
        ($field:literal, $recorded:expr, $engine:expr) => {
            if $recorded != $engine {
                return Err(ReplayError::RulesetParameterMismatch {
                    field: $field,
                    current: format!("{:?}", $engine),
                    recorded: format!("{:?}", $recorded),
                });
            }
        };
    }
    check!("id", recorded.id.as_str(), engine.id.0);
    check!(
        "catalog_version",
        recorded.catalog_version.as_str(),
        engine.catalog_version
    );
    check!("min_players", recorded.min_players, engine.min_players);
    check!("max_players", recorded.max_players, engine.max_players);
    check!(
        "prestige_to_end",
        recorded.prestige_to_end,
        engine.prestige_to_end
    );
    check!("max_tokens", recorded.max_tokens, engine.max_tokens);
    check!("max_reserved", recorded.max_reserved, engine.max_reserved);
    check!(
        "market_slots_per_tier",
        recorded.market_slots_per_tier,
        engine.market_slots_per_tier
    );
    check!("gold_tokens", recorded.gold_tokens, engine.gold_tokens);
    check!(
        "color_tokens_by_players",
        recorded.color_tokens_by_players,
        engine.color_tokens_by_players
    );
    check!("noble_extra", recorded.noble_extra, engine.noble_extra);
    Ok(())
}

/// Ensure a *runtime* `Ruleset` is a canonical `splendor-base-v1` before it is
/// used to drive a recorder.
///
/// Replay v1 only understands canonical base-v1 games; anything else would
/// produce a replay the verifier is guaranteed to reject. Rejecting here — at
/// recorder construction, before any `FullState` is built — keeps the recorder
/// public contract honest: every document it can emit must verify.
pub(crate) fn ensure_supported_runtime_ruleset(ruleset: &Ruleset) -> ReplayResult<()> {
    if ruleset.id.0 != SUPPORTED_RULESET_ID {
        return Err(ReplayError::UnsupportedRuleset(ruleset.id.0.to_string()));
    }
    check_ruleset_params(&ReplayRulesetV1::from_ruleset(ruleset), &Ruleset::base_v1())
}
