use splendor_catalog::{card, GemColor, CARD_COUNT, NOBLE_COUNT};
use splendor_core::{Action, Gems, Observation, Phase};

/// Frozen M12 player-view representation identity.
pub const REPRESENTATION_VERSION_V1: &str = "player-view-dense-v1";
pub const MAX_PLAYERS_V1: usize = 4;
pub const OBSERVATION_FEATURES_V1: usize = 368;
pub const ACTION_FEATURES_V1: usize = 36;

/// Encode only an [`Observation`]. Referee state, replay seed and hidden deck
/// identities cannot enter this API by construction.
pub fn encode_observation_v1(observation: &Observation) -> Vec<f32> {
    let mut out = Vec::with_capacity(OBSERVATION_FEATURES_V1);
    out.push(1.0);
    one_hot(&mut out, observation.viewer.index(), MAX_PLAYERS_V1);
    one_hot(
        &mut out,
        observation.public.player_count.saturating_sub(2) as usize,
        3,
    );
    let relative_current = relative_seat(
        observation.public.current_player.index(),
        observation.viewer.index(),
        observation.public.player_count as usize,
    );
    one_hot(&mut out, relative_current, MAX_PLAYERS_V1);
    one_hot(
        &mut out,
        match observation.public.phase {
            Phase::Main => 0,
            Phase::ChooseNoble => 1,
            Phase::GameOver => 2,
        },
        3,
    );
    push_gems(&mut out, observation.public.bank, 7.0);

    for tier in &observation.public.market {
        for card_id in tier {
            push_optional_card(&mut out, *card_id);
        }
    }
    for count in observation.public.deck_counts {
        out.push(f32::from(count) / 40.0);
    }
    push_id_multihot(
        &mut out,
        observation.public.nobles.iter().map(|id| id.index()),
        NOBLE_COUNT,
    );
    out.push(bool_feature(observation.public.end_game_triggered));
    match observation.public.turns_remaining_in_final_round {
        Some(turns) => {
            out.push(1.0);
            out.push(f32::from(turns) / 4.0);
        }
        None => {
            out.push(0.0);
            out.push(0.0);
        }
    }
    out.push(f32::from(observation.public.consecutive_forced_passes) / 4.0);
    push_id_multihot(
        &mut out,
        observation
            .public
            .pending_nobles
            .iter()
            .map(|id| id.index()),
        NOBLE_COUNT,
    );

    for seat in 0..MAX_PLAYERS_V1 {
        if let Some(player) = observation
            .public
            .players
            .iter()
            .find(|player| player.id.index() == seat)
        {
            out.push(1.0);
            one_hot(
                &mut out,
                relative_seat(
                    player.id.index(),
                    observation.viewer.index(),
                    observation.public.player_count as usize,
                ),
                MAX_PLAYERS_V1,
            );
            push_gems(&mut out, player.tokens, 10.0);
            for bonus in player.bonuses {
                out.push(f32::from(bonus) / 15.0);
            }
            out.push(f32::from(player.prestige) / 30.0);
            out.push(f32::from(player.reserved_count) / 3.0);
            out.push(player.public_reserved.len() as f32 / 3.0);
            push_card_aggregate(&mut out, player.public_reserved.iter().map(|id| id.index()));
            out.push(player.purchased.len() as f32 / CARD_COUNT as f32);
            out.push(player.nobles.len() as f32 / NOBLE_COUNT as f32);
        } else {
            out.extend(std::iter::repeat(0.0).take(32));
        }
    }

    for slot in 0..3 {
        if let Some(reserved) = observation.private.reserved.get(slot) {
            out.push(1.0);
            push_card_features(&mut out, reserved.card.index());
            one_hot(&mut out, reserved.tier.index(), 3);
            out.push(bool_feature(reserved.from_deck));
        } else {
            out.extend(std::iter::repeat(0.0).take(16));
        }
    }

    debug_assert_eq!(out.len(), OBSERVATION_FEATURES_V1);
    out
}

pub fn encode_action_v1(action: &Action) -> Vec<f32> {
    let mut out = vec![0.0; ACTION_FEATURES_V1];
    let (kind, take, give_back, tier, slot, noble) = match *action {
        Action::TakeTokens { take, give_back } => (0, take, give_back, None, None, None),
        Action::BuyMarket { tier, slot } => (
            1,
            Gems::ZERO,
            Gems::ZERO,
            Some(tier.index()),
            Some(slot as usize),
            None,
        ),
        Action::BuyReserved { slot } => {
            (2, Gems::ZERO, Gems::ZERO, None, Some(slot as usize), None)
        }
        Action::ReserveMarket {
            tier,
            slot,
            give_back,
        } => (
            3,
            Gems::ZERO,
            give_back,
            Some(tier.index()),
            Some(slot as usize),
            None,
        ),
        Action::ReserveDeck { tier, give_back } => {
            (4, Gems::ZERO, give_back, Some(tier.index()), None, None)
        }
        Action::ChooseNoble { noble } => {
            (5, Gems::ZERO, Gems::ZERO, None, None, Some(noble.index()))
        }
        Action::Pass => (6, Gems::ZERO, Gems::ZERO, None, None, None),
    };
    out[kind] = 1.0;
    write_gems(&mut out[7..13], take, 3.0);
    write_gems(&mut out[13..19], give_back, 10.0);
    if let Some(tier) = tier {
        out[19 + tier] = 1.0;
    }
    if let Some(slot) = slot {
        if slot < 4 {
            out[22 + slot] = 1.0;
        }
    }
    if let Some(noble) = noble {
        if noble < NOBLE_COUNT {
            out[26 + noble] = 1.0;
        }
    }
    out
}

