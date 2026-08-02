use splendor_catalog::{card, cards_for_tier, CardId, Tier, CARD_COUNT};
use splendor_core::{
    ruleset_fingerprint, Observation, PlayerId, Ruleset, Visibility, VisibleEvent,
};

use crate::error::BeliefError;
use crate::hash::{information_set_hash_v1, visible_history_hash_v1};
use crate::model::{InformationSetV1, PlayerReservedKnowledgeV1, ReservedKnowledgeV1};

/// Build a validated information set for the viewer of `observation`, using
/// only the purely visible inputs.
///
/// - `visible_history` must be the cumulative player-visible transcript from
///   game start (starting with `VisibleEvent::GameStarted`), produced for the
///   same viewer as `observation`.
/// - Neither input is mutated.
///
/// `FullState`, `RefereeEvent`, raw seeds, deck order and other players'
/// blind-reserved `CardId`s must never reach this function.
pub fn build_information_set_v1(
    ruleset: Ruleset,
    observation: &Observation,
    visible_history: &[VisibleEvent],
) -> Result<InformationSetV1, BeliefError> {
    validate_observation(ruleset, observation)?;

    let mut tracker = Tracker::new(observation.viewer, observation.public.player_count as usize);
    tracker.run(visible_history, observation, &ruleset)?;
    tracker.check_against_observation(observation)?;

    let (_known_cards, unseen_cards_by_tier) = compute_partition(observation, &tracker)?;

    let visible_history_hash = visible_history_hash_v1(visible_history)?;
    let information_set_hash = information_set_hash_v1(observation, &visible_history_hash);

    let reserved_knowledge = tracker
        .slots
        .iter()
        .enumerate()
        .map(|(i, slots)| PlayerReservedKnowledgeV1 {
            player: PlayerId(i as u8),
            slots: slots.clone(),
        })
        .collect();

    Ok(InformationSetV1::new(
        ruleset,
        observation.clone(),
        visible_history_hash,
        information_set_hash,
        reserved_knowledge,
        unseen_cards_by_tier,
    ))
}

/// Observation-side structural validation, independent of the history.
fn validate_observation(ruleset: Ruleset, observation: &Observation) -> Result<(), BeliefError> {
    let public = &observation.public;
    if observation.viewer.index() >= public.player_count as usize {
        return Err(BeliefError::ViewerOutOfRange {
            viewer: observation.viewer,
            player_count: public.player_count,
        });
    }
    if public.player_count as usize != public.players.len() {
        return Err(BeliefError::MalformedObservation(format!(
            "player_count {} != players.len() {}",
            public.player_count,
            public.players.len()
        )));
    }
    for (i, player) in public.players.iter().enumerate() {
        if player.id != PlayerId(i as u8) {
            return Err(BeliefError::MalformedObservation(format!(
                "player ids are not contiguous with their index: {:?} at index {i}",
                player.id
            )));
        }
    }
    if ruleset_fingerprint(&ruleset) != observation.ruleset_fingerprint {
        return Err(BeliefError::RulesetFingerprintMismatch);
    }
    for tier in Tier::ALL {
        let total = cards_for_tier(tier).len();
        let deck_count = public.deck_counts[tier.index()] as usize;
        if deck_count > total {
            return Err(BeliefError::CardAccountingMismatch {
                tier,
                expected: total,
                found: deck_count,
            });
        }
    }
    Ok(())
}

/// Reconstructed reserved-slot vectors, one per player index.
struct Tracker {
    viewer: PlayerId,
    player_count: usize,
    max_reserved: usize,
    slots: Vec<Vec<ReservedKnowledgeV1>>,
}

impl Tracker {
    fn new(viewer: PlayerId, player_count: usize) -> Self {
        Self {
            viewer,
            player_count,
            max_reserved: 3,
            slots: vec![Vec::new(); player_count],
        }
    }

