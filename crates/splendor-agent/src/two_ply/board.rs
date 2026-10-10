//! Lightweight simulation board for 2-ply continuation under strict information sets.
//! Unknown deck refills are NOT manufactured: purchased/reserved market cards leave empty slots (`None`).

use splendor_catalog::{all_nobles, card, CardId, GemColor, NobleId, Tier};
use splendor_core::{Action, Gems, Observation, PlayerId};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SimPlayer {
    pub id: PlayerId,
    pub tokens: Gems,
    pub bonuses: [u8; 5],
    pub prestige: u8,
    pub reserved: Vec<CardId>,
    pub purchased_count: usize,
}

impl SimPlayer {
    pub fn can_afford(&self, cost: [u8; 5]) -> bool {
        let mut needed_gold: u8 = 0;
        for c in GemColor::ALL {
            let discount = self.bonuses[c.index()];
            let effective_cost = cost[c.index()].saturating_sub(discount);
            let held = self.tokens.color(c);
            if effective_cost > held {
                needed_gold = needed_gold.saturating_add(effective_cost - held);
            }
        }
        self.tokens.gold >= needed_gold
    }

    pub fn pay_cost(&mut self, cost: [u8; 5], bank: &mut Gems) {
        for c in GemColor::ALL {
            let discount = self.bonuses[c.index()];
            let effective_cost = cost[c.index()].saturating_sub(discount);
            let held = self.tokens.color(c);
            let from_color = held.min(effective_cost);
            self.tokens.set_color(c, held - from_color);
            bank.set_color(c, bank.color(c) + from_color);
            let shortfall = effective_cost - from_color;
            if shortfall > 0 {
                self.tokens.gold = self.tokens.gold.saturating_sub(shortfall);
                bank.gold = bank.gold.saturating_add(shortfall);
            }
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SimBoard {
    pub players: Vec<SimPlayer>,
    pub current_player: usize,
    pub viewer: usize,
    pub bank: Gems,
    pub market: [[Option<CardId>; 4]; 3],
    pub nobles: Vec<NobleId>,
    pub end_game_triggered: bool,
    pub terminal: bool,
}

impl SimBoard {
    pub fn from_observation(obs: &Observation) -> Self {
        let viewer_idx = obs.viewer.index();
        let players = obs
            .public
            .players
            .iter()
            .enumerate()
            .map(|(i, p)| {
                let reserved = if i == viewer_idx {
                    obs.private.reserved.iter().map(|r| r.card).collect()
                } else {
                    p.public_reserved.clone()
                };
                SimPlayer {
                    id: p.id,
                    tokens: p.tokens,
                    bonuses: p.bonuses,
                    prestige: p.prestige,
                    reserved,
                    purchased_count: p.purchased.len(),
                }
            })
            .collect();

        Self {
            players,
            current_player: obs.public.current_player.index(),
            viewer: viewer_idx,
            bank: obs.public.bank,
            market: obs.public.market,
            nobles: obs.public.nobles.clone(),
            end_game_triggered: obs.public.end_game_triggered,
            terminal: false,
        }
    }

    pub fn current(&self) -> &SimPlayer {
        &self.players[self.current_player]
    }

    pub fn current_mut(&mut self) -> &mut SimPlayer {
        &mut self.players[self.current_player]
    }

    pub fn opponent(&self) -> &SimPlayer {
        let opp_idx = if self.players.len() == 2 {
            1 - self.viewer
        } else {
            (self.viewer + 1) % self.players.len()
        };
        &self.players[opp_idx]
    }

    pub fn viewer_player(&self) -> &SimPlayer {
        &self.players[self.viewer]
    }

    pub fn apply_action(&mut self, action: Action) {
        if self.terminal {
            return;
        }

        let cur_idx = self.current_player;
        match action {
            Action::TakeTokens { take, give_back } => {
                let p = &mut self.players[cur_idx];
                p.tokens = p
                    .tokens
                    .saturating_add(take)
                    .checked_sub(give_back)
                    .unwrap_or(p.tokens);
                self.bank = self.bank.checked_sub(take).unwrap_or(self.bank);
                self.bank = self.bank.saturating_add(give_back);
            }
            Action::BuyMarket { tier, slot } => {
                if let Some(cid) = self.market[tier.index()][slot as usize] {
                    // Strict information set: market slot becomes None, NO refill from hidden deck!
                    self.market[tier.index()][slot as usize] = None;
                    let def = card(cid);
                    let p = &mut self.players[cur_idx];
                    p.pay_cost(def.cost, &mut self.bank);
                    p.bonuses[def.bonus.index()] += 1;
                    p.prestige = p.prestige.saturating_add(def.prestige);
                    p.purchased_count += 1;
                    self.check_noble_claims(cur_idx);
                }
            }
            Action::BuyReserved { slot } => {
                let p = &mut self.players[cur_idx];
                if (slot as usize) < p.reserved.len() {
                    let cid = p.reserved.remove(slot as usize);
                    let def = card(cid);
                    p.pay_cost(def.cost, &mut self.bank);
                    p.bonuses[def.bonus.index()] += 1;
                    p.prestige = p.prestige.saturating_add(def.prestige);
                    p.purchased_count += 1;
                    self.check_noble_claims(cur_idx);
                }
            }
            Action::ReserveMarket {
                tier,
                slot,
                give_back,
            } => {
                if let Some(cid) = self.market[tier.index()][slot as usize] {
                    self.market[tier.index()][slot as usize] = None;
                    let p = &mut self.players[cur_idx];
                    p.reserved.push(cid);
                    if self.bank.gold > 0 {
                        p.tokens.gold += 1;
                        self.bank.gold -= 1;
                    }
                    p.tokens = p.tokens.checked_sub(give_back).unwrap_or(p.tokens);
                    self.bank = self.bank.saturating_add(give_back);
                }
            }
            Action::ReserveDeck { give_back, .. } => {
                let p = &mut self.players[cur_idx];
                if self.bank.gold > 0 {
                    p.tokens.gold += 1;
                    self.bank.gold -= 1;
                }
                p.tokens = p.tokens.checked_sub(give_back).unwrap_or(p.tokens);
                self.bank = self.bank.saturating_add(give_back);
            }
            Action::ChooseNoble { noble } => {
                let def = &all_nobles()[noble.index()];
                let p = &mut self.players[cur_idx];
                p.prestige = p.prestige.saturating_add(def.prestige);
                if let Some(pos) = self.nobles.iter().position(|&n| n == noble) {
                    self.nobles.remove(pos);
                }
            }
            Action::Pass => {}
        }

        // Check endgame condition
        if self.players[cur_idx].prestige >= 15 {
            self.end_game_triggered = true;
        }

        // Advance player turn
        self.current_player = (self.current_player + 1) % self.players.len();
        if self.end_game_triggered && self.current_player == 0 {
            self.terminal = true;
        }
    }

    fn check_noble_claims(&mut self, player_idx: usize) {
        let p = &mut self.players[player_idx];
        let mut best_noble_idx = None;
        let mut best_score = -1;

        for (i, &nid) in self.nobles.iter().enumerate() {
            let ndef = &all_nobles()[nid.index()];
            let mut satisfied = true;
            for c in GemColor::ALL {
                if p.bonuses[c.index()] < ndef.requirements[c.index()] {
                    satisfied = false;
                    break;
                }
            }
            if satisfied {
                let score = ndef.prestige as i32;
                if score > best_score {
                    best_score = score;
                    best_noble_idx = Some(i);
                }
            }
        }

        if let Some(idx) = best_noble_idx {
            let nid = self.nobles.remove(idx);
            let def = &all_nobles()[nid.index()];
            p.prestige = p.prestige.saturating_add(def.prestige);
        }
    }

    pub fn legal_actions(&self) -> Vec<Action> {
        let p = self.current();
        let mut actions = Vec::with_capacity(32);

        // 1. Buy Market
        for tier in Tier::ALL {
            for slot in 0..4u8 {
                if let Some(cid) = self.market[tier.index()][slot as usize] {
                    if p.can_afford(card(cid).cost) {
                        actions.push(Action::BuyMarket { tier, slot });
                    }
                }
            }
        }

        // 2. Buy Reserved
        for (slot, &cid) in p.reserved.iter().enumerate() {
            if p.can_afford(card(cid).cost) {
                actions.push(Action::BuyReserved { slot: slot as u8 });
            }
        }

        // 3. Take Tokens
        let held_tokens = p.tokens.total();
        let max_tokens: u8 = 10;
        let available_space = max_tokens.saturating_sub(held_tokens);

        // Double take (if bank has >= 4)
        for c in GemColor::ALL {
            if self.bank.color(c) >= 4 {
                let mut take = Gems::ZERO;
                take.set_color(c, 2);
                if available_space >= 2 {
                    actions.push(Action::TakeTokens {
                        take,
                        give_back: Gems::ZERO,
                    });
                } else if available_space == 1 {
                    // Must return 1 token of a different color
                    for ret_c in GemColor::ALL {
                        if ret_c != c && p.tokens.color(ret_c) > 0 {
                            let mut give_back = Gems::ZERO;
                            give_back.set_color(ret_c, 1);
                            actions.push(Action::TakeTokens { take, give_back });
                        }
                    }
                }
            }
        }

        // Three distinct colors
        let available_colors: Vec<GemColor> = GemColor::ALL
            .iter()
            .copied()
            .filter(|&c| self.bank.color(c) > 0)
            .collect();

        if available_colors.len() >= 3 {
            for i in 0..available_colors.len() {
                for j in (i + 1)..available_colors.len() {
                    for k in (j + 1)..available_colors.len() {
                        let mut take = Gems::ZERO;
                        take.set_color(available_colors[i], 1);
                        take.set_color(available_colors[j], 1);
                        take.set_color(available_colors[k], 1);

                        if available_space >= 3 {
                            actions.push(Action::TakeTokens {
                                take,
                                give_back: Gems::ZERO,
                            });
                        } else if available_space == 2 {
                            // Return 1 token
                            for ret_c in GemColor::ALL {
                                if p.tokens.color(ret_c) > 0 {
                                    let mut give_back = Gems::ZERO;
                                    give_back.set_color(ret_c, 1);
                                    actions.push(Action::TakeTokens { take, give_back });
                                }
                            }
                        }
                    }
                }
            }
        } else if !available_colors.is_empty() {
            // Fewer than 3 colors left in bank
            let mut take = Gems::ZERO;
            for &c in &available_colors {
                take.set_color(c, 1);
            }
            if available_space >= available_colors.len() as u8 {
                actions.push(Action::TakeTokens {
                    take,
                    give_back: Gems::ZERO,
                });
            }
        }

        // 4. Reserve Market (if reserved < 3)
        if p.reserved.len() < 3 {
            let give_back = if p.tokens.total() >= 10 && self.bank.gold > 0 {
                // Find a token to give back
                let mut gb = Gems::ZERO;
                for c in GemColor::ALL {
                    if p.tokens.color(c) > 0 {
                        gb.set_color(c, 1);
                        break;
                    }
                }
                gb
            } else {
                Gems::ZERO
            };

            for tier in Tier::ALL {
                for slot in 0..4u8 {
                    if self.market[tier.index()][slot as usize].is_some() {
                        actions.push(Action::ReserveMarket {
                            tier,
                            slot,
                            give_back,
                        });
                    }
                }
            }
        }

        if actions.is_empty() {
            actions.push(Action::Pass);
        }

        actions
    }
}
