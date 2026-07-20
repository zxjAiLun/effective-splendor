use rand::rngs::SmallRng;
use rand::seq::SliceRandom;
use rand::{Rng, SeedableRng};
use serde::{Deserialize, Serialize};
use splendor_catalog::{all_cards, all_nobles, card, CardId, GemColor, NobleId, Ruleset, Tier};

use crate::action::Action;
use crate::error::{EngineError, EngineResult};
use crate::events::{
    ChanceEvent, GameEvent, PurchaseSource, ReserveSource, StepResult, Visibility,
};
use crate::gems::Gems;
use crate::hash::{full_state_hash, FullStateHash};

/// Zero-based player index.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
pub struct PlayerId(pub u8);

impl PlayerId {
    pub fn index(self) -> usize {
        self.0 as usize
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Phase {
    Main,
    ChooseNoble,
    GameOver,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ReservedCard {
    pub card: CardId,
    /// True if reserved from deck top (identity hidden from others).
    pub from_deck: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FullPlayerState {
    pub id: PlayerId,
    pub tokens: Gems,
    /// Permanent bonuses [W,B,G,R,K].
    pub bonuses: [u8; 5],
    pub prestige: u8,
    pub reserved: Vec<ReservedCard>,
    pub nobles: Vec<NobleId>,
}

impl FullPlayerState {
    fn new(id: PlayerId) -> Self {
        Self {
            id,
            tokens: Gems::ZERO,
            bonuses: [0; 5],
            prestige: 0,
            reserved: Vec::new(),
            nobles: Vec::new(),
        }
    }

    pub fn can_afford(&self, cost: [u8; 5]) -> bool {
        payment_for(self, cost).is_some()
    }
}

/// Compute gold-aware payment: minimize gold use, deterministic color order.
pub fn payment_for(player: &FullPlayerState, cost: [u8; 5]) -> Option<Gems> {
    let mut pay = Gems::ZERO;
    let mut gold_needed = 0u8;
    for c in GemColor::ALL {
        let need = cost[c.index()].saturating_sub(player.bonuses[c.index()]);
        let have = player.tokens.color(c);
        if have >= need {
            pay.set_color(c, need);
        } else {
            pay.set_color(c, have);
            gold_needed = gold_needed.saturating_add(need - have);
        }
    }
    if player.tokens.gold < gold_needed {
        return None;
    }
    pay.gold = gold_needed;
    Some(pay)
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct GameResult {
    pub scores: Vec<u8>,
    pub ranks: Vec<u8>,
    pub winners: Vec<PlayerId>,
    pub reason: TerminalReason,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TerminalReason {
    PrestigeThreshold,
    Stalemate,
}

#[derive(Debug, Clone)]
pub struct GameConfig {
    pub player_count: u8,
    pub seed: u64,
    pub ruleset: Ruleset,
}

impl Default for GameConfig {
    fn default() -> Self {
        Self {
            player_count: 2,
            seed: 0,
            ruleset: Ruleset::base_v1(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SetupInfo {
    pub seed: u64,
    pub player_count: u8,
    pub ruleset_id: String,
    pub catalog_version: String,
    pub engine_version: String,
}

/// Referee-only full game state.
#[derive(Debug, Clone)]
pub struct FullState {
    pub ruleset: Ruleset,
    pub seed: u64,
    pub rng: SmallRng,
    pub decks: [Vec<CardId>; 3],
    pub market: [[Option<CardId>; 4]; 3],
    pub nobles: Vec<NobleId>,
    pub bank: Gems,
    pub players: Vec<FullPlayerState>,
    pub current_player: PlayerId,
    pub phase: Phase,
    pub pending_nobles: Vec<NobleId>,
    pub end_game_triggered: bool,
    /// After end is triggered, remaining turns in the final round (including
    /// players after the triggerer, not including the triggerer's finished turn).
    pub turns_remaining_in_final_round: Option<u8>,
    pub result: Option<GameResult>,
    /// Event log for the current game (optional accumulation).
    pub log: Vec<GameEvent>,
}

impl FullState {
    pub fn player_count(&self) -> u8 {
        self.players.len() as u8
    }

    pub fn setup_info(&self) -> SetupInfo {
        SetupInfo {
            seed: self.seed,
            player_count: self.player_count(),
            ruleset_id: self.ruleset.id.0.to_string(),
            catalog_version: self.ruleset.catalog_version.to_string(),
            engine_version: crate::ENGINE_VERSION.to_string(),
        }
    }

    pub fn new(config: GameConfig) -> EngineResult<(Self, StepResult)> {
        let n = config.player_count;
        if n < config.ruleset.min_players || n > config.ruleset.max_players {
            return Err(EngineError::InvalidPlayerCount(n));
        }

        let mut rng = SmallRng::seed_from_u64(config.seed);
        let color_tokens = config.ruleset.color_token_count(n);

        let mut decks: [Vec<CardId>; 3] = [Vec::new(), Vec::new(), Vec::new()];
        for c in all_cards() {
            decks[c.tier.index()].push(c.id);
        }
        for d in decks.iter_mut() {
            d.shuffle(&mut rng);
        }

        let mut noble_pool: Vec<NobleId> = all_nobles().iter().map(|n| n.id).collect();
        noble_pool.shuffle(&mut rng);
        let noble_count = config.ruleset.noble_count(n) as usize;
        let nobles = noble_pool.into_iter().take(noble_count).collect::<Vec<_>>();

        let players = (0..n).map(|i| FullPlayerState::new(PlayerId(i))).collect();

        let mut state = FullState {
            ruleset: config.ruleset,
            seed: config.seed,
            rng,
            decks,
            market: [[None; 4]; 3],
            nobles,
            bank: Gems {
                white: color_tokens,
                blue: color_tokens,
                green: color_tokens,
                red: color_tokens,
                black: color_tokens,
                gold: config.ruleset.gold_tokens,
            },
            players,
            current_player: PlayerId(0),
            phase: Phase::Main,
            pending_nobles: Vec::new(),
            end_game_triggered: false,
            turns_remaining_in_final_round: None,
            result: None,
            log: Vec::new(),
        };

        let mut events = vec![GameEvent::GameStarted {
            player_count: n,
            seed: config.seed,
            ruleset: config.ruleset.id.0.to_string(),
        }];

        // Deal market
        for tier in Tier::ALL {
            for slot in 0..4u8 {
                if let Some(cid) = state.draw_from_deck(tier) {
                    state.market[tier.index()][slot as usize] = Some(cid);
                    events.push(GameEvent::Chance(ChanceEvent::CardRevealed {
                        tier,
                        slot: Some(slot),
                        card: cid,
                        visible_to: Visibility::Public,
                    }));
                }
            }
        }

        events.push(GameEvent::Chance(ChanceEvent::SetupDealt {
            market: state.market,
            nobles: state.nobles.clone(),
        }));

        let hash_after = full_state_hash(&state);
        state.log.extend(events.clone());

        Ok((
            state,
            StepResult {
                events,
                state_hash_before: FullStateHash::empty(),
                state_hash_after: hash_after,
            },
        ))
    }

    fn draw_from_deck(&mut self, tier: Tier) -> Option<CardId> {
        self.decks[tier.index()].pop()
    }

    pub fn is_terminal(&self) -> bool {
        self.phase == Phase::GameOver
    }

    pub fn legal_actions(&self) -> Vec<Action> {
        if self.is_terminal() {
            return Vec::new();
        }
        match self.phase {
            Phase::Main => self.legal_main_actions(),
            Phase::ChooseNoble => self
                .pending_nobles
                .iter()
                .map(|&noble| Action::ChooseNoble { noble })
                .collect(),
            Phase::GameOver => Vec::new(),
        }
    }

    fn legal_main_actions(&self) -> Vec<Action> {
        let mut actions = Vec::new();
        let pid = self.current_player;
        let player = &self.players[pid.index()];

        // --- Take tokens ---
        self.collect_take_token_actions(&mut actions);

        // --- Buy market ---
        for tier in Tier::ALL {
            for slot in 0..4u8 {
                if let Some(cid) = self.market[tier.index()][slot as usize] {
                    let def = card(cid);
                    if player.can_afford(def.cost) {
                        actions.push(Action::BuyMarket { tier, slot });
                    }
                }
            }
        }

        // --- Buy reserved ---
        for (slot, r) in player.reserved.iter().enumerate() {
            let def = card(r.card);
            if player.can_afford(def.cost) {
                actions.push(Action::BuyReserved { slot: slot as u8 });
            }
        }

        // --- Reserve ---
        if player.reserved.len() < self.ruleset.max_reserved as usize {
            for tier in Tier::ALL {
                for slot in 0..4u8 {
                    if self.market[tier.index()][slot as usize].is_some() {
                        actions.push(Action::ReserveMarket { tier, slot });
                    }
                }
                if !self.decks[tier.index()].is_empty() {
                    actions.push(Action::ReserveDeck { tier });
                }
            }
        }

        // Official table almost never soft-locks; keep Pass as a safety valve so
        // search / random rollouts never face an empty action set in Main.
        if actions.is_empty() {
            actions.push(Action::Pass);
        }

        actions
    }

    fn collect_take_token_actions(&self, out: &mut Vec<Action>) {
        let player = &self.players[self.current_player.index()];
        let max_tokens = self.ruleset.max_tokens;

        // Two of same color
        for c in GemColor::ALL {
            if self.bank.color(c) >= 4 {
                let mut take = Gems::ZERO;
                take.set_color(c, 2);
                self.expand_take_with_returns(player.tokens, take, max_tokens, out);
            }
        }

        // Up to three different colors
        let available: Vec<GemColor> = GemColor::ALL
            .iter()
            .copied()
            .filter(|&c| self.bank.color(c) > 0)
            .collect();

        // All combinations of 1, 2, or 3 distinct colors (prefer max available up to 3)
        let n = available.len().min(3);
        if n == 0 {
            return;
        }
        // Generate combinations of size k for k in 1..=n, but rules say you take
        // 3 different if possible — actually official rules: take 3 different OR 2 same.
        // You may take fewer only if fewer colors remain in bank.
        // Strict reading: you always take 3 different when ≥3 colors available,
        // or all remaining distinct if <3. You cannot voluntarily take fewer than min(3, available).
        let k = available.len().min(3);
        for combo in combinations(&available, k) {
            let mut take = Gems::ZERO;
            for &c in &combo {
                take.set_color(c, 1);
            }
            self.expand_take_with_returns(player.tokens, take, max_tokens, out);
        }
    }

    fn expand_take_with_returns(
        &self,
        current: Gems,
        take: Gems,
        max_tokens: u8,
        out: &mut Vec<Action>,
    ) {
        // Gold is never taken via TakeTokens.
        if take.gold != 0 {
            return;
        }
        // Bank must cover take.
        if self.bank.checked_sub(take).is_none() {
            return;
        }

        let after = current + take;
        let total = after.total();
        if total <= max_tokens {
            out.push(Action::TakeTokens {
                take,
                give_back: Gems::ZERO,
            });
            return;
        }

        let must_return = total - max_tokens;
        // Enumerate all give_back multisets from `after` totaling must_return.
        // Bound is small (must_return ≤ 3 typically, tokens ≤ 12).
        let mut give_options = Vec::new();
        enumerate_returns(after, must_return, &mut give_options);
        for give_back in give_options {
            // Cannot return more than held after take; already enforced.
            // Must not return tokens you didn't effectively have — ok.
            out.push(Action::TakeTokens { take, give_back });
        }
    }

    pub fn apply(&mut self, action: Action) -> EngineResult<StepResult> {
        if self.is_terminal() {
            return Err(EngineError::GameOver);
        }

        let before = full_state_hash(self);
        let mut events = Vec::new();

        match self.phase {
            Phase::Main => {
                if matches!(action, Action::ChooseNoble { .. }) {
                    return Err(EngineError::WrongPhase(action));
                }
                self.apply_main(action, &mut events)?;
            }
            Phase::ChooseNoble => {
                let Action::ChooseNoble { noble } = action else {
                    return Err(EngineError::WrongPhase(action));
                };
                self.apply_choose_noble(noble, &mut events)?;
            }
            Phase::GameOver => return Err(EngineError::GameOver),
        }

        let after = full_state_hash(self);
        self.log.extend(events.clone());
        Ok(StepResult {
            events,
            state_hash_before: before,
            state_hash_after: after,
        })
    }

    fn apply_main(&mut self, action: Action, events: &mut Vec<GameEvent>) -> EngineResult<()> {
        let legal = self.legal_main_actions();
        if !legal.contains(&action) {
            return Err(EngineError::IllegalAction(format!("{action:?}")));
        }

        let pid = self.current_player;
        events.push(GameEvent::ActionApplied {
            player: pid,
            action,
        });

        match action {
            Action::Pass => {
                self.advance_turn(events);
            }
            Action::TakeTokens { take, give_back } => {
                self.apply_take(pid, take, give_back, events)?;
                self.advance_turn(events);
            }
            Action::BuyMarket { tier, slot } => {
                let cid = self.market[tier.index()][slot as usize]
                    .ok_or_else(|| EngineError::IllegalAction("empty market slot".into()))?;
                self.apply_buy(pid, cid, PurchaseSource::Market { tier, slot }, events)?;
                // Refill market
                if let Some(new_c) = self.draw_from_deck(tier) {
                    self.market[tier.index()][slot as usize] = Some(new_c);
                    events.push(GameEvent::Chance(ChanceEvent::CardRevealed {
                        tier,
                        slot: Some(slot),
                        card: new_c,
                        visible_to: Visibility::Public,
                    }));
                } else {
                    self.market[tier.index()][slot as usize] = None;
                }
                self.after_purchase(pid, events)?;
            }
            Action::BuyReserved { slot } => {
                let reserved = self.players[pid.index()]
                    .reserved
                    .get(slot as usize)
                    .ok_or_else(|| EngineError::IllegalAction("bad reserve slot".into()))?
                    .clone();
                self.apply_buy(
                    pid,
                    reserved.card,
                    PurchaseSource::Reserved { slot },
                    events,
                )?;
                self.players[pid.index()].reserved.remove(slot as usize);
                self.after_purchase(pid, events)?;
            }
            Action::ReserveMarket { tier, slot } => {
                let cid = self.market[tier.index()][slot as usize]
                    .ok_or_else(|| EngineError::IllegalAction("empty market slot".into()))?;
                self.apply_reserve(
                    pid,
                    cid,
                    false,
                    ReserveSource::Market { tier, slot },
                    events,
                )?;
                if let Some(new_c) = self.draw_from_deck(tier) {
                    self.market[tier.index()][slot as usize] = Some(new_c);
                    events.push(GameEvent::Chance(ChanceEvent::CardRevealed {
                        tier,
                        slot: Some(slot),
                        card: new_c,
                        visible_to: Visibility::Public,
                    }));
                } else {
                    self.market[tier.index()][slot as usize] = None;
                }
                self.advance_turn(events);
            }
            Action::ReserveDeck { tier } => {
                let cid = self
                    .draw_from_deck(tier)
                    .ok_or_else(|| EngineError::IllegalAction("empty deck".into()))?;
                events.push(GameEvent::Chance(ChanceEvent::CardRevealed {
                    tier,
                    slot: None,
                    card: cid,
                    visible_to: Visibility::Player(pid),
                }));
                self.apply_reserve(pid, cid, true, ReserveSource::Deck { tier }, events)?;
                self.advance_turn(events);
            }
            Action::ChooseNoble { .. } => unreachable!(),
        }
        Ok(())
    }

    fn apply_take(
        &mut self,
        pid: PlayerId,
        take: Gems,
        give_back: Gems,
        events: &mut Vec<GameEvent>,
    ) -> EngineResult<()> {
        self.bank = self
            .bank
            .checked_sub(take)
            .ok_or_else(|| EngineError::IllegalAction("bank lacks tokens".into()))?;
        let p = &mut self.players[pid.index()];
        p.tokens += take;

        if !give_back.is_zero() {
            p.tokens = p
                .tokens
                .checked_sub(give_back)
                .ok_or_else(|| EngineError::IllegalAction("cannot return tokens".into()))?;
            self.bank += give_back;
        }

        if p.tokens.total() > self.ruleset.max_tokens {
            return Err(EngineError::IllegalAction("exceeds max tokens".into()));
        }

        events.push(GameEvent::TokensTransferred {
            player: pid,
            taken_from_bank: take,
            returned_to_bank: give_back,
        });
        Ok(())
    }

    fn apply_buy(
        &mut self,
        pid: PlayerId,
        cid: CardId,
        source: PurchaseSource,
        events: &mut Vec<GameEvent>,
    ) -> EngineResult<()> {
        let def = card(cid);
        let pay = payment_for(&self.players[pid.index()], def.cost)
            .ok_or_else(|| EngineError::IllegalAction("cannot afford".into()))?;

        let p = &mut self.players[pid.index()];
        p.tokens = p
            .tokens
            .checked_sub(pay)
            .ok_or_else(|| EngineError::IllegalAction("payment failed".into()))?;
        self.bank += pay;

        p.bonuses[def.bonus.index()] = p.bonuses[def.bonus.index()].saturating_add(1);
        p.prestige = p.prestige.saturating_add(def.prestige);

        if let PurchaseSource::Market { tier, slot } = source {
            self.market[tier.index()][slot as usize] = None;
        }

        events.push(GameEvent::CardPurchased {
            player: pid,
            card: cid,
            paid: pay,
            from: source,
        });
        Ok(())
    }

    fn apply_reserve(
        &mut self,
        pid: PlayerId,
        cid: CardId,
        from_deck: bool,
        source: ReserveSource,
        events: &mut Vec<GameEvent>,
    ) -> EngineResult<()> {
        if let ReserveSource::Market { tier, slot } = source {
            self.market[tier.index()][slot as usize] = None;
        }

        let mut received_gold = false;
        if self.bank.gold > 0 {
            self.bank.gold -= 1;
            self.players[pid.index()].tokens.gold += 1;
            received_gold = true;
            // If over 10 tokens after gold, must return — official rules: if taking
            // gold would exceed 10, you still get it then discard down to 10.
            let max = self.ruleset.max_tokens;
            let p = &mut self.players[pid.index()];
            if p.tokens.total() > max {
                // Prefer discarding a non-gold if possible; for determinism, discard
                // gold last. Enumerate is complex for legal_actions — for reserve,
                // legal_actions currently doesn't expand return choices.
                // Spec simplification for Phase 0: auto-discard gold first if over,
                // else lowest color index. This is a known Phase-0 approximation;
                // full atomic return-on-reserve will be added with legal expansion.
                auto_discard_to_max(p, max, &mut self.bank);
            }
        }

        self.players[pid.index()].reserved.push(ReservedCard {
            card: cid,
            from_deck,
        });

        events.push(GameEvent::CardReserved {
            player: pid,
            card: cid,
            from: source,
            received_gold,
            public_identity: !from_deck,
            visible_to: if from_deck {
                Visibility::Player(pid)
            } else {
                Visibility::Public
            },
        });
        Ok(())
    }

    fn after_purchase(&mut self, pid: PlayerId, events: &mut Vec<GameEvent>) -> EngineResult<()> {
        // Check nobles
        let qualified: Vec<NobleId> = self
            .nobles
            .iter()
            .copied()
            .filter(|&nid| player_qualifies(&self.players[pid.index()], nid))
            .collect();

        match qualified.len() {
            0 => {
                self.maybe_trigger_end(pid, events);
                self.advance_turn(events);
            }
            1 => {
                let noble = qualified[0];
                self.take_noble(pid, noble, events);
                self.maybe_trigger_end(pid, events);
                self.advance_turn(events);
            }
            _ => {
                self.pending_nobles = qualified;
                self.phase = Phase::ChooseNoble;
            }
        }
        Ok(())
    }

    fn apply_choose_noble(
        &mut self,
        noble: NobleId,
        events: &mut Vec<GameEvent>,
    ) -> EngineResult<()> {
        if !self.pending_nobles.contains(&noble) {
            return Err(EngineError::IllegalAction("noble not available".into()));
        }
        let pid = self.current_player;
        events.push(GameEvent::ActionApplied {
            player: pid,
            action: Action::ChooseNoble { noble },
        });
        self.take_noble(pid, noble, events);
        self.pending_nobles.clear();
        self.phase = Phase::Main;
        self.maybe_trigger_end(pid, events);
        self.advance_turn(events);
        Ok(())
    }

    fn take_noble(&mut self, pid: PlayerId, noble: NobleId, events: &mut Vec<GameEvent>) {
        if let Some(pos) = self.nobles.iter().position(|&n| n == noble) {
            self.nobles.remove(pos);
        }
        let p = &mut self.players[pid.index()];
        p.nobles.push(noble);
        let prestige = splendor_catalog::all_nobles()[noble.index()].prestige;
        p.prestige = p.prestige.saturating_add(prestige);
        events.push(GameEvent::NobleTaken { player: pid, noble });
    }

    fn maybe_trigger_end(&mut self, pid: PlayerId, events: &mut Vec<GameEvent>) {
        if self.end_game_triggered {
            return;
        }
        let score = self.players[pid.index()].prestige;
        if score >= self.ruleset.prestige_to_end {
            self.end_game_triggered = true;
            // Remaining players in the round (after current) still play.
            let n = self.player_count();
            // After this turn advances, players (pid+1 .. first_player-1) play.
            // We set remaining turns = players after current until back to 0...
            // Standard: finish the round so everyone has equal turns.
            // Current player is about to end their turn; remaining = n - 1 - pid.index()?
            // If player 0 triggers, players 1..n-1 still play → n-1 turns.
            // If player k triggers, players k+1..n-1 still play → n-1-k turns.
            let remaining = n - 1 - pid.0;
            self.turns_remaining_in_final_round = Some(remaining);
            events.push(GameEvent::EndGameTriggered { by: pid });
            if remaining == 0 {
                self.finish_game(events);
            }
        }
    }

    fn advance_turn(&mut self, events: &mut Vec<GameEvent>) {
        if self.phase == Phase::GameOver || self.phase == Phase::ChooseNoble {
            return;
        }

        // End already triggered: `turns_remaining` is how many *other* players
        // still get a turn after the triggerer's completed turn.
        if self.end_game_triggered {
            if let Some(rem) = self.turns_remaining_in_final_round {
                if rem == 0 {
                    self.finish_game(events);
                    return;
                }
                let n = self.player_count();
                let next = PlayerId((self.current_player.0 + 1) % n);
                self.current_player = next;
                events.push(GameEvent::TurnAdvanced { next_player: next });
                self.turns_remaining_in_final_round = Some(rem - 1);
                return;
            }
        }

        let n = self.player_count();
        let next = PlayerId((self.current_player.0 + 1) % n);
        self.current_player = next;
        events.push(GameEvent::TurnAdvanced { next_player: next });
    }

    fn finish_game(&mut self, events: &mut Vec<GameEvent>) {
        self.finish_game_with_reason(TerminalReason::PrestigeThreshold, events);
    }

    fn finish_game_with_reason(&mut self, reason: TerminalReason, events: &mut Vec<GameEvent>) {
        self.phase = Phase::GameOver;
        let mut result = compute_result(&self.players);
        result.reason = reason;
        self.result = Some(result.clone());
        events.push(GameEvent::GameEnded { result });
    }

    /// Invariant checks for tests.
    pub fn assert_invariants(&self) -> EngineResult<()> {
        // Token conservation
        let color_supply = self.ruleset.color_token_count(self.player_count());
        for c in GemColor::ALL {
            let mut total = self.bank.color(c);
            for p in &self.players {
                total = total.saturating_add(p.tokens.color(c));
            }
            if total != color_supply {
                return Err(EngineError::Invariant(format!(
                    "color {:?} tokens {} != supply {}",
                    c, total, color_supply
                )));
            }
        }
        let mut gold = self.bank.gold;
        for p in &self.players {
            gold = gold.saturating_add(p.tokens.gold);
        }
        if gold != self.ruleset.gold_tokens {
            return Err(EngineError::Invariant(format!(
                "gold {} != {}",
                gold, self.ruleset.gold_tokens
            )));
        }

        // Each card appears at most once
        let mut seen = [false; 90];
        let mut mark = |id: CardId| -> EngineResult<()> {
            let i = id.index();
            if seen[i] {
                return Err(EngineError::Invariant(format!("duplicate card {i}")));
            }
            seen[i] = true;
            Ok(())
        };
        for tier in 0..3 {
            for slot in 0..4 {
                if let Some(id) = self.market[tier][slot] {
                    mark(id)?;
                }
            }
            for &id in &self.decks[tier] {
                mark(id)?;
            }
        }
        for p in &self.players {
            for r in &p.reserved {
                mark(r.card)?;
            }
            // Purchased cards are only tracked as bonuses, not IDs — OK for Phase 0.
        }

        for p in &self.players {
            if p.tokens.total() > self.ruleset.max_tokens {
                return Err(EngineError::Invariant("player over token limit".into()));
            }
            if p.reserved.len() > self.ruleset.max_reserved as usize {
                return Err(EngineError::Invariant("too many reserved".into()));
            }
        }
        Ok(())
    }
}

fn player_qualifies(player: &FullPlayerState, noble: NobleId) -> bool {
    let def = &all_nobles()[noble.index()];
    GemColor::ALL
        .iter()
        .all(|&c| player.bonuses[c.index()] >= def.requirements[c.index()])
}

fn auto_discard_to_max(player: &mut FullPlayerState, max: u8, bank: &mut Gems) {
    while player.tokens.total() > max {
        // Discard gold first (deterministic Phase-0 policy when reserve overflows).
        if player.tokens.gold > 0 {
            player.tokens.gold -= 1;
            bank.gold += 1;
            continue;
        }
        let mut discarded = false;
        for c in GemColor::ALL {
            if player.tokens.color(c) > 0 {
                player.tokens.sub_color(c, 1);
                bank.add_color(c, 1);
                discarded = true;
                break;
            }
        }
        if !discarded {
            break;
        }
    }
}

fn compute_result(players: &[FullPlayerState]) -> GameResult {
    let scores: Vec<u8> = players.iter().map(|p| p.prestige).collect();
    let best = *scores.iter().max().unwrap_or(&0);

    // Tie-break: fewer development cards (bonuses sum) wins among top score.
    let card_counts: Vec<u8> = players
        .iter()
        .map(|p| p.bonuses.iter().sum::<u8>())
        .collect();

    let mut contenders: Vec<usize> = scores
        .iter()
        .enumerate()
        .filter(|(_, &s)| s == best)
        .map(|(i, _)| i)
        .collect();
    let min_cards = contenders
        .iter()
        .map(|&i| card_counts[i])
        .min()
        .unwrap_or(0);
    contenders.retain(|&i| card_counts[i] == min_cards);

    let winners: Vec<PlayerId> = contenders.iter().map(|&i| PlayerId(i as u8)).collect();

    // Dense ranks: 0 = best
    let mut order: Vec<usize> = (0..players.len()).collect();
    order.sort_by(|&a, &b| {
        scores[b]
            .cmp(&scores[a])
            .then_with(|| card_counts[a].cmp(&card_counts[b]))
    });
    let mut ranks = vec![0u8; players.len()];
    for (rank, &i) in order.iter().enumerate() {
        ranks[i] = rank as u8;
    }

    GameResult {
        scores,
        ranks,
        winners,
        reason: TerminalReason::PrestigeThreshold,
    }
}

fn combinations<T: Copy>(items: &[T], k: usize) -> Vec<Vec<T>> {
    let mut out = Vec::new();
    let mut cur = Vec::new();
    fn rec<T: Copy>(items: &[T], k: usize, start: usize, cur: &mut Vec<T>, out: &mut Vec<Vec<T>>) {
        if cur.len() == k {
            out.push(cur.clone());
            return;
        }
        for i in start..items.len() {
            cur.push(items[i]);
            rec(items, k, i + 1, cur, out);
            cur.pop();
        }
    }
    rec(items, k, 0, &mut cur, &mut out);
    out
}

fn enumerate_returns(held: Gems, count: u8, out: &mut Vec<Gems>) {
    fn rec(held: Gems, remaining: u8, idx: usize, cur: &mut Gems, out: &mut Vec<Gems>) {
        if remaining == 0 {
            out.push(*cur);
            return;
        }
        if idx > 5 {
            return;
        }
        // colors 0..4 then gold=5
        let max_here = if idx < 5 {
            held.color(GemColor::from_index(idx).unwrap())
        } else {
            held.gold
        };
        let max_take = max_here.min(remaining);
        for n in 0..=max_take {
            if idx < 5 {
                cur.set_color(GemColor::from_index(idx).unwrap(), n);
            } else {
                cur.gold = n;
            }
            rec(held, remaining - n, idx + 1, cur, out);
            if idx < 5 {
                cur.set_color(GemColor::from_index(idx).unwrap(), 0);
            } else {
                cur.gold = 0;
            }
        }
    }
    let mut cur = Gems::ZERO;
    rec(held, count, 0, &mut cur, out);
}

/// Random legal action helper for smoke tests / baseline bot.
pub fn random_action<R: Rng>(state: &FullState, rng: &mut R) -> Option<Action> {
    let acts = state.legal_actions();
    acts.choose(rng).copied()
}

/// Play a full random game; returns final state.
pub fn play_random_game(config: GameConfig) -> EngineResult<FullState> {
    let (mut state, _) = FullState::new(config)?;
    let mut guard = 0u32;
    let mut consecutive_passes = 0u32;
    let pass_limit = state.player_count() as u32;
    while !state.is_terminal() {
        guard += 1;
        if guard > 10_000 {
            return Err(EngineError::Invariant("game exceeded 10000 plies".into()));
        }
        let acts = state.legal_actions();
        if acts.is_empty() {
            return Err(EngineError::Invariant(format!(
                "no legal actions in phase {:?}",
                state.phase
            )));
        }
        // Prefer non-pass actions so random rollouts keep progressing.
        let non_pass: Vec<Action> = acts
            .iter()
            .copied()
            .filter(|a| !matches!(a, Action::Pass))
            .collect();
        let pool = if non_pass.is_empty() {
            &acts
        } else {
            &non_pass
        };
        let idx = state.rng.gen_range(0..pool.len());
        let action = pool[idx];
        if matches!(action, Action::Pass) {
            consecutive_passes += 1;
        } else {
            consecutive_passes = 0;
        }
        state.apply(action)?;
        state.assert_invariants()?;

        // Full round of forced passes → stalemate terminal.
        if consecutive_passes >= pass_limit && !state.is_terminal() {
            state.force_stalemate_end();
        }
    }
    Ok(state)
}

impl FullState {
    /// End the game immediately with current scores (stalemate / soft-lock).
    pub fn force_stalemate_end(&mut self) {
        if self.is_terminal() {
            return;
        }
        let mut events = Vec::new();
        self.finish_game_with_reason(TerminalReason::Stalemate, &mut events);
        self.log.extend(events);
    }
}