    fn run(
        &mut self,
        events: &[VisibleEvent],
        observation: &Observation,
        ruleset: &Ruleset,
    ) -> Result<(), BeliefError> {
        let mut iter = events.iter().enumerate();
        let Some((index, first_event)) = iter.next() else {
            return Err(BeliefError::MalformedHistory {
                index: 0,
                reason: "visible history is empty; must start with GameStarted".to_string(),
            });
        };
        let VisibleEvent::GameStarted {
            player_count,
            ruleset: ruleset_id,
        } = first_event
        else {
            return Err(BeliefError::MalformedHistory {
                index: 0,
                reason: "visible history must start with GameStarted".to_string(),
            });
        };
        if *player_count != observation.public.player_count {
            return Err(BeliefError::MalformedHistory {
                index,
                reason: format!(
                    "GameStarted player_count {player_count} != observation player_count {}",
                    observation.public.player_count
                ),
            });
        }
        if ruleset_id.as_str() != ruleset.id.0 {
            return Err(BeliefError::MalformedHistory {
                index,
                reason: format!(
                    "GameStarted ruleset {ruleset_id:?} != ruleset id {:?}",
                    ruleset.id.0
                ),
            });
        }
        for (index, event) in iter {
            match event {
                VisibleEvent::CardReserved {
                    player,
                    card,
                    from,
                    public_identity,
                    visible_to,
                    ..
                } => {
                    let json = serde_json::to_value(from)
                        .map_err(|e| BeliefError::Serialization(e.to_string()))?;
                    let source = decode_reserve_source(json, index)?;
                    self.handle_reserve(
                        index,
                        *player,
                        *card,
                        source,
                        *public_identity,
                        *visible_to,
                    )?;
                }
                VisibleEvent::CardPurchased {
                    player, card, from, ..
                } => {
                    let json = serde_json::to_value(from)
                        .map_err(|e| BeliefError::Serialization(e.to_string()))?;
                    let source = decode_purchase_source(json, index)?;
                    self.handle_purchase(index, *player, *card, source)?;
                }
                VisibleEvent::ChanceRevealed {
                    tier,
                    slot,
                    card,
                    visible_to,
                } => {
                    self.handle_chance_reveal(index, *tier, *slot, *card, *visible_to)?;
                }
                _ => {}
            }
        }
        Ok(())
    }

    fn handle_reserve(
        &mut self,
        index: usize,
        player: PlayerId,
        card: Option<CardId>,
        from: ReserveSourceInfo,
        public_identity: bool,
        _visible_to: Visibility,
    ) -> Result<(), BeliefError> {
        self.check_player(index, player)?;
        let slots = &mut self.slots[player.index()];
        match from {
            ReserveSourceInfo::Market { tier, .. } => {
                let Some(card) = card else {
                    return Err(BeliefError::MalformedHistory {
                        index,
                        reason: "market reserve must carry the public card identity".to_string(),
                    });
                };
                if !public_identity {
                    return Err(BeliefError::MalformedHistory {
                        index,
                        reason: "market reserve must be public".to_string(),
                    });
                }
                validate_card_tier(index, card, tier, "market reserve")?;
                slots.push(ReservedKnowledgeV1::Known {
                    card,
                    from_deck: false,
                });
            }
            ReserveSourceInfo::Deck { tier } => {
                if player == self.viewer {
                    let Some(card) = card else {
                        return Err(BeliefError::MalformedHistory {
                            index,
                            reason: "viewer blind reserve must carry the card identity".to_string(),
                        });
                    };
                    if public_identity {
                        return Err(BeliefError::MalformedHistory {
                            index,
                            reason: "deck reserve cannot be public".to_string(),
                        });
                    }
                    validate_card_tier(index, card, tier, "viewer deck reserve")?;
                    slots.push(ReservedKnowledgeV1::Known {
                        card,
                        from_deck: true,
                    });
                } else {
                    if card.is_some() {
                        return Err(BeliefError::HiddenInformationLeak { index });
                    }
                    if public_identity {
                        return Err(BeliefError::MalformedHistory {
                            index,
                            reason: "deck reserve cannot be public".to_string(),
                        });
                    }
                    slots.push(ReservedKnowledgeV1::HiddenDeck { tier });
                }
            }
        }
        if slots.len() > self.max_reserved {
            return Err(BeliefError::MalformedHistory {
                index,
                reason: format!(
                    "reserved slots exceed max_reserved {} for player {player:?}",
                    self.max_reserved
                ),
            });
        }
        Ok(())
    }

