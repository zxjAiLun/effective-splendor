use splendor_catalog::{card, CardId, GemColor, NobleId, CARD_COUNT, NOBLE_COUNT};
use splendor_core::{Action, Gems, Observation, Phase};

use crate::error::invalid_dataset;
use crate::LearningError;

/// Frozen M12 player-view representation identity.
pub const REPRESENTATION_VERSION_V1: &str = "player-view-dense-v1";
pub const MAX_PLAYERS_V1: usize = 4;
pub const OBSERVATION_FEATURES_V1: usize = 368;
pub const ACTION_FEATURES_V1: usize = 36;

/// Encode only an [`Observation`]. Referee state, replay seed and hidden deck
/// identities cannot enter this API by construction.
pub fn encode_observation_v1(observation: &Observation) -> Result<Vec<f32>, LearningError> {
    validate_observation_v1(observation)?;
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
    Ok(out)
}

pub fn encode_action_v1(action: &Action) -> Result<Vec<f32>, LearningError> {
    validate_action_v1(action)?;
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
    Ok(out)
}

/// Frozen M25/M49A deterministic action delta feature count.
pub const ACTION_DELTA_FEATURES_V2: usize = 23;
/// Combined input dimension for M49A Q-network (368 + 36 + 23 = 427).
pub const COMBINED_FEATURES_V1: usize =
    OBSERVATION_FEATURES_V1 + ACTION_FEATURES_V1 + ACTION_DELTA_FEATURES_V2;

