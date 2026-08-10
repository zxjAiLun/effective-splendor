use splendor_belief::{build_information_set_v1, InformationSetHashV1, VisibleHistoryHashV1};
use splendor_core::{Observation, Ruleset, VisibleEvent};

use crate::{search_ismcts_v1, IsmctsConfigV1, IsmctsError, IsmctsResultV1};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PlayerViewIsmctsAnalysisV1 {
    visible_history_hash: VisibleHistoryHashV1,
    information_set_hash: InformationSetHashV1,
    result: IsmctsResultV1,
}

impl PlayerViewIsmctsAnalysisV1 {
    pub fn visible_history_hash(&self) -> &VisibleHistoryHashV1 {
        &self.visible_history_hash
    }

    pub fn information_set_hash(&self) -> &InformationSetHashV1 {
        &self.information_set_hash
    }

    pub fn result(&self) -> &IsmctsResultV1 {
        &self.result
    }
}

pub fn analyze_player_view_ismcts_v1(
    ruleset: Ruleset,
    observation: &Observation,
    visible_history: &[VisibleEvent],
    config: IsmctsConfigV1,
) -> Result<PlayerViewIsmctsAnalysisV1, IsmctsError> {
    let information_set = build_information_set_v1(ruleset, observation, visible_history)
        .map_err(|error| IsmctsError::Belief(error.to_string()))?;
    let visible_history_hash = information_set.visible_history_hash().clone();
    let information_set_hash = information_set.information_set_hash().clone();
    let result = search_ismcts_v1(&information_set, config)?;
    Ok(PlayerViewIsmctsAnalysisV1 {
        visible_history_hash,
        information_set_hash,
        result,
    })
}