    fn handle_purchase(
        &mut self,
        index: usize,
        player: PlayerId,
        card: CardId,
        from: PurchaseSourceInfo,
    ) -> Result<(), BeliefError> {
        self.check_player(index, player)?;
        match from {
            PurchaseSourceInfo::Market { tier, .. } => {
                validate_card_tier(index, card, tier, "market purchase")?;
            }
            PurchaseSourceInfo::Reserved { slot } => {
                let slot_index = slot as usize;
                let slot_kind = self.slots[player.index()].get(slot_index).copied().ok_or(
                    BeliefError::MalformedHistory {
                        index,
                        reason: format!(
                            "reserved purchase slot {slot} out of range for player {player:?}"
                        ),
                    },
                )?;
                match slot_kind {
                    ReservedKnowledgeV1::Known { card: known, .. } => {
                        if known != card {
                            return Err(BeliefError::MalformedHistory {
                                index,
                                reason: format!(
                                    "reserved purchase card {card:?} != tracked card {known:?}"
                                ),
                            });
                        }
                    }
                    ReservedKnowledgeV1::HiddenDeck { tier } => {
                        validate_card_tier(index, card, tier, "hidden reserved purchase")?;
                    }
                }
                self.slots[player.index()].remove(slot_index);
            }
        }
        Ok(())
    }

    fn handle_chance_reveal(
        &self,
        index: usize,
        tier: Tier,
        slot: Option<u8>,
        card: Option<CardId>,
        visible_to: Visibility,
    ) -> Result<(), BeliefError> {
        if slot.is_some() {
            if card.is_none() {
                return Err(BeliefError::MalformedHistory {
                    index,
                    reason: "market reveal must carry the public card identity".to_string(),
                });
            }
            return Ok(());
        }
        // Blind draw: an identity may appear only for the viewer's own reserve.
        match (card, visible_to) {
            (None, _) => Ok(()),
            (Some(card), Visibility::Player(player)) if player == self.viewer => {
                validate_card_tier(index, card, tier, "viewer blind draw")
            }
            (Some(_), Visibility::Public) => Err(BeliefError::MalformedHistory {
                index,
                reason: "blind draw cannot be public".to_string(),
            }),
            (Some(_), Visibility::Player(_)) => Err(BeliefError::HiddenInformationLeak { index }),
        }
    }

    fn check_player(&self, index: usize, player: PlayerId) -> Result<(), BeliefError> {
        if player.index() >= self.player_count {
            return Err(BeliefError::MalformedHistory {
                index,
                reason: format!(
                    "player {player:?} out of range for {} players",
                    self.player_count
                ),
            });
        }
        Ok(())
    }

    /// Cross-check the tracked slots against the observation, per player.
    fn check_against_observation(&self, observation: &Observation) -> Result<(), BeliefError> {
        let public = &observation.public;
        for (i, player_view) in public.players.iter().enumerate() {
            let player = PlayerId(i as u8);
            let tracked = &self.slots[i];
            if tracked.len() != player_view.reserved_count as usize {
                return Err(BeliefError::ReservedKnowledgeMismatch { player });
            }
            if player == observation.viewer {
                self.check_viewer_private(tracked, observation, player)?;
            } else {
                let known_public: Vec<CardId> = tracked
                    .iter()
                    .filter_map(|kind| match kind {
                        ReservedKnowledgeV1::Known {
                            card,
                            from_deck: false,
                        } => Some(*card),
                        _ => None,
                    })
                    .collect();
                if known_public != player_view.public_reserved {
                    return Err(BeliefError::ReservedKnowledgeMismatch { player });
                }
            }
        }
        Ok(())
    }

