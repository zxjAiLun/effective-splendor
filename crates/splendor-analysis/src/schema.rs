use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use splendor_core::{
    Action, CardId, FullPlayerState, GemColor, NobleId, Observation, PlayerId, Tier,
};
use splendor_neural_search::{NeuralIsmctsConfigV1, NeuralIsmctsResultV1, NEURAL_VALUE_SCALE_V1};
use splendor_replay::ReplayGameResultV1;

use crate::AnalysisError;

pub const ANALYSIS_TRACE_FORMAT: &str = "effective-splendor-analysis-trace";
pub const ANALYSIS_TRACE_VERSION: u32 = 1;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AnalysisCardV1 {
    pub id: CardId,
    pub tier: Tier,
    pub bonus: GemColor,
    pub prestige: u8,
    pub cost: [u8; 5],
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AnalysisNobleV1 {
    pub id: NobleId,
    pub prestige: u8,
    pub requirements: [u8; 5],
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AnalysisCatalogV1 {
    pub cards: Vec<AnalysisCardV1>,
    pub nobles: Vec<AnalysisNobleV1>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RefereeRevealV1 {
    pub seed: u64,
    /// Remaining deck order, bottom to top; the final element is drawn next.
    pub decks: [Vec<CardId>; 3],
    /// Full player records, including every blind-reserved card identity.
    pub players: Vec<FullPlayerState>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AnalysisFrameV1 {
    pub ply: u32,
    pub state_hash_before: String,
    pub actor: PlayerId,
    pub recorded_action: Action,
    pub observation_hash: String,
    pub visible_event_count: u32,
    pub visible_history_hash: String,
    pub information_set_hash: String,
    /// Default-safe projection. The viewer must render this unless reveal is explicit.
    pub player_view: Observation,
    /// Referee-only post-game data. Never pass this field to an Agent/model.
    pub referee_reveal: RefereeRevealV1,
    pub legal_actions: Vec<Action>,
    pub neural_result: NeuralIsmctsResultV1,
    pub recommended_matches_recorded: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AnalysisTraceV1 {
    pub format: String,
    pub version: u32,
    pub engine_version: String,
    pub catalog_version: String,
    pub replay_version: u32,
    pub replay_document_hash: String,
    pub replay_final_state_hash: String,
    pub ruleset_fingerprint: String,
    pub player_count: u8,
    pub result: ReplayGameResultV1,
    pub analyzer_label: String,
    pub model_id: String,
    pub checkpoint_hash: String,
    pub value_scale: u32,
    pub config: NeuralIsmctsConfigV1,
    pub catalog: AnalysisCatalogV1,
    pub frames: Vec<AnalysisFrameV1>,
}

impl AnalysisTraceV1 {
    pub fn validate(&self) -> Result<(), AnalysisError> {
        if self.format != ANALYSIS_TRACE_FORMAT || self.version != ANALYSIS_TRACE_VERSION {
            return Err(invalid("unsupported format/version"));
        }
        if self.engine_version != splendor_core::ENGINE_VERSION
            || self.catalog_version != splendor_core::CATALOG_VERSION
            || self.replay_version != splendor_replay::REPLAY_VERSION
        {
            return Err(invalid("engine/catalog/replay version mismatch"));
        }
        if !(2..=4).contains(&self.player_count) || self.frames.is_empty() {
            return Err(invalid("player count or frame count is invalid"));
        }
        if self.result.scores.len() != self.player_count as usize
            || self.result.ranks.len() != self.player_count as usize
            || self
                .result
                .winners
                .iter()
                .any(|winner| usize::from(*winner) >= self.player_count as usize)
        {
            return Err(invalid("terminal result shape is invalid"));
        }
        for (label, hash) in [
            ("replay_document_hash", self.replay_document_hash.as_str()),
            (
                "replay_final_state_hash",
                self.replay_final_state_hash.as_str(),
            ),
            ("ruleset_fingerprint", self.ruleset_fingerprint.as_str()),
            ("checkpoint_hash", self.checkpoint_hash.as_str()),
        ] {
            validate_hash(label, hash)?;
        }
        if self.value_scale != NEURAL_VALUE_SCALE_V1
            || self.model_id.trim().is_empty()
            || self.analyzer_label.trim().is_empty()
            || self.config.expected_checkpoint_hash != self.checkpoint_hash
        {
            return Err(invalid("analyzer/model/value-scale binding is invalid"));
        }
        self.config
            .validate()
            .map_err(|error| invalid(error.to_string()))?;
        validate_catalog(&self.catalog)?;

        let seed = self.frames[0].referee_reveal.seed;
        for (index, frame) in self.frames.iter().enumerate() {
            if frame.ply != index as u32
                || frame.actor != frame.player_view.viewer
                || frame.actor.index() >= self.player_count as usize
                || frame.player_view.public.current_player != frame.actor
                || frame.player_view.public.player_count != self.player_count
                || frame.player_view.public.players.len() != self.player_count as usize
                || frame.referee_reveal.players.len() != self.player_count as usize
                || frame.referee_reveal.seed != seed
                || frame.player_view.ruleset_fingerprint.as_str() != self.ruleset_fingerprint
                || frame.visible_event_count == 0
            {
                return Err(invalid(format!("frame {index} identity/shape mismatch")));
            }
            if splendor_core::observation_hash(&frame.player_view).as_str()
                != frame.observation_hash
            {
                return Err(invalid(format!("frame {index} observation hash mismatch")));
            }
            validate_projection(
                &frame.player_view,
                &frame.referee_reveal,
                frame.actor,
                index,
            )?;
            validate_action(frame.recorded_action, index)?;
            validate_action(frame.neural_result.action, index)?;
            for action in &frame.legal_actions {
                validate_action(*action, index)?;
            }
            for (label, hash) in [
                ("state_hash_before", frame.state_hash_before.as_str()),
                ("observation_hash", frame.observation_hash.as_str()),
                ("visible_history_hash", frame.visible_history_hash.as_str()),
                ("information_set_hash", frame.information_set_hash.as_str()),
            ] {
                validate_hash(label, hash)?;
            }
            if frame.legal_actions.is_empty()
                || !frame.legal_actions.contains(&frame.recorded_action)
                || frame.neural_result.action_stats.len() != frame.legal_actions.len()
                || frame
                    .neural_result
                    .action_stats
                    .iter()
                    .map(|stats| stats.action)
                    .ne(frame.legal_actions.iter().copied())
                || !frame.legal_actions.contains(&frame.neural_result.action)
                || frame.neural_result.information_set_hash != frame.information_set_hash
                || frame.neural_result.model_id != self.model_id
                || frame.neural_result.checkpoint_hash != self.checkpoint_hash
                || frame.neural_result.stats.simulations != self.config.simulations
                || frame.neural_result.stats.sampled_determinizations != self.config.simulations
                || frame.neural_result.stats.root_visits != self.config.simulations
                || frame.recommended_matches_recorded
                    != (frame.neural_result.action == frame.recorded_action)
            {
                return Err(invalid(format!(
                    "frame {index} action/search binding mismatch"
                )));
            }
            let visit_sum = frame
                .neural_result
                .action_stats
                .iter()
                .try_fold(0u32, |sum, stats| sum.checked_add(stats.visits))
                .ok_or(AnalysisError::ArithmeticOverflow)?;
            if visit_sum != self.config.simulations {
                return Err(invalid(format!("frame {index} visit sum mismatch")));
            }
            for stats in &frame.neural_result.action_stats {
                if stats.prior_micros > self.value_scale
                    || stats.value_sum_by_player.len() != self.player_count as usize
                    || stats
                        .value_sum_by_player
                        .iter()
                        .any(|sum| *sum > u64::from(stats.visits) * u64::from(self.value_scale))
                {
                    return Err(invalid(format!("frame {index} edge stats invalid")));
                }
            }
        }
        Ok(())
    }
}

pub(crate) fn validate_projection(
    player_view: &Observation,
    referee_reveal: &RefereeRevealV1,
    actor: PlayerId,
    index: usize,
) -> Result<(), AnalysisError> {
    let mut card_zones = vec![false; splendor_catalog::CARD_COUNT];
    for tier in 0..3 {
        let count = u8::try_from(referee_reveal.decks[tier].len())
            .map_err(|_| invalid(format!("frame {index} deck count overflow")))?;
        if player_view.public.deck_counts[tier] != count {
            return Err(invalid(format!("frame {index} deck projection mismatch")));
        }
        for card in player_view.public.market[tier].iter().flatten() {
            validate_card(*card, Some(tier), index, &mut card_zones)?;
        }
        for card in &referee_reveal.decks[tier] {
            validate_card(*card, Some(tier), index, &mut card_zones)?;
        }
    }
    for noble in player_view
        .public
        .nobles
        .iter()
        .chain(&player_view.public.pending_nobles)
    {
        validate_noble(*noble, index)?;
    }
    for (seat, (public, full)) in player_view
        .public
        .players
        .iter()
        .zip(&referee_reveal.players)
        .enumerate()
    {
        for card in &public.public_reserved {
            validate_card_domain(*card, index)?;
        }
        for card in &public.purchased {
            validate_card_domain(*card, index)?;
        }
        for noble in &public.nobles {
            validate_noble(*noble, index)?;
        }
        for reserved in &full.reserved {
            validate_card(reserved.card, None, index, &mut card_zones)?;
        }
        for card in &full.purchased {
            validate_card(*card, None, index, &mut card_zones)?;
        }
        for noble in &full.nobles {
            validate_noble(*noble, index)?;
        }
        let public_reserved = full
            .reserved
            .iter()
            .filter(|reserved| !reserved.from_deck)
            .map(|reserved| reserved.card)
            .collect::<Vec<_>>();
        if public.id.index() != seat
            || full.id != public.id
            || full.tokens != public.tokens
            || full.bonuses != public.bonuses
            || full.prestige != public.prestige
            || full.purchased != public.purchased
            || full.nobles != public.nobles
            || full.reserved.len() != public.reserved_count as usize
            || public_reserved != public.public_reserved
        {
            return Err(invalid(format!(
                "frame {index} public player projection mismatch"
            )));
        }
        if public.id == actor {
            if player_view.private.reserved.len() != full.reserved.len() {
                return Err(invalid(format!(
                    "frame {index} private reserve count mismatch"
                )));
            }
            for (slot, (private, reserved)) in player_view
                .private
                .reserved
                .iter()
                .zip(&full.reserved)
                .enumerate()
            {
                if reserved.card.index() >= splendor_catalog::CARD_COUNT
                    || private.slot as usize != slot
                    || private.card != reserved.card
                    || private.from_deck != reserved.from_deck
                    || private.tier != splendor_catalog::card(reserved.card).tier
                {
                    return Err(invalid(format!("frame {index} private reserve mismatch")));
                }
            }
        }
    }
    if card_zones.iter().any(|present| !present) {
        return Err(invalid(format!(
            "frame {index} card zones do not partition the frozen catalog"
        )));
    }
    Ok(())
}

pub(crate) fn validate_card(
    card: CardId,
    expected_tier: Option<usize>,
    index: usize,
    zones: &mut [bool],
) -> Result<(), AnalysisError> {
    validate_card_domain(card, index)?;
    let card_index = card.index();
    if expected_tier.is_some_and(|tier| splendor_catalog::card(card).tier.index() != tier) {
        return Err(invalid(format!("frame {index} card tier mismatch")));
    }
    if zones[card_index] {
        return Err(invalid(format!("frame {index} duplicate card zone")));
    }
    zones[card_index] = true;
    Ok(())
}

pub(crate) fn validate_card_domain(card: CardId, index: usize) -> Result<(), AnalysisError> {
    if card.index() >= splendor_catalog::CARD_COUNT {
        return Err(invalid(format!("frame {index} card id out of range")));
    }
    Ok(())
}

pub(crate) fn validate_noble(noble: NobleId, index: usize) -> Result<(), AnalysisError> {
    if noble.index() >= splendor_catalog::NOBLE_COUNT {
        return Err(invalid(format!("frame {index} noble id out of range")));
    }
    Ok(())
}

pub(crate) fn validate_action(action: Action, index: usize) -> Result<(), AnalysisError> {
    match action {
        Action::BuyMarket { slot, .. } | Action::ReserveMarket { slot, .. } if slot >= 4 => {
            Err(invalid(format!("frame {index} market slot out of range")))
        }
        Action::ChooseNoble { noble } => validate_noble(noble, index),
        _ => Ok(()),
    }
}

pub fn analysis_trace_hash_v1(trace: &AnalysisTraceV1) -> Result<String, AnalysisError> {
    trace.validate()?;
    let json = serde_json::to_vec(trace)
        .map_err(|error| AnalysisError::Serialization(error.to_string()))?;
    let mut hasher = Sha256::new();
    hasher.update(b"effective-splendor-analysis-trace-v1\0");
    hasher.update(json);
    Ok(hex::encode(hasher.finalize()))
}

pub(crate) fn validate_catalog(catalog: &AnalysisCatalogV1) -> Result<(), AnalysisError> {
    let cards_match =
        catalog
            .cards
            .iter()
            .zip(splendor_catalog::all_cards())
            .all(|(actual, expected)| {
                actual.id == expected.id
                    && actual.tier == expected.tier
                    && actual.bonus == expected.bonus
                    && actual.prestige == expected.prestige
                    && actual.cost == expected.cost
            });
    let nobles_match = catalog
        .nobles
        .iter()
        .zip(splendor_catalog::all_nobles())
        .all(|(actual, expected)| {
            actual.id == expected.id
                && actual.prestige == expected.prestige
                && actual.requirements == expected.requirements
        });
    if catalog.cards.len() != splendor_catalog::CARD_COUNT
        || catalog.nobles.len() != splendor_catalog::NOBLE_COUNT
        || !cards_match
        || !nobles_match
    {
        return Err(invalid("catalog is not the frozen dense catalog"));
    }
    Ok(())
}

pub(crate) fn validate_hash(label: &str, hash: &str) -> Result<(), AnalysisError> {
    if hash.len() != 64
        || !hash
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        return Err(invalid(format!("{label} is not lowercase SHA-256")));
    }
    Ok(())
}

pub(crate) fn invalid(message: impl Into<String>) -> AnalysisError {
    AnalysisError::InvalidTrace(message.into())
}