/// Exact post-action state delta encoding matching Splendor engine rules and Python M25 parity.
///
/// Computes 23 exact deterministic features without peeking at hidden deck cards:
/// - [0]: delta_vp (VP change / 5.0)
/// - [1]: post_vp (new VP / 15.0)
/// - [2]: dist_15 (max(0, 15 - new VP) / 15.0)
/// - [3..8]: delta_bonuses (5 gem colors [W, B, G, R, K], 1.0 if bought card has that bonus)
/// - [8..14]: delta_tokens (6 gem colors [W, B, G, R, K, Gold], net change / 10.0)
/// - [14]: post_tokens (total tokens / 10.0)
/// - [15..20]: card_cost (5 gem colors [W, B, G, R, K], cost / 7.0)
/// - [20]: card_prestige (card prestige / 5.0)
/// - [21]: gold_spent (gold tokens paid / 5.0)
/// - [22]: noble_delta (1.0 if 1 or >1 noble qualifies; 0.0 otherwise)
pub fn encode_action_delta_v2(
    observation: &Observation,
    action: &Action,
) -> Result<[f32; ACTION_DELTA_FEATURES_V2], LearningError> {
    validate_observation_v1(observation)?;
    validate_action_v1(action)?;

    let viewer = observation.viewer.index();
    let player = &observation.public.players[viewer];
    let tokens = [
        player.tokens.white,
        player.tokens.blue,
        player.tokens.green,
        player.tokens.red,
        player.tokens.black,
        player.tokens.gold,
    ];
    let bonuses = player.bonuses;
    let prestige = player.prestige;

    let mut delta_vp = 0.0f32;
    let mut delta_bonuses = [0.0f32; 5];
    let mut delta_tokens = [0.0f32; 6];
    let mut card_cost = [0.0f32; 5];
    let mut card_prestige = 0.0f32;
    let mut gold_spent = 0.0f32;
    let mut noble_delta = 0.0f32;

    match *action {
        Action::TakeTokens { take, give_back } => {
            let take_arr = [
                take.white, take.blue, take.green, take.red, take.black, take.gold,
            ];
            let give_arr = [
                give_back.white,
                give_back.blue,
                give_back.green,
                give_back.red,
                give_back.black,
                give_back.gold,
            ];
            for i in 0..6 {
                delta_tokens[i] = (take_arr[i] as f32 - give_arr[i] as f32) / 10.0;
            }
        }
        Action::BuyMarket { tier, slot } => {
            let slot_idx = slot as usize;
            if slot_idx < 4 {
                if let Some(card_id) = observation.public.market[tier.index()][slot_idx] {
                    compute_buy_delta(
                        card_id,
                        bonuses,
                        tokens,
                        &observation.public.nobles,
                        &mut delta_vp,
                        &mut delta_bonuses,
                        &mut delta_tokens,
                        &mut card_cost,
                        &mut card_prestige,
                        &mut gold_spent,
                        &mut noble_delta,
                    );
                }
            }
        }
        Action::BuyReserved { slot } => {
            let slot_idx = slot as usize;
            let reserved = &observation.private.reserved;
            if slot_idx < reserved.len() {
                let card_id = reserved[slot_idx].card;
                compute_buy_delta(
                    card_id,
                    bonuses,
                    tokens,
                    &observation.public.nobles,
                    &mut delta_vp,
                    &mut delta_bonuses,
                    &mut delta_tokens,
                    &mut card_cost,
                    &mut card_prestige,
                    &mut gold_spent,
                    &mut noble_delta,
                );
            }
        }
        Action::ReserveMarket {
            tier,
            slot,
            give_back,
        } => {
            let slot_idx = slot as usize;
            if slot_idx < 4 {
                if let Some(card_id) = observation.public.market[tier.index()][slot_idx] {
                    let card_def = card(card_id);
                    card_prestige = card_def.prestige as f32 / 5.0;
                    for i in 0..5 {
                        card_cost[i] = card_def.cost[i] as f32 / 7.0;
                    }
                }
            }
            let gold_taken = if observation.public.bank.gold > 0 { 1u8 } else { 0u8 };
            let give_arr = [
                give_back.white,
                give_back.blue,
                give_back.green,
                give_back.red,
                give_back.black,
                give_back.gold,
            ];
            for i in 0..5 {
                delta_tokens[i] = -(give_arr[i] as f32) / 10.0;
            }
            delta_tokens[5] = (gold_taken as f32 - give_arr[5] as f32) / 10.0;
        }
        Action::ReserveDeck {
            tier: _,
            give_back,
        } => {
            let gold_taken = if observation.public.bank.gold > 0 { 1u8 } else { 0u8 };
            let give_arr = [
                give_back.white,
                give_back.blue,
                give_back.green,
                give_back.red,
                give_back.black,
                give_back.gold,
            ];
            for i in 0..5 {
                delta_tokens[i] = -(give_arr[i] as f32) / 10.0;
            }
            delta_tokens[5] = (gold_taken as f32 - give_arr[5] as f32) / 10.0;
        }
        Action::ChooseNoble { .. } => {
            delta_vp = 3.0 / 5.0;
            noble_delta = 1.0;
        }
        Action::Pass => {}
    }

    let new_vp = prestige as f32 + delta_vp * 5.0;
    let post_vp = new_vp / 15.0;
    let dist_15 = (15.0 - new_vp).max(0.0) / 15.0;
    let token_sum: f32 = tokens.iter().map(|&t| t as f32).sum();
    let delta_token_sum: f32 = delta_tokens.iter().sum();
    let post_tokens = (token_sum + delta_token_sum * 10.0) / 10.0;

    let mut out = [0.0f32; ACTION_DELTA_FEATURES_V2];
    out[0] = delta_vp;
    out[1] = post_vp;
    out[2] = dist_15;
    out[3..8].copy_from_slice(&delta_bonuses);
    out[8..14].copy_from_slice(&delta_tokens);
    out[14] = post_tokens;
    out[15..20].copy_from_slice(&card_cost);
    out[20] = card_prestige;
    out[21] = gold_spent;
    out[22] = noble_delta;

    Ok(out)
}