    fn check_viewer_private(
        &self,
        tracked: &[ReservedKnowledgeV1],
        observation: &Observation,
        player: PlayerId,
    ) -> Result<(), BeliefError> {
        let private = &observation.private.reserved;
        if private.len() != tracked.len() {
            return Err(BeliefError::ReservedKnowledgeMismatch { player });
        }
        for (slot_index, (kind, reserved_view)) in tracked.iter().zip(private).enumerate() {
            let ReservedKnowledgeV1::Known {
                card: tracked_card,
                from_deck,
            } = kind
            else {
                return Err(BeliefError::ReservedKnowledgeMismatch { player });
            };
            if reserved_view.slot as usize != slot_index
                || reserved_view.card != *tracked_card
                || reserved_view.from_deck != *from_deck
            {
                return Err(BeliefError::ReservedKnowledgeMismatch { player });
            }
            if reserved_view.card.0 as usize >= CARD_COUNT {
                return Err(BeliefError::MalformedObservation(format!(
                    "private reserved card {:?} out of catalog",
                    reserved_view.card
                )));
            }
            if card(reserved_view.card).tier != reserved_view.tier {
                return Err(BeliefError::MalformedObservation(format!(
                    "private reserved card {:?} tier {:?} != reserved view tier {:?}",
                    reserved_view.card,
                    card(reserved_view.card).tier,
                    reserved_view.tier
                )));
            }
        }
        Ok(())
    }
}

/// Validate that `cid` is a catalog card of exactly `tier`.
fn validate_card_tier(
    index: usize,
    cid: CardId,
    tier: Tier,
    context: &str,
) -> Result<(), BeliefError> {
    if cid.0 as usize >= CARD_COUNT {
        return Err(BeliefError::MalformedHistory {
            index,
            reason: format!("{context} card {cid:?} out of catalog"),
        });
    }
    let actual = card(cid).tier;
    if actual != tier {
        return Err(BeliefError::MalformedHistory {
            index,
            reason: format!("{context} card {cid:?} tier {actual:?} != expected {tier:?}"),
        });
    }
    Ok(())
}

/// Known-card set, duplicate / tier validation, and the per-tier unseen pools.
///
/// `known` is market + purchased + all tracked `Known` slots (the tracked
/// `Known` set is exactly the public market reserves plus the viewer's own
/// reserved cards, after the observation cross-check).
fn compute_partition(
    observation: &Observation,
    tracker: &Tracker,
) -> Result<(Vec<CardId>, [Vec<CardId>; 3]), BeliefError> {
    let public = &observation.public;
    let mut known: Vec<CardId> = Vec::new();
    for tier in Tier::ALL {
        for slot in 0..4 {
            if let Some(card) = public.market[tier.index()][slot] {
                known.push(card);
            }
        }
    }
    for player_view in &public.players {
        known.extend(player_view.purchased.iter().copied());
    }
    for slots in &tracker.slots {
        for kind in slots {
            if let ReservedKnowledgeV1::Known { card, .. } = kind {
                known.push(*card);
            }
        }
    }

    for cid in &known {
        if cid.0 as usize >= CARD_COUNT {
            return Err(BeliefError::MalformedObservation(format!(
                "known card {cid:?} out of catalog"
            )));
        }
    }
    for tier in Tier::ALL {
        for (slot, cid) in public.market[tier.index()].iter().enumerate() {
            if let Some(cid) = cid {
                if card(*cid).tier != tier {
                    return Err(BeliefError::MalformedObservation(format!(
                        "market tier {tier:?} slot {slot} card {cid:?} tier mismatch"
                    )));
                }
            }
        }
    }

    let mut sorted = known.clone();
    sorted.sort_unstable();
    for pair in sorted.windows(2) {
        if pair[0] == pair[1] {
            return Err(BeliefError::DuplicateKnownCard { card: pair[0] });
        }
    }

    let mut unseen: [Vec<CardId>; 3] = [Vec::new(), Vec::new(), Vec::new()];
    for tier in Tier::ALL {
        let total = cards_for_tier(tier).len();
        let known_in_tier = known.iter().filter(|cid| card(**cid).tier == tier).count();
        let unseen_count = total.checked_sub(known_in_tier).ok_or_else(|| {
            BeliefError::MalformedObservation(format!(
                "known cards exceed catalog total for tier {tier:?}"
            ))
        })?;
        let hidden = tracker
            .slots
            .iter()
            .flat_map(|slots| slots.iter())
            .filter(
                |kind| matches!(kind, ReservedKnowledgeV1::HiddenDeck { tier: t } if *t == tier),
            )
            .count();
        let expected = public.deck_counts[tier.index()] as usize + hidden;
        if unseen_count != expected {
            return Err(BeliefError::CardAccountingMismatch {
                tier,
                expected,
                found: unseen_count,
            });
        }
        let mut tier_unseen: Vec<CardId> = cards_for_tier(tier)
            .iter()
            .filter(|def| !known.contains(&def.id))
            .map(|def| def.id)
            .collect();
        tier_unseen.sort_unstable();
        unseen[tier.index()] = tier_unseen;
    }

    Ok((known, unseen))
}