fn relative_seat(seat: usize, viewer: usize, player_count: usize) -> usize {
    if player_count == 0 {
        0
    } else {
        (seat + player_count - viewer) % player_count
    }
}

fn one_hot(out: &mut Vec<f32>, index: usize, width: usize) {
    for position in 0..width {
        out.push(bool_feature(position == index));
    }
}

fn bool_feature(value: bool) -> f32 {
    if value {
        1.0
    } else {
        0.0
    }
}

fn push_gems(out: &mut Vec<f32>, gems: Gems, scale: f32) {
    let start = out.len();
    out.resize(start + 6, 0.0);
    write_gems(&mut out[start..], gems, scale);
}

fn write_gems(out: &mut [f32], gems: Gems, scale: f32) {
    let values = [
        gems.white, gems.blue, gems.green, gems.red, gems.black, gems.gold,
    ];
    for (target, value) in out.iter_mut().zip(values) {
        *target = f32::from(value) / scale;
    }
}

fn push_optional_card(out: &mut Vec<f32>, card_id: Option<splendor_catalog::CardId>) {
    match card_id {
        Some(id) => {
            out.push(1.0);
            push_card_features(out, id.index());
        }
        None => out.extend(std::iter::repeat(0.0).take(12)),
    }
}

/// Five bonus indicators, prestige, then five costs.
fn push_card_features(out: &mut Vec<f32>, card_index: usize) {
    let definition = card(splendor_catalog::CardId(card_index as u8));
    one_hot(out, definition.bonus.index(), GemColor::COUNT);
    out.push(f32::from(definition.prestige) / 5.0);
    for cost in definition.cost {
        out.push(f32::from(cost) / 7.0);
    }
}

fn push_card_aggregate(out: &mut Vec<f32>, cards: impl Iterator<Item = usize>) {
    let mut bonuses = [0u8; 5];
    let mut prestige = 0u16;
    let mut costs = [0u16; 5];
    for card_index in cards {
        let definition = card(splendor_catalog::CardId(card_index as u8));
        bonuses[definition.bonus.index()] = bonuses[definition.bonus.index()].saturating_add(1);
        prestige = prestige.saturating_add(u16::from(definition.prestige));
        for (target, cost) in costs.iter_mut().zip(definition.cost) {
            *target = target.saturating_add(u16::from(cost));
        }
    }
    for count in bonuses {
        out.push(f32::from(count) / 3.0);
    }
    out.push(prestige as f32 / 15.0);
    for cost in costs {
        out.push(cost as f32 / 21.0);
    }
}

fn push_id_multihot(out: &mut Vec<f32>, ids: impl Iterator<Item = usize>, width: usize) {
    let start = out.len();
    out.resize(start + width, 0.0);
    for id in ids {
        if id < width {
            out[start + id] = 1.0;
        }
    }
}

#[cfg(test)]
mod tests {
    use splendor_core::{FullState, GameConfig, PlayerId};

    use super::*;

    #[test]
    fn feature_shapes_are_frozen() {
        let (state, _) = FullState::new(GameConfig::default()).unwrap();
        let observation = state.observation(PlayerId(0));
        assert_eq!(
            encode_observation_v1(&observation).len(),
            OBSERVATION_FEATURES_V1
        );
        for action in state.legal_actions() {
            assert_eq!(encode_action_v1(&action).len(), ACTION_FEATURES_V1);
        }
    }

    #[test]
    fn opponent_blind_card_does_not_change_features() {
        let (mut left, _) = FullState::new(GameConfig {
            seed: 1234,
            ..Default::default()
        })
        .unwrap();
        let reserve = left
            .legal_actions()
            .into_iter()
            .find(|action| matches!(action, Action::ReserveDeck { .. }))
            .unwrap();
        left.apply(reserve).unwrap();
        let mut right = left.clone();
        let replacement = right.decks[0][0];
        let original = right.players[0].reserved[0].card;
        right.players[0].reserved[0].card = replacement;
        right.decks[0][0] = original;

        let left_features = encode_observation_v1(&left.observation(PlayerId(1)));
        let right_features = encode_observation_v1(&right.observation(PlayerId(1)));
        assert_eq!(left_features, right_features);
    }
}
