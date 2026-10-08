# Unified Match Metrics Standard

Status: FROZEN / AUTHORIZED (2026-09-27)
Format: `effective-splendor-batch-metrics-v1`
Engines:
- Batch Manifest Replays: `crates/splendor-cli/examples/s4_batch_metrics.rs`
- Human Player Benchmark: `crates/splendor-cli/examples/s4_human_metrics.rs`

## Overview

Per project requirement, all subsequent evaluations, pilots, self-play runs, and human matches must compute and persist this unified set of metrics. Single-winrate metrics are explicitly insufficient to capture tempo, card distributions, and noble interactions in Splendor.

## Standard Required Metrics

Every evaluation output must persist the following unified metrics in its output summary JSON:

1. **Game Level (Macro Tempo)**:
   - `total_games`: Total number of matches analyzed.
   - `total_plies`: Total action plies across all games.
   - `mean_plies`: Average plies per game (`total_plies / total_games`).
   - `mean_turns`: Average turns per game (`(plies + 1) / 2`).
   - `median_turns`, `min_turns`, `max_turns`, `std_turns`: Distribution of game duration.
   - `mean_victory_margin`: Average absolute prestige difference at endgame.
   - `close_games_margin_le_2_percent`: Percentage of matches decided by $\le 2$ prestige points.

2. **Seat & Player Breakdown (P0 First / P1 Second / Perspectives)**:
   - `wins`, `ties`, `losses`: Absolute match outcomes.
   - `win_rate_percent`: Win percentage (`wins / total_games * 100`).
   - `mean_prestige`: Average final score.
   - `vp_per_turn`: Scoring velocity per player turn (`total_score / total_player_turns`).
   - `vp_per_ply`: Scoring velocity per total ply (`total_score / total_plies`).
   - `mean_nobles`: Average nobles claimed per game.
   - `games_with_nobles_percent`: Percentage of games where at least 1 noble was claimed.

3. **Card Tier & VP Distribution (Micro Economy)**:
   - `mean_cards_by_vp`: BTreeMap of average cards acquired per game for each VP value:
     - `0-VP`: Pure engine development cards (Tier 1 & Tier 2).
     - `1-VP`: Tempo transition cards.
     - `2-VP`: Mid-game backbone cards.
     - `3-VP`: High-value rush cards.
     - `4-VP`: Heavy high-cost bombs.
     - `5-VP`: Endgame win-condition cards.

4. **Engine & Reserve Lifecycle**:
   - `mean_permanent_bonuses`: Average permanent gem discounts at endgame.
   - `mean_bonuses_by_color`: Breakdown of permanent discounts across White, Blue, Green, Red, Black.
   - `mean_reserves_acquired`: Average cards reserved per game.
   - `mean_reserves_bought`: Average reserved cards successfully purchased.
   - `mean_reserves_stranded`: Average unredeemed dead cards left in hand at endgame.
   - `reserve_redemption_rate_percent`: Percentage of reserved cards actually bought (`bought / acquired * 100`).

5. **Action Type Distribution**:
   - `buy_market`, `buy_reserved`, `take_tokens`, `reserve_market`, `reserve_deck`, `choose_noble`, `pass`.

## Reference Benchmark Baselines

- **Human Expert (13 Games)**: `benchmarks/human-expert-metrics-v1.json`
  - Win Rate: 76.92% (10W / 0T / 3L)
  - Mean Prestige: 15.00 VP
  - Scoring Velocity: 0.539 VP/turn (0.269 VP/ply)
  - 3+ VP Cards: 2.08 / game (3-VP: 1.08, 4-VP: 0.54, 5-VP: 0.46)
  - Reserve Redemption Rate: 88.9% (Stranded: 0.31 cards/game)
- **Heuristic v0.2.9 Pure Self-Play (5,000 Games)**: `benchmarks/m50-v029-selfplay-5k.metrics.json`
  - Seat 0 Win Rate: 54.58%, Seat 1 Win Rate: 44.66%
  - Mean Prestige: 13.86 VP (P0: 14.14, P1: 13.59)
  - Mean Duration: 27.70 turns (55.35 plies)
  - Scoring Velocity: 0.501 VP/turn (0.250 VP/ply)
  - 3+ VP Cards: 1.06 / game (3-VP: 0.67, 4-VP: 0.29, 5-VP: 0.10)
  - Reserve Redemption Rate: 66.8% (Stranded: 0.88 cards/game)

## Required Markdown tables and model orientation — 2026-10-02

This extends the frozen metrics contract with the owner's presentation requirement:
all subsequent model result/release/evolution documents must contain the detailed
tables themselves, including per-opponent results and both physical seats. A JSON
link or win-rate-only table is insufficient. JSON persistence remains required.

Minimum presentation tables:

1. Per-opponent games/seed blocks/W-D-L/pure win rate/half-draw score rate/paired CI;
   candidate and opponent final VP; a separate first/second-seat breakdown.
2. Macro duration (plies, legacy rounds, min/median/max/population SD, victory
   margin and close-game fraction) and both players' VP per decision/Main action/ply.
3. Both players' cards by VP 0..5, discounts by color, noble mean/coverage, reserve
   acquisition/purchase/terminal unbought count/redemption rate.
4. All seven action counts and shares, with the percentage denominator stated.
5. Observed timings, clock scope, model/opponent/runtime identities, seed/protocol
   and result/config/replay-source hashes. Mark unavailable measurements explicitly.

`s4_batch_metrics` outputs physical seats. Split manifests by candidate identity,
opponent and candidate seat, select the correct physical seat, then merge by model
identity. Pooling P0 and calling it the candidate mixes both policies and is invalid.
Mean fields are game weighted; VP velocities and redemption/action rates must use
summed numerators and denominators, not an unweighted mean of subgroup percentages.

Actual legacy code uses integer `ceil(plies/2)` for `mean_turns` and counts
`choose_noble` as a decision for `vp_per_turn`. This is not an extra Main turn.
Preserve those existing metrics, label their denominator, and also report Main
counts/velocity separately when available. The old `(plies+1)/2` wording should
be read as the implementation's integer division, not fractional half turns.

Tie-aware score rate is `(wins + 0.5 * draws) / games`; pure win rate is
`wins / games`. Outcomes follow verified winners/ranks, not equal VP alone.
Terminal unbought reserves describe retained cards; they are not automatically
wasted actions or successful denial. Post-hoc behavior tables are descriptive;
they do not establish a learned style, causality, or an additional promotion gate.

## Reading changes and acceptance gates — 2026-10-02

Show the main interpretation before the full metrics: artifact validity,
competitive results and style evidence are separate conclusions. Provide a
compact matched baseline → candidate → delta view with units, signed changes,
bold emphasis and arrows. An optional color view must preserve textual meaning.
Development samples and independent acceptance samples need explicit labels;
do not combine them or compare different opponents as a model effect.

For every acceptance gate, state the frozen threshold and whether it applies to
an estimate or confidence bound. Label score-rate changes in percentage points,
absolute score rates in percent, and normalized style utilities in their own
units. Record the original PASS/FAIL plus its meaning: a failed confidence bound
may leave a tolerance unconfirmed without proving harm. Descriptive arrows show
direction, not desirability or statistical significance. Style anchoring may
trade some strength/economy within a predeclared tolerance; all metrics need not
increase. Future changes to primary style measures or hard/diagnostic gate policy
must be frozen before new sampling; they cannot relabel a completed experiment.
