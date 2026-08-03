use splendor_belief::{build_information_set_v1, InformationSetHashV1, VisibleHistoryHashV1};
use splendor_core::{Observation, Ruleset, VisibleEvent};

use crate::config::RootDeterminizationConfigV1;
use crate::error::ImperfectSearchError;
use crate::model::RootDeterminizationResultV1;
use crate::search::aggregate_root_determinizations_v1;

/// Replay-neutral composition result for one player information view.
///
/// The constructor is intentionally private. Callers must provide the
/// validated ruleset, observation, and visible transcript to
/// [`analyze_player_view_v1`]; they cannot inject hashes or bypass the C1
/// information-set invariants.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PlayerViewRootAnalysisV1 {
    visible_history_hash: VisibleHistoryHashV1,
    information_set_hash: InformationSetHashV1,
    result: RootDeterminizationResultV1,
}

impl PlayerViewRootAnalysisV1 {
    /// SHA-256 identity of the visible transcript supplied to the composition
    /// API.
    pub fn visible_history_hash(&self) -> &VisibleHistoryHashV1 {
        &self.visible_history_hash
    }

    /// SHA-256 identity of the validated observation plus visible transcript.
    pub fn information_set_hash(&self) -> &InformationSetHashV1 {
        &self.information_set_hash
    }

    /// The C3 root-determinization result.
    pub fn result(&self) -> &RootDeterminizationResultV1 {
        &self.result
    }
}

/// Build a validated player information set and aggregate its root actions.
///
/// This is the replay-neutral boundary used by offline bindings. It accepts
/// only a runtime observation and the already-projected visible history; raw
/// replay seeds, referee events, deck order, and full states do not cross this
/// API.
pub fn analyze_player_view_v1(
    ruleset: Ruleset,
    observation: &Observation,
    visible_history: &[VisibleEvent],
    config: RootDeterminizationConfigV1,
) -> Result<PlayerViewRootAnalysisV1, ImperfectSearchError> {
    let information_set = build_information_set_v1(ruleset, observation, visible_history)?;
    let visible_history_hash = information_set.visible_history_hash().clone();
    let information_set_hash = information_set.information_set_hash().clone();
    let result = aggregate_root_determinizations_v1(&information_set, config)?;

    Ok(PlayerViewRootAnalysisV1 {
        visible_history_hash,
        information_set_hash,
        result,
    })
}
