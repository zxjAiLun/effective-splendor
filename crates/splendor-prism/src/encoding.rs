//! Canonical Prism-only visible representation. Widths are frozen by M51.
//!
//! Entity[96]: 0..7 type(global,player,card,noble,bank,unknown,empty),7 known,
//! 8 present,9..14 region(market,own reserve,opp reserve,own purchased,opp purchased),
//! 15/16 self/opponent owner,17 catalog identity(normalized),18..21 tier,21 VP/5,
//! 22..27 five costs/requirements /7,27..32 bonus onehot,32..38 tokens/bank /10,
//! 38..43 player discounts /20,43 prestige/20,44 purchased/30,45 reserved/3,46 nobles/3,
//! 47..52 my discounted cost/noble gap /7,52..57 opponent equivalent,
//! 57..62 my colored token shortfall /7,62..67 opponent equivalent,
//! 67/68 gold-aware total shortfall /20,69/70 affordable/eligible,
//! 71 relative current player,72..75 phase onehot,75 final triggered,76 remaining/2,
//! 77 remaining present,78 forced passes/2,79..82 deck counts /40,
//! 82 total Main count/100,83/84 own/opp Main count/50,85 viewer absolute seat,
//! 86..89 known blind-reserve tier counts /3 (global),90 pending noble,
//! 91/92 total noble gaps /20,93 bank gold/5,94 player count/4,95 unused.
//!
//! Action[80]: 0..7 seven kinds;7..13 take/4;13..19 give-back/10;19..22 tier;
//! 22 target present,23 unknown target;24..30 post tokens/10;30..36 bank delta/10;
//! 36..41 bonus gain;41 realized VP gain/8;42 postVP/20;43 market source,44 reserve source;
//! 45 target→reserve,46 target→purchased,47 selected/automatic noble;
//! 48 target leaves market,49 unknown refill;50 Main cost;51 eligible noble count/3;
//! 52..62 eligible NobleId mask;62..67 post bonuses/20;67 threshold reached;
//! 68 pending noble choice;69 current final round;70 post reserve count/3;
//! 71/72 target own/opponent pre-shortfall;73 after min noble gap/20;
//! 74 post gold/5;75 paid gold/5;76 post tokens full;77 own target from deck;78/79 unused.
//! Targets are local entity indices, never flattened market slot numbers.
use serde::{Deserialize, Serialize};
use splendor_catalog::{all_cards, all_nobles, card, CardId, NobleId, Tier};
use splendor_core::{
    ruleset_fingerprint, Action, Gems, Observation, Phase, PublicPlayerView, Ruleset, VisibleEvent,
};
use std::collections::BTreeSet;