/// Local mirror of `splendor_core`'s `ReserveSource` enum.
///
/// `ReserveSource`/`PurchaseSource` are public *types* but are not re-exported
/// from `splendor-core` (the `events` module is private), so they cannot be
/// named from another crate. Their serde encoding is frozen by the protocol,
/// so we decode the event `from` field through its JSON form instead of
/// pattern-matching the inaccessible enum. Only the fields the tracker needs
/// are carried (market slot positions are irrelevant to slot tracking).
#[derive(Debug, Clone, Copy)]
enum ReserveSourceInfo {
    Market { tier: Tier },
    Deck { tier: Tier },
}

/// Local mirror of `splendor_core`'s `PurchaseSource` enum.
#[derive(Debug, Clone, Copy)]
enum PurchaseSourceInfo {
    Market { tier: Tier },
    Reserved { slot: u8 },
}

fn decode_reserve_source(
    value: serde_json::Value,
    index: usize,
) -> Result<ReserveSourceInfo, BeliefError> {
    let object = value
        .as_object()
        .ok_or_else(|| malformed_source(index, "reserve source is not an object"))?;
    if let Some(market) = object.get("market") {
        let market = market
            .as_object()
            .ok_or_else(|| malformed_source(index, "market source is not an object"))?;
        let tier = decode_tier(market.get("tier"), index)?;
        Ok(ReserveSourceInfo::Market { tier })
    } else if let Some(deck) = object.get("deck") {
        let deck = deck
            .as_object()
            .ok_or_else(|| malformed_source(index, "deck source is not an object"))?;
        let tier = decode_tier(deck.get("tier"), index)?;
        Ok(ReserveSourceInfo::Deck { tier })
    } else {
        Err(malformed_source(index, "unknown reserve source variant"))
    }
}

fn decode_purchase_source(
    value: serde_json::Value,
    index: usize,
) -> Result<PurchaseSourceInfo, BeliefError> {
    let object = value
        .as_object()
        .ok_or_else(|| malformed_source(index, "purchase source is not an object"))?;
    if let Some(market) = object.get("market") {
        let market = market
            .as_object()
            .ok_or_else(|| malformed_source(index, "market source is not an object"))?;
        let tier = decode_tier(market.get("tier"), index)?;
        Ok(PurchaseSourceInfo::Market { tier })
    } else if let Some(reserved) = object.get("reserved") {
        let reserved = reserved
            .as_object()
            .ok_or_else(|| malformed_source(index, "reserved source is not an object"))?;
        let slot = decode_slot(reserved.get("slot"), index)?;
        Ok(PurchaseSourceInfo::Reserved { slot })
    } else {
        Err(malformed_source(index, "unknown purchase source variant"))
    }
}

fn decode_tier(value: Option<&serde_json::Value>, index: usize) -> Result<Tier, BeliefError> {
    match value.and_then(|v| v.as_str()) {
        Some("One") => Ok(Tier::One),
        Some("Two") => Ok(Tier::Two),
        Some("Three") => Ok(Tier::Three),
        _ => Err(malformed_source(index, "unknown tier in source")),
    }
}

fn decode_slot(value: Option<&serde_json::Value>, index: usize) -> Result<u8, BeliefError> {
    match value.and_then(|v| v.as_u64()) {
        Some(slot) if slot <= u8::MAX as u64 => Ok(slot as u8),
        _ => Err(malformed_source(index, "invalid slot in source")),
    }
}

fn malformed_source(index: usize, reason: &str) -> BeliefError {
    BeliefError::MalformedHistory {
        index,
        reason: reason.to_string(),
    }
}