fn compute_buy_delta(
    card_id: CardId,
    bonuses: [u8; 5],
    tokens: [u8; 6],
    visible_nobles: &[NobleId],
    delta_vp: &mut f32,
    delta_bonuses: &mut [f32; 5],
    delta_tokens: &mut [f32; 6],
    card_cost: &mut [f32; 5],
    card_prestige: &mut f32,
    gold_spent: &mut f32,
    noble_delta: &mut f32,
) {
    let c = card(card_id);
    *card_prestige = c.prestige as f32 / 5.0;
    *delta_vp = c.prestige as f32 / 5.0;
    let color_idx = c.bonus.index();
    delta_bonuses[color_idx] = 1.0;
    for i in 0..5 {
        card_cost[i] = c.cost[i] as f32 / 7.0;
    }

    let mut total_gold_paid: u8 = 0;
    for i in 0..5 {
        let needed = c.cost[i].saturating_sub(bonuses[i]);
        let paid = tokens[i].min(needed);
        let deficit = needed - paid;
        total_gold_paid = total_gold_paid.saturating_add(deficit);
        delta_tokens[i] = -(paid as f32) / 10.0;
    }
    delta_tokens[5] = -(total_gold_paid as f32) / 10.0;
    *gold_spent = total_gold_paid as f32 / 5.0;

    // Check post-purchase qualifying nobles matching engine after_purchase() semantics:
    // Any noble on the board whose requirements are satisfied by the player's post-purchase bonuses
    // is qualified, including nobles whose requirements were already satisfied prior to this purchase
    // (e.g. from an earlier turn where multiple nobles qualified and only one was chosen).
    let mut new_bonuses = bonuses;
    new_bonuses[color_idx] = new_bonuses[color_idx].saturating_add(1);

    let all_n = splendor_catalog::all_nobles();
    let mut qualifying_nobles: Vec<&splendor_catalog::NobleDef> = Vec::new();
    for &nid in visible_nobles {
        if nid.index() < all_n.len() {
            let n = &all_n[nid.index()];
            let post_met = (0..5).all(|c_idx| new_bonuses[c_idx] >= n.requirements[c_idx]);
            if post_met {
                qualifying_nobles.push(n);
            }
        }
    }

    if qualifying_nobles.len() == 1 {
        let noble_prestige = qualifying_nobles[0].prestige as f32;
        *delta_vp += noble_prestige / 5.0;
        *noble_delta = 1.0;
    } else if qualifying_nobles.len() > 1 {
        *noble_delta = 1.0;
    }
}

/// Encode an observation and an action into the combined 427-dimensional feature vector.
///
/// Order: `[encode_observation_v1 (368), encode_action_v1 (36), encode_action_delta_v2 (23)]` = 427 features.
pub fn encode_combined_v1(
    observation: &Observation,
    action: &Action,
) -> Result<Vec<f32>, LearningError> {
    let obs_f = encode_observation_v1(observation)?;
    let act_f = encode_action_v1(action)?;
    let delta_f = encode_action_delta_v2(observation, action)?;
    let mut out = Vec::with_capacity(COMBINED_FEATURES_V1);
    out.extend_from_slice(&obs_f);
    out.extend_from_slice(&act_f);
    out.extend_from_slice(&delta_f);
    debug_assert_eq!(out.len(), COMBINED_FEATURES_V1);
    Ok(out)
}

fn validate_observation_v1(observation: &Observation) -> Result<(), LearningError> {
    let player_count = observation.public.player_count as usize;
    if !(2..=MAX_PLAYERS_V1).contains(&player_count)
        || observation.viewer.index() >= player_count
        || observation.public.current_player.index() >= player_count
        || observation.public.players.len() != player_count
    {
        return Err(invalid_dataset(
            "observation has an invalid player/viewer shape",
        ));
    }
    for (expected_seat, player) in observation.public.players.iter().enumerate() {
        if player.id.index() != expected_seat
            || player.reserved_count > 3
            || player.public_reserved.len() > player.reserved_count as usize
        {
            return Err(invalid_dataset(
                "observation has an invalid public player shape",
            ));
        }
        validate_card_ids(player.public_reserved.iter().copied())?;
        validate_card_ids(player.purchased.iter().copied())?;
        validate_noble_ids(player.nobles.iter().copied())?;
    }
    for (tier_index, tier) in observation.public.market.iter().enumerate() {
        for card_id in tier.iter().flatten() {
            validate_card_id(*card_id)?;
            if card(*card_id).tier.index() != tier_index {
                return Err(invalid_dataset(
                    "observation market card does not match its tier",
                ));
            }
        }
    }
    validate_noble_ids(observation.public.nobles.iter().copied())?;
    validate_noble_ids(observation.public.pending_nobles.iter().copied())?;
    if observation.private.reserved.len() > 3 {
        return Err(invalid_dataset(
            "observation has more than three private reserved cards",
        ));
    }
    let viewer = &observation.public.players[observation.viewer.index()];
    if viewer.reserved_count as usize != observation.private.reserved.len() {
        return Err(invalid_dataset(
            "private reserved cards do not match the viewer's public count",
        ));
    }
    for (expected_slot, reserved) in observation.private.reserved.iter().enumerate() {
        validate_card_id(reserved.card)?;
        if reserved.slot as usize != expected_slot || card(reserved.card).tier != reserved.tier {
            return Err(invalid_dataset(
                "private reserved card has an invalid slot or tier",
            ));
        }
    }
    Ok(())
}