pub const ENTITY_DIM: usize = 96;
pub const ACTION_DIM: usize = 80;
pub const OBS_SCHEMA: &str = "prism-observation-v1";
pub const ACTION_SCHEMA: &str = "prism-action-v1";
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct EncodedState {
    pub entities: Vec<Vec<f32>>,
    pub actions: Vec<Vec<f32>>,
    pub targets: Vec<i32>,
}
impl EncodedState {
    pub fn validate(&self) -> Result<(), String> {
        if self.entities.is_empty()
            || self.entities.len() > 128
            || self.actions.is_empty()
            || self.actions.len() > 4096
            || self.targets.len() != self.actions.len()
        {
            return Err("Prism invalid input cardinality".into());
        }
        for (rows, width) in [(&self.entities, ENTITY_DIM), (&self.actions, ACTION_DIM)] {
            if rows
                .iter()
                .any(|r| r.len() != width || r.iter().any(|x| !x.is_finite()))
            {
                return Err("Prism invalid feature width/value".into());
            }
        }
        if self
            .targets
            .iter()
            .any(|t| *t < -1 || *t >= self.entities.len() as i32)
        {
            return Err("Prism invalid target index".into());
        }
        Ok(())
    }
}
pub fn catalog_fingerprint() -> String {
    ruleset_fingerprint(&Ruleset::base_v1()).to_string()
}
fn gems(g: Gems) -> [u8; 6] {
    [g.white, g.blue, g.green, g.red, g.black, g.gold]
}
fn row(kind: usize, known: bool, present: bool) -> Vec<f32> {
    let mut r = vec![0.0; ENTITY_DIM];
    r[kind] = 1.0;
    r[7] = known as u8 as f32;
    r[8] = present as u8 as f32;
    r
}
fn relations(
    r: &mut [f32],
    cost: [u8; 5],
    noble: bool,
    me: &PublicPlayerView,
    opp: &PublicPlayerView,
) {
    for (j, p) in [me, opp].iter().enumerate() {
        let t = gems(p.tokens);
        let mut missing = 0u16;
        let mut gap = 0u16;
        for i in 0..5 {
            let need = cost[i].saturating_sub(p.bonuses[i]);
            let short = if noble {
                need
            } else {
                need.saturating_sub(t[i])
            };
            r[47 + j * 5 + i] = need as f32 / 7.0;
            r[57 + j * 5 + i] = short as f32 / 7.0;
            missing += short as u16;
            gap += need as u16;
        }
        let missing = if noble {
            missing
        } else {
            missing.saturating_sub(t[5] as u16)
        };
        r[67 + j] = missing as f32 / 20.0;
        r[69 + j] = (missing == 0) as u8 as f32;
        if noble {
            r[91 + j] = gap as f32 / 20.0;
        }
    }
}
fn card_row(id: CardId, region: usize, me: &PublicPlayerView, opp: &PublicPlayerView) -> Vec<f32> {
    let c = card(id);
    let mut r = row(2, true, true);
    r[9 + region] = 1.0;
    if region == 1 || region == 3 {
        r[15] = 1.0;
    }
    if region == 2 || region == 4 {
        r[16] = 1.0;
    }
    r[17] = (id.0 as f32 + 1.0) / 90.0;
    r[18 + c.tier.index()] = 1.0;
    r[21] = c.prestige as f32 / 5.0;
    for i in 0..5 {
        r[22 + i] = c.cost[i] as f32 / 7.0;
    }
    r[27 + c.bonus.index()] = 1.0;
    relations(&mut r, c.cost, false, me, opp);
    r
}
fn noble_row(
    id: NobleId,
    owner: Option<usize>,
    pending: bool,
    me: &PublicPlayerView,
    opp: &PublicPlayerView,
) -> Vec<f32> {
    let n = &all_nobles()[id.index()];
    let mut r = row(3, true, true);
    r[17] = (id.0 as f32 + 1.0) / 10.0;
    r[21] = 3.0 / 5.0;
    if let Some(owner) = owner {
        r[15 + owner] = 1.0;
    }
    for i in 0..5 {
        r[22 + i] = n.requirements[i] as f32 / 7.0;
    }
    r[90] = pending as u8 as f32;
    relations(&mut r, n.requirements, true, me, opp);
    r
}
fn validate_observation(obs: &Observation) -> Result<(), String> {
    if obs.public.player_count != 2
        || obs.public.players.len() != 2
        || obs.viewer.index() > 1
        || obs.public.current_player.index() > 1
        || obs.viewer != obs.public.current_player
    {
        return Err("Prism requires active viewer in classic 2-player game".into());
    }
    if obs.ruleset_fingerprint.to_string() != catalog_fingerprint() {
        return Err("Prism ruleset/catalog mismatch".into());
    }
    if obs.public.phase == Phase::GameOver {
        return Err("Prism terminal observation has no decision".into());
    }
    let mut known = BTreeSet::new();
    let mut check = |id: CardId| -> Result<(), String> {
        if id.index() >= all_cards().len() || !known.insert(id) {
            Err("invalid/duplicate visible CardId".into())
        } else {
            Ok(())
        }
    };
    for tier in 0..3 {
        for id in obs.public.market[tier].iter().flatten() {
            check(*id)?;
            if card(*id).tier.index() != tier {
                return Err("market tier mismatch".into());
            }
        }
    }
    for (i, p) in obs.public.players.iter().enumerate() {
        if p.id.index() != i
            || p.reserved_count > 3
            || p.public_reserved.len() > p.reserved_count as usize
            || gems(p.tokens).iter().map(|x| *x as u16).sum::<u16>() > 10
            || p.bonuses.iter().any(|x| *x > 90)
        {
            return Err("invalid player view".into());
        }
        for id in &p.purchased {
            check(*id)?;
        }
        if i != obs.viewer.index() {
            for id in &p.public_reserved {
                check(*id)?;
            }
        }
    }
    if obs.private.reserved.len() != obs.public.players[obs.viewer.index()].reserved_count as usize
    {
        return Err("own reserve count mismatch".into());
    }
    for (i, r) in obs.private.reserved.iter().enumerate() {
        check(r.card)?;
        if r.slot as usize != i || card(r.card).tier != r.tier {
            return Err("own reserve slot/tier mismatch".into());
        }
    }
    let ids = obs
        .public
        .nobles
        .iter()
        .chain(obs.public.pending_nobles.iter())
        .chain(obs.public.players.iter().flat_map(|p| p.nobles.iter()));
    if ids.clone().any(|id| id.index() >= all_nobles().len()) {
        return Err("invalid NobleId".into());
    }
    if obs
        .public
        .pending_nobles
        .iter()
        .any(|id| !obs.public.nobles.contains(id))
    {
        return Err("pending noble not on board".into());
    }
    Ok(())
}
pub fn encode(
    obs: &Observation,
    history: &[VisibleEvent],
    actions: &[Action],
) -> Result<EncodedState, String> {
    validate_observation(obs)?;
    let my = obs.viewer.index();
    let me = &obs.public.players[my];
    let opp = &obs.public.players[1 - my];
    let mut main = [0u32; 2];
    let mut reserve_history: [Vec<Option<Tier>>; 2] = [Vec::new(), Vec::new()];
    for event in history {
        if let VisibleEvent::ActionApplied { player, action } = event {
            if player.index() > 1 {
                return Err("history player invalid".into());
            }
            if action.is_main_action() {
                main[player.index()] += 1;
            }
            match *action {
                Action::ReserveMarket { .. } => reserve_history[player.index()].push(None),
                Action::ReserveDeck { tier, .. } => {
                    reserve_history[player.index()].push(Some(tier))
                }
                Action::BuyReserved { slot } => {
                    if (slot as usize) < reserve_history[player.index()].len() {
                        reserve_history[player.index()].remove(slot as usize);
                    }
                }
                _ => {}
            }
        }
    }
    let mut entities = Vec::new();
    let mut global = row(0, true, true);
    for (i, v) in gems(obs.public.bank).iter().enumerate() {
        global[32 + i] = *v as f32 / 10.0;
    }
    global[71] = (obs.public.current_player.index() != my) as u8 as f32;
    global[72
        + match obs.public.phase {
            Phase::Main => 0,
            Phase::ChooseNoble => 1,
            Phase::GameOver => 2,
        }] = 1.0;
    global[75] = obs.public.end_game_triggered as u8 as f32;
    global[76] = obs.public.turns_remaining_in_final_round.unwrap_or(0) as f32 / 2.0;
    global[77] = obs.public.turns_remaining_in_final_round.is_some() as u8 as f32;
    global[78] = obs.public.consecutive_forced_passes as f32 / 2.0;
    for i in 0..3 {
        global[79 + i] = obs.public.deck_counts[i] as f32 / 40.0;
    }
    global[82] = (main[0] + main[1]) as f32 / 100.0;
    global[83] = main[my] as f32 / 50.0;
    global[84] = main[1 - my] as f32 / 50.0;
    global[85] = my as f32;
    global[93] = obs.public.bank.gold as f32 / 5.0;
    global[94] = 0.5;
    for tier in reserve_history[1 - my].iter().flatten() {
        global[86 + tier.index()] += 1.0 / 3.0;
    }
    entities.push(global);
    for (relative, p) in [me, opp].iter().enumerate() {
        let mut r = row(1, true, true);
        r[15 + relative] = 1.0;
        for (i, v) in gems(p.tokens).iter().enumerate() {
            r[32 + i] = *v as f32 / 10.0;
        }
        for i in 0..5 {
            r[38 + i] = p.bonuses[i] as f32 / 20.0;
        }
        r[43] = p.prestige as f32 / 20.0;
        r[44] = p.purchased.len() as f32 / 30.0;
        r[45] = p.reserved_count as f32 / 3.0;
        r[46] = p.nobles.len() as f32 / 3.0;
        r[85] = p.id.0 as f32;
        entities.push(r);
    }
    for (i, v) in gems(obs.public.bank).iter().enumerate() {
        let mut r = row(4, true, true);
        r[22 + i] = 1.0;
        r[32 + i] = *v as f32 / 10.0;
        entities.push(r);
    }
    let mut market = [[0usize; 4]; 3];
    for tier in 0..3 {
        for slot in 0..4 {
            market[tier][slot] = entities.len();
            let r = match obs.public.market[tier][slot] {
                Some(id) => card_row(id, 0, me, opp),
                None => {
                    let mut r = row(6, true, false);
                    r[9] = 1.0;
                    r[18 + tier] = 1.0;
                    r
                }
            };
            entities.push(r);
        }
    }
    let mut reserved = Vec::new();
    for r in &obs.private.reserved {
        reserved.push(entities.len());
        entities.push(card_row(r.card, 1, me, opp));
    }
    for _ in obs.private.reserved.len()..3 {
        let mut r = row(6, true, false);
        r[10] = 1.0;
        r[15] = 1.0;
        entities.push(r);
    }
    for id in &opp.public_reserved {
        entities.push(card_row(*id, 2, me, opp));
    }
    for _ in opp.public_reserved.len()..opp.reserved_count as usize {
        let mut r = row(5, false, true);
        r[11] = 1.0;
        r[16] = 1.0;
        entities.push(r);
    }
    for _ in opp.reserved_count..3 {
        let mut r = row(6, true, false);
        r[11] = 1.0;
        r[16] = 1.0;
        entities.push(r);
    }
    for id in &me.purchased {
        entities.push(card_row(*id, 3, me, opp));
    }
    for id in &opp.purchased {
        entities.push(card_row(*id, 4, me, opp));
    }
    let mut nobles = std::collections::BTreeMap::new();
    for id in &obs.public.nobles {
        nobles.insert(*id, entities.len());
        entities.push(noble_row(
            *id,
            None,
            obs.public.pending_nobles.contains(id),
            me,
            opp,
        ));
    }
    for (relative, p) in [me, opp].iter().enumerate() {
        for id in &p.nobles {
            entities.push(noble_row(*id, Some(relative), false, me, opp));
        }
    }
    let before = gems(me.tokens);
    let mut encoded = Vec::new();
    let mut targets = Vec::new();
    for action in actions {
        if (obs.public.phase == Phase::ChooseNoble) != matches!(action, Action::ChooseNoble { .. })
        {
            return Err("action/phase mismatch".into());
        }
        let mut a = vec![0.0; ACTION_DIM];
        let mut target = -1;
        let mut after = before;
        let mut bonus = me.bonuses;
        let mut vp = me.prestige as u16;
        let mut reserve_count = me.reserved_count;
        let mut bought = None;
        let mut returned = Gems::ZERO;
        let mut take = Gems::ZERO;
        let mut selected_noble = false;
        match *action {
            Action::TakeTokens { take: t, give_back } => {
                a[0] = 1.0;
                take = t;
                returned = give_back;
            }
            Action::BuyMarket { tier, slot } => {
                a[1] = 1.0;
                if slot >= 4 {
                    return Err("market slot invalid".into());
                }
                let id =
                    obs.public.market[tier.index()][slot as usize].ok_or("empty buy target")?;
                target = market[tier.index()][slot as usize] as i32;
                bought = Some(id);
                a[19 + tier.index()] = 1.0;
                a[43] = 1.0;
                a[46] = 1.0;
                a[48] = 1.0;
                a[49] = (obs.public.deck_counts[tier.index()] > 0) as u8 as f32;
            }
            Action::BuyReserved { slot } => {
                a[2] = 1.0;
                let r = obs
                    .private
                    .reserved
                    .get(slot as usize)
                    .ok_or("reserve slot invalid")?;
                target = reserved[slot as usize] as i32;
                bought = Some(r.card);
                a[19 + r.tier.index()] = 1.0;
                a[44] = 1.0;
                a[46] = 1.0;
                a[77] = r.from_deck as u8 as f32;
                reserve_count = reserve_count.checked_sub(1).ok_or("reserve underflow")?;
            }
            Action::ReserveMarket {
                tier,
                slot,
                give_back,
            } => {
                a[3] = 1.0;
                if slot >= 4 || obs.public.market[tier.index()][slot as usize].is_none() {
                    return Err("reserve market target invalid".into());
                }
                target = market[tier.index()][slot as usize] as i32;
                a[19 + tier.index()] = 1.0;
                a[43] = 1.0;
                a[45] = 1.0;
                a[48] = 1.0;
                a[49] = (obs.public.deck_counts[tier.index()] > 0) as u8 as f32;
                returned = give_back;
                take.gold = (obs.public.bank.gold > 0) as u8;
                reserve_count += 1;
            }
            Action::ReserveDeck { tier, give_back } => {
                a[4] = 1.0;
                if obs.public.deck_counts[tier.index()] == 0 {
                    return Err("empty reserve deck".into());
                }
                a[19 + tier.index()] = 1.0;
                a[23] = 1.0;
                a[45] = 1.0;
                returned = give_back;
                take.gold = (obs.public.bank.gold > 0) as u8;
                reserve_count += 1;
            }
            Action::ChooseNoble { noble } => {
                a[5] = 1.0;
                if !obs.public.pending_nobles.contains(&noble) {
                    return Err("noble not pending".into());
                }
                target = *nobles.get(&noble).ok_or("noble missing")? as i32;
                vp += 3;
                selected_noble = true;
            }
            Action::Pass => {
                a[6] = 1.0;
            }
        }
        if reserve_count > 3 {
            return Err("reserve capacity exceeded".into());
        }
        if let Some(id) = bought {
            let c = card(id);
            let mut gold = 0u16;
            for i in 0..5 {
                let need = c.cost[i].saturating_sub(bonus[i]);
                let paid = need.min(before[i]);
                after[i] -= paid;
                gold += (need - paid) as u16;
            }
            if gold > before[5] as u16 {
                return Err("unaffordable buy".into());
            }
            after[5] -= gold as u8;
            a[75] = gold as f32 / 5.0;
            bonus[c.bonus.index()] = bonus[c.bonus.index()]
                .checked_add(1)
                .ok_or("bonus overflow")?;
            a[36 + c.bonus.index()] = 1.0;
            vp += c.prestige as u16;
            let eligible: Vec<_> = obs
                .public
                .nobles
                .iter()
                .filter(|id| (0..5).all(|i| bonus[i] >= all_nobles()[id.index()].requirements[i]))
                .collect();
            a[51] = eligible.len() as f32 / 3.0;
            for id in &eligible {
                a[52 + id.index()] = 1.0;
            }
            if eligible.len() == 1 {
                vp += 3;
                selected_noble = true;
            } else if eligible.len() > 1 {
                a[68] = 1.0;
            }
        } else {
            let t = gems(take);
            let r = gems(returned);
            let bank = gems(obs.public.bank);
            for i in 0..6 {
                if t[i] > bank[i] {
                    return Err("taking unavailable tokens".into());
                }
                let held = before[i] as u16 + t[i] as u16;
                if r[i] as u16 > held {
                    return Err("return exceeds tokens".into());
                }
                after[i] = (held - r[i] as u16) as u8;
                a[7 + i] = t[i] as f32 / 4.0;
                a[13 + i] = r[i] as f32 / 10.0;
            }
        }
        if after.iter().map(|x| *x as u16).sum::<u16>() > 10 {
            return Err("post tokens over cap".into());
        }
        for i in 0..6 {
            a[24 + i] = after[i] as f32 / 10.0;
            a[30 + i] = (before[i] as f32 - after[i] as f32) / 10.0;
        }
        for i in 0..5 {
            a[62 + i] = bonus[i] as f32 / 20.0;
        }
        a[22] = (target >= 0) as u8 as f32;
        a[41] = (vp - me.prestige as u16) as f32 / 8.0;
        a[42] = vp as f32 / 20.0;
        a[47] = selected_noble as u8 as f32;
        a[50] = action.is_main_action() as u8 as f32;
        a[67] = (vp >= 15) as u8 as f32;
        a[69] = obs.public.end_game_triggered as u8 as f32;
        a[70] = reserve_count as f32 / 3.0;
        if target >= 0 {
            a[71] = entities[target as usize][67];
            a[72] = entities[target as usize][68];
        }
        a[73] = obs
            .public
            .nobles
            .iter()
            .map(|id| {
                (0..5)
                    .map(|i| {
                        all_nobles()[id.index()].requirements[i].saturating_sub(bonus[i]) as u16
                    })
                    .sum::<u16>()
            })
            .min()
            .unwrap_or(0) as f32
            / 20.0;
        a[74] = after[5] as f32 / 5.0;
        a[76] = (after.iter().map(|x| *x as u16).sum::<u16>() == 10) as u8 as f32;
        encoded.push(a);
        targets.push(target);
    }
    let result = EncodedState {
        entities,
        actions: encoded,
        targets,
    };
    result.validate()?;
    Ok(result)
}
#[cfg(test)]
#[path = "encoding_tests.rs"]
mod tests;
