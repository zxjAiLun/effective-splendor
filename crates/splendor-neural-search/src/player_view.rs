use splendor_belief::{build_information_set_v1, InformationSetHashV1, VisibleHistoryHashV1};
use splendor_core::{Observation, Ruleset, VisibleEvent};
use splendor_learning::PolicyValueModelV1;

use crate::{
    search_neural_ismcts_v1, NeuralIsmctsConfigV1, NeuralIsmctsResultV1, NeuralSearchError,
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PlayerViewNeuralIsmctsAnalysisV1 {
    visible_history_hash: VisibleHistoryHashV1,
    information_set_hash: InformationSetHashV1,
    result: NeuralIsmctsResultV1,
}

impl PlayerViewNeuralIsmctsAnalysisV1 {
    pub fn visible_history_hash(&self) -> &VisibleHistoryHashV1 {
        &self.visible_history_hash
    }

    pub fn information_set_hash(&self) -> &InformationSetHashV1 {
        &self.information_set_hash
    }

    pub fn result(&self) -> &NeuralIsmctsResultV1 {
        &self.result
    }
}

pub fn analyze_player_view_neural_ismcts_v1(
    ruleset: Ruleset,
    observation: &Observation,
    visible_history: &[VisibleEvent],
    model: &PolicyValueModelV1,
    config: &NeuralIsmctsConfigV1,
) -> Result<PlayerViewNeuralIsmctsAnalysisV1, NeuralSearchError> {
    let information_set = build_information_set_v1(ruleset, observation, visible_history)
        .map_err(|error| NeuralSearchError::Belief(error.to_string()))?;
    let visible_history_hash = information_set.visible_history_hash().clone();
    let information_set_hash = information_set.information_set_hash().clone();
    let result = search_neural_ismcts_v1(&information_set, model, config)?;
    Ok(PlayerViewNeuralIsmctsAnalysisV1 {
        visible_history_hash,
        information_set_hash,
        result,
    })
}