fn validate_action_v1(action: &Action) -> Result<(), LearningError> {
    match *action {
        Action::TakeTokens { take, give_back } => {
            let colors = [take.white, take.blue, take.green, take.red, take.black];
            let non_zero = colors.iter().filter(|value| **value != 0).count();
            let total = colors.iter().map(|value| u16::from(*value)).sum::<u16>();
            let valid_take = take.gold == 0
                && ((non_zero == 1 && total == 2)
                    || ((1..=3).contains(&non_zero)
                        && total == non_zero as u16
                        && colors.iter().all(|value| *value <= 1)));
            if !valid_take || gems_total(give_back) > 3 {
                return Err(invalid_dataset(
                    "take_tokens action has an invalid token payload",
                ));
            }
        }
        Action::BuyMarket { slot, .. } | Action::ReserveMarket { slot, .. } if slot >= 4 => {
            return Err(invalid_dataset("market action slot is out of range"));
        }
        Action::BuyReserved { slot } if slot >= 3 => {
            return Err(invalid_dataset("reserved action slot is out of range"));
        }
        Action::ReserveMarket { give_back, .. } | Action::ReserveDeck { give_back, .. }
            if gems_total(give_back) > 1 =>
        {
            return Err(invalid_dataset(
                "reserve action has an invalid token return payload",
            ));
        }
        Action::ChooseNoble { noble } => validate_noble_id(noble)?,
        _ => {}
    }
    Ok(())
}

fn validate_card_ids(ids: impl Iterator<Item = CardId>) -> Result<(), LearningError> {
    for id in ids {
        validate_card_id(id)?;
    }
    Ok(())
}

fn validate_card_id(id: CardId) -> Result<(), LearningError> {
    if id.index() >= CARD_COUNT {
        return Err(invalid_dataset(format!(
            "card id {} is outside the catalog",
            id.index()
        )));
    }
    Ok(())
}

fn validate_noble_ids(ids: impl Iterator<Item = NobleId>) -> Result<(), LearningError> {
    for id in ids {
        validate_noble_id(id)?;
    }
    Ok(())
}

fn validate_noble_id(id: NobleId) -> Result<(), LearningError> {
    if id.index() >= NOBLE_COUNT {
        return Err(invalid_dataset(format!(
            "noble id {} is outside the catalog",
            id.index()
        )));
    }
    Ok(())
}

