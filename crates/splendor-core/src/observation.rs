use serde::{Deserialize, Serialize};
use splendor_catalog::{CardId, NobleId, Tier};

use crate::gems::Gems;
use crate::state::{FullState, Phase, PlayerId, ReservedCard};

/// Fully public board information.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PublicState {
    pub player_count: u8,
    pub current_player: PlayerId,
    pub phase: Phase,
    pub bank: Gems,
    pub market: [[Option<CardId>; 4]; 3],
    pub deck_counts: [u8; 3],
    pub nobles: Vec<NobleId>,
    pub players: Vec<PublicPlayerView>,
    pub end_game_triggered: bool,
    pub turns_remaining_in_final_round: Option<u8>,
    pub pending_nobles: Vec<NobleId>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PublicPlayerView {
    pub id: PlayerId,
    pub tokens: Gems,
    pub bonuses: [u8; 5],
    pub prestige: u8,
    pub reserved_count: u8,
    /// Face-up reserved cards only (from market). Blind reserves are omitted.
    pub public_reserved: Vec<CardId>,
    pub nobles: Vec<NobleId>,
}

/// Private information visible only to one player.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PrivatePlayerView {
    pub reserved: Vec<ReservedView>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ReservedView {
    pub slot: u8,
    pub card: CardId,
    pub tier: Tier,
    pub from_deck: bool,
}

/// Player-centric observation: public board + own private cards.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Observation {
    pub viewer: PlayerId,
    pub public: PublicState,
    pub private: PrivatePlayerView,
}

impl FullState {
    /// Build an observation for `viewer`. Must not leak other players' blind reserves.
    pub fn observation(&self, viewer: PlayerId) -> Observation {
        let public = PublicState {
            player_count: self.player_count(),
            current_player: self.current_player,
            phase: self.phase,
            bank: self.bank,
            market: self.market,
            deck_counts: [
                self.decks[0].len() as u8,
                self.decks[1].len() as u8,
                self.decks[2].len() as u8,
            ],
            nobles: self.nobles.clone(),
            players: self
                .players
                .iter()
                .map(|p| PublicPlayerView {
                    id: p.id,
                    tokens: p.tokens,
                    bonuses: p.bonuses,
                    prestige: p.prestige,
                    reserved_count: p.reserved.len() as u8,
                    public_reserved: p
                        .reserved
                        .iter()
                        .filter(|r| !r.from_deck)
                        .map(|r| r.card)
                        .collect(),
                    nobles: p.nobles.clone(),
                })
                .collect(),
            end_game_triggered: self.end_game_triggered,
            turns_remaining_in_final_round: self.turns_remaining_in_final_round,
            pending_nobles: self.pending_nobles.clone(),
        };

        let me = &self.players[viewer.index()];
        let private = PrivatePlayerView {
            reserved: me
                .reserved
                .iter()
                .enumerate()
                .map(|(i, r)| reserved_view(i as u8, r))
                .collect(),
        };

        Observation {
            viewer,
            public,
            private,
        }
    }
}

fn reserved_view(slot: u8, r: &ReservedCard) -> ReservedView {
    let tier = splendor_catalog::card(r.card).tier;
    ReservedView {
        slot,
        card: r.card,
        tier,
        from_deck: r.from_deck,
    }
}