fn gems_total(gems: Gems) -> u16 {
    [
        gems.white, gems.blue, gems.green, gems.red, gems.black, gems.gold,
    ]
    .iter()
    .map(|value| u16::from(*value))
    .sum()
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
            encode_observation_v1(&observation).unwrap().len(),
            OBSERVATION_FEATURES_V1
        );
        for action in state.legal_actions() {
            assert_eq!(encode_action_v1(&action).unwrap().len(), ACTION_FEATURES_V1);
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

        let left_features = encode_observation_v1(&left.observation(PlayerId(1))).unwrap();
        let right_features = encode_observation_v1(&right.observation(PlayerId(1))).unwrap();
        assert_eq!(left_features, right_features);
    }

    #[test]
    fn malformed_catalog_ids_and_action_slots_are_rejected() {
        let (state, _) = FullState::new(GameConfig::default()).unwrap();
        let mut observation = state.observation(PlayerId(0));
        observation.public.market[0][0] = Some(CardId(255));
        assert!(matches!(
            encode_observation_v1(&observation),
            Err(LearningError::InvalidDataset(_))
        ));

        assert!(matches!(
            encode_action_v1(&Action::BuyReserved { slot: 3 }),
            Err(LearningError::InvalidDataset(_))
        ));
        assert!(matches!(
            encode_action_v1(&Action::ChooseNoble {
                noble: NobleId(255)
            }),
            Err(LearningError::InvalidDataset(_))
        ));
    }

    fn make_test_observation() -> Observation {
        Observation {
            viewer: PlayerId(0),
            ruleset_fingerprint: splendor_core::ruleset_fingerprint(
                &splendor_core::Ruleset::base_v1(),
            ),
            public: splendor_core::PublicState {
                player_count: 2,
                current_player: PlayerId(0),
                phase: splendor_core::Phase::Main,
                bank: Gems {
                    white: 4,
                    blue: 4,
                    green: 4,
                    red: 4,
                    black: 4,
                    gold: 5,
                },
                market: [
                    [
                        Some(CardId(0)),
                        Some(CardId(1)),
                        Some(CardId(2)),
                        Some(CardId(3)),
                    ],
                    [
                        Some(CardId(40)),
                        Some(CardId(41)),
                        Some(CardId(42)),
                        Some(CardId(43)),
                    ],
                    [
                        Some(CardId(70)),
                        Some(CardId(71)),
                        Some(CardId(72)),
                        Some(CardId(73)),
                    ],
                ],
                deck_counts: [36, 26, 16],
                nobles: vec![NobleId(0), NobleId(1), NobleId(2)],
                players: vec![
                    splendor_core::PublicPlayerView {
                        id: PlayerId(0),
                        tokens: Gems {
                            white: 2,
                            blue: 1,
                            green: 0,
                            red: 3,
                            black: 0,
                            gold: 1,
                        },
                        bonuses: [1, 2, 0, 0, 1],
                        prestige: 4,
                        reserved_count: 1,
                        public_reserved: vec![CardId(4)],
                        purchased: vec![],
                        nobles: vec![],
                    },
                    splendor_core::PublicPlayerView {
                        id: PlayerId(1),
                        tokens: Gems::ZERO,
                        bonuses: [0, 0, 0, 0, 0],
                        prestige: 0,
                        reserved_count: 0,
                        public_reserved: vec![],
                        purchased: vec![],
                        nobles: vec![],
                    },
                ],
                end_game_triggered: false,
                turns_remaining_in_final_round: None,
                consecutive_forced_passes: 0,
                pending_nobles: vec![],
            },
            private: splendor_core::PrivatePlayerView {
                reserved: vec![splendor_core::ReservedView {
                    slot: 0,
                    card: CardId(4),
                    tier: splendor_catalog::Tier::One,
                    from_deck: false,
                }],
            },
        }
    }

    fn assert_approx_eq(actual: &[f32], expected: &[f32]) {
        assert_eq!(actual.len(), expected.len());
        for (i, (&a, &e)) in actual.iter().zip(expected.iter()).enumerate() {
            assert!(
                (a - e).abs() < 1e-5,
                "mismatch at index {i}: actual {a}, expected {e}"
            );
        }
    }

    #[test]
    fn test_python_rust_action_delta_parity_all_action_types() {
        let fixture_str = include_str!("../tests/fixtures/m49a_delta_parity_v1.json");
        let fixture_json: serde_json::Value =
            serde_json::from_str(fixture_str).expect("valid fixture json");
        let cases = fixture_json["cases"].as_array().expect("cases array");

        for c in cases {
            let id = c["id"].as_str().unwrap();
            let obs: Observation = serde_json::from_value(c["observation"].clone()).unwrap();
            let act: Action = serde_json::from_value(c["action"].clone()).unwrap();
            let expected_delta: Vec<f32> = c["expected_delta_23"]
                .as_array()
                .unwrap()
                .iter()
                .map(|v| v.as_f64().unwrap() as f32)
                .collect();

            let actual = encode_action_delta_v2(&obs, &act)
                .unwrap_or_else(|e| panic!("failed encoding action for {id}: {e}"));

            assert_eq!(actual.len(), 23);
            for (i, (&a, &e)) in actual.iter().zip(expected_delta.iter()).enumerate() {
                assert!(
                    (a - e).abs() < 1e-5,
                    "cross-language parity mismatch for case '{id}' at index {i}: actual {a}, expected {e}"
                );
            }
        }

        // Test combined vector (368 + 36 + 23 = 427)
        let obs = make_test_observation();
        let act_buy_m = Action::BuyMarket {
            tier: splendor_catalog::Tier::One,
            slot: 0,
        };
        let delta_buy_m = encode_action_delta_v2(&obs, &act_buy_m).unwrap();
        let combined = encode_combined_v1(&obs, &act_buy_m).unwrap();
        assert_eq!(combined.len(), COMBINED_FEATURES_V1);
        assert_eq!(combined.len(), 427);
        assert_approx_eq(
            &combined[..OBSERVATION_FEATURES_V1],
            &encode_observation_v1(&obs).unwrap(),
        );
        assert_approx_eq(
            &combined[OBSERVATION_FEATURES_V1..OBSERVATION_FEATURES_V1 + ACTION_FEATURES_V1],
            &encode_action_v1(&act_buy_m).unwrap(),
        );
        assert_approx_eq(
            &combined[OBSERVATION_FEATURES_V1 + ACTION_FEATURES_V1..],
            &delta_buy_m,
        );
    }
}
