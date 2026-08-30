//! Evaluation report schema and pure aggregation.
//!
//! [`EvaluationReportV1`] collects one [`EvaluationMatchRecordV1`] per scheduled
//! match plus per-agent [`AgentAggregateV1`] (with per-seat breakdowns). The
//! canonical report uses only integer tallies — no `f32`/`f64`. Averages (mean
//! rank, mean score) are derived by the *consumer* as `sum / completed_matches`
//! and are intentionally never serialized, so floating-point formatting never
//! becomes a compatibility surface.
//!
//! [`aggregate`] is a pure function over `(plan, records)`. The canonical
//! schedule is derived *inside* `aggregate` from the plan via
//! [`expand_schedule`](crate::expand_schedule); callers cannot inject an
//! arbitrary schedule, so a report's `plan_hash`, `scheduled_matches`, and
//! per-seat tallies are always bound to the plan's own canonical schedule.
//! It rejects malformed input (missing/duplicate/extra records, game-id or
//! seat-mapping mismatches, length/winner/aborted-seat violations) instead of
//! panicking, and its output is independent of the order in which records are
//! supplied.

use std::collections::HashMap;

use splendor_arena::ArenaOutcomeV1;

use crate::error::EvaluationError;
use crate::plan::{evaluation_plan_hash_v1, EvaluationPlanV1, EVALUATION_VERSION};
use crate::schedule::{expand_schedule, EvaluationMatchSpecV1};

/// Top-level report format tag written into every evaluation report.
pub const EVALUATION_REPORT_FORMAT: &str = "effective-splendor-evaluation-report";

/// One match's contribution to the report.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EvaluationMatchRecordV1 {
    /// Matches the schedule's `match_index`.
    pub match_index: u32,
    /// Must equal the scheduled slot's `game_id`.
    pub game_id: String,
    /// Must equal the scheduled slot's `seed_index`.
    pub seed_index: u32,
    /// Must equal the scheduled slot's `rotation`.
    pub rotation: u8,
    /// Must equal the scheduled slot's seat→agent mapping.
    pub agent_ids_by_seat: Vec<String>,
    /// Authoritative arena outcome for this match.
    pub outcome: ArenaOutcomeV1,
}

/// Per-seat tally for one agent.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SeatAggregateV1 {
    /// Seat index (0-based).
    pub seat: u8,
    /// Matches where this agent was scheduled at this seat.
    pub scheduled_matches: u32,
    /// Completed matches at this seat.
    pub completed_matches: u32,
    /// Aborted matches at this seat.
    pub aborted_matches: u32,
    /// Wins recorded at this seat.
    pub wins: u32,
    /// Sum of ranks at this seat (lower is better).
    pub rank_sum: u64,
    /// Sum of scores at this seat.
    pub score_sum: u64,
    /// Faults attributed to this agent at this seat.
    pub faults_caused: u32,
}

/// Per-agent aggregate across the whole evaluation.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AgentAggregateV1 {
    /// Agent identifier (from the plan).
    pub agent_id: String,
    /// Matches where this agent was scheduled (all of them, under rotation).
    pub scheduled_matches: u32,
    /// Completed matches.
    pub completed_matches: u32,
    /// Aborted matches.
    pub aborted_matches: u32,
    /// Wins (shared winners each count once).
    pub wins: u32,
    /// Sum of ranks (lower is better).
    pub rank_sum: u64,
    /// Sum of scores.
    pub score_sum: u64,
    /// Faults attributed to this agent.
    pub faults_caused: u32,
    /// Per-seat breakdown, ordered by seat index.
    pub by_seat: Vec<SeatAggregateV1>,
}

/// The version-1 evaluation report.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EvaluationReportV1 {
    /// Always [`EVALUATION_REPORT_FORMAT`].
    pub format: String,
    /// Always [`EVALUATION_VERSION`].
    pub version: u32,
    /// Echo of the plan's `evaluation_id`.
    pub evaluation_id: String,
    /// SHA-256 of the (validated) plan this report was built from.
    pub plan_hash: String,
    /// Total scheduled matches.
    pub scheduled_matches: u32,
    /// One record per scheduled match, in `match_index` order.
    pub records: Vec<EvaluationMatchRecordV1>,
    /// Per-agent aggregates, in plan declaration order.
    pub agents: Vec<AgentAggregateV1>,
}

/// Aggregate a set of match records against a plan.
///
/// The canonical schedule is derived *inside* this function from `plan` via
/// [`expand_schedule`](crate::expand_schedule). Callers pass only the plan and
/// the per-match records; they cannot inject an arbitrary schedule, so the
/// resulting report is always bound to the plan's own canonical schedule (and
/// therefore to its [`plan_hash`](EvaluationReportV1::plan_hash)).
///
/// Validation performed against the canonical schedule:
/// - every `match_index` exists in the schedule and appears exactly once;
/// - every scheduled match has a record (no missing, no extra);
/// - each record's `game_id`, `seed_index`, `rotation`, and seat→agent mapping
///   match its scheduled slot;
/// - completed outcomes carry `scores`/`ranks` of length equal to the player
///   count, and every winner seat is in bounds and distinct;
/// - aborted outcomes name a seat within bounds.
///
/// Aggregation semantics:
/// - **Completed**: every seat's `completed_matches += 1`, its `score_sum`/`rank_sum`
///   accumulate; each winner (ties included) gets `wins += 1`.
/// - **Aborted**: every participant's `aborted_matches += 1`; only the attributed
///   seat's agent gets `faults_caused += 1`. No score/rank/win is fabricated.
pub fn aggregate(
    plan: &EvaluationPlanV1,
    records: &[EvaluationMatchRecordV1],
) -> Result<EvaluationReportV1, EvaluationError> {
    let specs = expand_schedule(plan)?;
    aggregate_canonical(plan, &specs, records)
}

/// Internal aggregation over an already-canonical schedule. Private so no
/// external caller can bypass [`expand_schedule`] and inject an arbitrary
/// schedule. `specs` MUST be exactly `expand_schedule(plan)` — the public
/// [`aggregate`] guarantees this.
fn aggregate_canonical(
    plan: &EvaluationPlanV1,
    specs: &[EvaluationMatchSpecV1],
    records: &[EvaluationMatchRecordV1],
) -> Result<EvaluationReportV1, EvaluationError> {
    let plan_hash = evaluation_plan_hash_v1(plan)?.to_string();
    let player_count = plan.agents.len();

    // Index specs by match_index for O(1) lookup and duplicate/missing checks.
    let mut spec_pos: HashMap<u32, usize> = HashMap::new();
    for (i, spec) in specs.iter().enumerate() {
        spec_pos.insert(spec.match_index, i);
    }

    let mut seen: std::collections::HashSet<u32> = std::collections::HashSet::new();
    let mut ordered: Vec<&EvaluationMatchRecordV1> = Vec::with_capacity(records.len());
    for record in records {
        let pos = *spec_pos
            .get(&record.match_index)
            .ok_or(EvaluationError::UnknownMatchIndex(record.match_index))?;
        if !seen.insert(record.match_index) {
            return Err(EvaluationError::DuplicateRecord(record.match_index));
        }
        let spec = &specs[pos];
        if record.game_id != spec.arena_config.game_id {
            return Err(EvaluationError::RecordGameIdMismatch {
                match_index: record.match_index,
                expected: spec.arena_config.game_id.clone(),
                found: record.game_id.clone(),
            });
        }
        if record.agent_ids_by_seat != spec.agent_ids_by_seat
            || record.seed_index != spec.seed_index
            || record.rotation != spec.rotation
        {
            return Err(EvaluationError::RecordSeatMappingMismatch {
                match_index: record.match_index,
            });
        }
        ordered.push(record);
    }
    for spec in specs {
        if !seen.contains(&spec.match_index) {
            return Err(EvaluationError::MissingRecord(spec.match_index));
        }
    }

    // Agent aggregates in plan declaration order → deterministic output
    // independent of record iteration order.
    let mut agent_index: HashMap<&str, usize> = HashMap::new();
    let mut agents: Vec<AgentAggregateV1> = Vec::with_capacity(player_count);
    let seat_scheduled = plan.game_seeds.len() as u32;
    for agent in &plan.agents {
        agent_index.insert(agent.id.as_str(), agents.len());
        let by_seat = (0..player_count)
            .map(|seat| SeatAggregateV1 {
                seat: seat as u8,
                scheduled_matches: seat_scheduled,
                completed_matches: 0,
                aborted_matches: 0,
                wins: 0,
                rank_sum: 0,
                score_sum: 0,
                faults_caused: 0,
            })
            .collect();
        agents.push(AgentAggregateV1 {
            agent_id: agent.id.clone(),
            scheduled_matches: specs.len() as u32,
            completed_matches: 0,
            aborted_matches: 0,
            wins: 0,
            rank_sum: 0,
            score_sum: 0,
            faults_caused: 0,
            by_seat,
        });
    }

    // Fail-closed lookup of an agent's aggregate index from an untrusted record
    // id. The canonical-schedule + seat-mapping checks above guarantee every
    // record id is a plan agent id, so this never fails on the happy path — but
    // the aggregator must not panic on a `HashMap` Index miss.
    let agent_index_of = |id: &str, match_index: u32| -> Result<usize, EvaluationError> {
        agent_index
            .get(id)
            .copied()
            .ok_or_else(|| EvaluationError::UnknownAgentInRecord {
                match_index,
                agent_id: id.to_string(),
            })
    };

    ordered.sort_by_key(|r| r.match_index);
    for record in ordered {
        let n = record.agent_ids_by_seat.len();
        match &record.outcome {
            ArenaOutcomeV1::Completed { result, .. } => {
                if result.scores.len() != n || result.ranks.len() != n {
                    return Err(EvaluationError::OutcomeLengthMismatch {
                        match_index: record.match_index,
                        expected: n,
                        found: result.scores.len(),
                    });
                }
                // Validate every winner BEFORE accumulating: out-of-bounds or
                // duplicate winner seats must return an error, never panic on
                // an unchecked `agent_ids_by_seat[seat]` index.
                let mut winner_seats: std::collections::HashSet<u8> =
                    std::collections::HashSet::new();
                for winner in &result.winners {
                    let seat = winner.0;
                    if (seat as usize) >= n {
                        return Err(EvaluationError::WinnerSeatOutOfBounds {
                            match_index: record.match_index,
                            seat,
                            player_count: n as u8,
                        });
                    }
                    if !winner_seats.insert(seat) {
                        return Err(EvaluationError::DuplicateWinnerSeat {
                            match_index: record.match_index,
                            seat,
                        });
                    }
                }
                for seat in 0..n {
                    let ai = agent_index_of(&record.agent_ids_by_seat[seat], record.match_index)?;
                    agents[ai].by_seat[seat].completed_matches += 1;
                    agents[ai].by_seat[seat].score_sum += result.scores[seat] as u64;
                    agents[ai].by_seat[seat].rank_sum += result.ranks[seat] as u64;
                    agents[ai].completed_matches += 1;
                    agents[ai].score_sum += result.scores[seat] as u64;
                    agents[ai].rank_sum += result.ranks[seat] as u64;
                }
                for winner in &result.winners {
                    let seat = winner.0 as usize;
                    let ai = agent_index_of(&record.agent_ids_by_seat[seat], record.match_index)?;
                    agents[ai].wins += 1;
                    agents[ai].by_seat[seat].wins += 1;
                }
            }
            ArenaOutcomeV1::Aborted { seat, .. } => {
                if (*seat as usize) >= n {
                    return Err(EvaluationError::AbortedSeatOutOfBounds {
                        match_index: record.match_index,
                        seat: *seat,
                        player_count: n as u8,
                    });
                }
                for s in 0..n {
                    let ai = agent_index_of(&record.agent_ids_by_seat[s], record.match_index)?;
                    agents[ai].aborted_matches += 1;
                    agents[ai].by_seat[s].aborted_matches += 1;
                }
                let ai = agent_index_of(
                    &record.agent_ids_by_seat[*seat as usize],
                    record.match_index,
                )?;
                agents[ai].faults_caused += 1;
                agents[ai].by_seat[*seat as usize].faults_caused += 1;
            }
            ArenaOutcomeV1::Truncated { .. } => {
                // Evaluation reports aggregate terminal games; a truncated
                // (ply-capped) game has no result to aggregate.
                return Err(EvaluationError::OutcomeLengthMismatch {
                    match_index: record.match_index,
                    expected: n,
                    found: 0,
                });
            }
        }
    }

    let mut report_records: Vec<EvaluationMatchRecordV1> = records
        .iter()
        .map(|r| EvaluationMatchRecordV1 {
            match_index: r.match_index,
            game_id: r.game_id.clone(),
            seed_index: r.seed_index,
            rotation: r.rotation,
            agent_ids_by_seat: r.agent_ids_by_seat.clone(),
            outcome: r.outcome.clone(),
        })
        .collect();
    report_records.sort_by_key(|r| r.match_index);

    Ok(EvaluationReportV1 {
        format: EVALUATION_REPORT_FORMAT.to_string(),
        version: EVALUATION_VERSION,
        evaluation_id: plan.evaluation_id.clone(),
        plan_hash,
        scheduled_matches: specs.len() as u32,
        records: report_records,
        agents,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::schedule::expand_schedule;
    use splendor_arena::{AgentFault, ArenaOutcomeV1, ArenaPhase};
    use splendor_core::{GameResult, PlayerId, TerminalReason};

    /// Build a completed record matching `spec`, where seat 0 wins.
    fn completed_record(
        match_index: u32,
        spec: &EvaluationMatchSpecV1,
        scores: &[u8],
        ranks: &[u8],
        winners: &[u8],
    ) -> EvaluationMatchRecordV1 {
        let result = GameResult {
            scores: scores.to_vec(),
            ranks: ranks.to_vec(),
            winners: winners.iter().map(|&s| PlayerId(s)).collect(),
            reason: TerminalReason::PrestigeThreshold,
        };
        EvaluationMatchRecordV1 {
            match_index,
            game_id: spec.arena_config.game_id.clone(),
            seed_index: spec.seed_index,
            rotation: spec.rotation,
            agent_ids_by_seat: spec.agent_ids_by_seat.clone(),
            outcome: ArenaOutcomeV1::completed(result, 10, "deadbeef".repeat(8)),
        }
    }

    /// Build an aborted record matching `spec`, attributing `seat`.
    fn aborted_record(
        match_index: u32,
        spec: &EvaluationMatchSpecV1,
        seat: u8,
    ) -> EvaluationMatchRecordV1 {
        EvaluationMatchRecordV1 {
            match_index,
            game_id: spec.arena_config.game_id.clone(),
            seed_index: spec.seed_index,
            rotation: spec.rotation,
            agent_ids_by_seat: spec.agent_ids_by_seat.clone(),
            outcome: ArenaOutcomeV1::aborted(
                seat,
                ArenaPhase::ActionRequest,
                AgentFault::ActionTimeout,
                Some(1),
                0,
            ),
        }
    }

    /// One record per spec: seat 0 wins with score 15 / rank 1, seat s>0 with
    /// score 5 / rank 2.
    fn build_records(specs: &[EvaluationMatchSpecV1]) -> Vec<EvaluationMatchRecordV1> {
        specs
            .iter()
            .map(|spec| {
                let n = spec.agent_ids_by_seat.len();
                let scores: Vec<u8> = (0..n).map(|s| if s == 0 { 15 } else { 5 }).collect();
                let ranks: Vec<u8> = (0..n).map(|s| if s == 0 { 1 } else { 2 }).collect();
                completed_record(spec.match_index, spec, &scores, &ranks, &[0])
            })
            .collect()
    }

    #[test]
    fn completed_results_aggregate_wins_ranks_scores() {
        let plan = crate::make_plan(&["A", "B"], &[1, 2]);
        let specs = expand_schedule(&plan).unwrap();
        let records = build_records(&specs);
        let report = aggregate(&plan, &records).unwrap();

        assert_eq!(report.scheduled_matches, 4);
        let a = report.agents.iter().find(|a| a.agent_id == "A").unwrap();
        let b = report.agents.iter().find(|a| a.agent_id == "B").unwrap();
        // Under rotation each agent wins exactly half the matches.
        assert_eq!(a.wins, 2);
        assert_eq!(b.wins, 2);
        // A: seat0 (15) in rot0 seeds + seat1 (5) in rot1 seeds => 40 total.
        assert_eq!(a.score_sum, 40);
        assert_eq!(a.rank_sum, 6);
        assert_eq!(b.score_sum, 40);
        assert_eq!(b.rank_sum, 6);
        assert_eq!(a.completed_matches, 4);
        assert_eq!(b.completed_matches, 4);
    }

    #[test]
    fn shared_winners_are_counted_for_each_winner() {
        let plan = crate::make_plan(&["A", "B"], &[1]);
        let specs = expand_schedule(&plan).unwrap();
        let mut records = build_records(&specs);
        // Both matches are ties: every seat wins its own match.
        for spec in &specs {
            let idx = records
                .iter()
                .position(|r| r.match_index == spec.match_index)
                .unwrap();
            records[idx] = EvaluationMatchRecordV1 {
                match_index: spec.match_index,
                game_id: spec.arena_config.game_id.clone(),
                seed_index: spec.seed_index,
                rotation: spec.rotation,
                agent_ids_by_seat: spec.agent_ids_by_seat.clone(),
                outcome: ArenaOutcomeV1::completed(
                    GameResult {
                        scores: vec![10, 10],
                        ranks: vec![1, 1],
                        winners: vec![PlayerId(0), PlayerId(1)],
                        reason: TerminalReason::PrestigeThreshold,
                    },
                    10,
                    "deadbeef".repeat(8),
                ),
            };
        }
        let report = aggregate(&plan, &records).unwrap();
        let a = report.agents.iter().find(|a| a.agent_id == "A").unwrap();
        let b = report.agents.iter().find(|a| a.agent_id == "B").unwrap();
        // Each agent is the seat-0 winner in exactly one of the two matches.
        assert_eq!(a.wins, 2);
        assert_eq!(b.wins, 2);
        assert_eq!(a.score_sum, 20);
        assert_eq!(b.score_sum, 20);
    }

    #[test]
    fn aborted_match_counts_fault_for_attributed_agent() {
        let plan = crate::make_plan(&["A", "B"], &[1]);
        let specs = expand_schedule(&plan).unwrap();
        let mut records = build_records(&specs);
        // Both matches aborted at seat 0: in [A,B] A faults, in [B,A] B faults.
        records[0] = aborted_record(specs[0].match_index, &specs[0], 0);
        records[1] = aborted_record(specs[1].match_index, &specs[1], 0);
        let report = aggregate(&plan, &records).unwrap();
        let a = report.agents.iter().find(|a| a.agent_id == "A").unwrap();
        let b = report.agents.iter().find(|a| a.agent_id == "B").unwrap();
        // Every participant is counted in every aborted match...
        assert_eq!(a.aborted_matches, 2);
        assert_eq!(b.aborted_matches, 2);
        // ...but only the seat-0 agent in each match is attributed the fault.
        assert_eq!(a.faults_caused, 1);
        assert_eq!(b.faults_caused, 1);
        assert_eq!(a.completed_matches, 0);
        assert_eq!(a.score_sum, 0);
        assert_eq!(a.wins, 0);
    }

    #[test]
    fn aborted_match_does_not_fabricate_scores() {
        let plan = crate::make_plan(&["A", "B"], &[1, 2]);
        let specs = expand_schedule(&plan).unwrap();
        let records: Vec<EvaluationMatchRecordV1> = specs
            .iter()
            .map(|spec| aborted_record(spec.match_index, spec, 0))
            .collect();
        let report = aggregate(&plan, &records).unwrap();
        for agent in &report.agents {
            assert_eq!(agent.completed_matches, 0);
            assert_eq!(agent.score_sum, 0);
            assert_eq!(agent.rank_sum, 0);
            assert_eq!(agent.wins, 0);
            assert_eq!(agent.aborted_matches, report.scheduled_matches);
        }
        // Seat 0 faults in every match; A sits at seat 0 in half of them.
        let a = report.agents.iter().find(|a| a.agent_id == "A").unwrap();
        assert_eq!(a.faults_caused, report.scheduled_matches / 2);
    }

    #[test]
    fn record_schedule_mismatch_is_rejected() {
        let plan = crate::make_plan(&["A", "B"], &[1]);
        let specs = expand_schedule(&plan).unwrap();

        // Wrong game_id.
        let mut rec = build_records(&specs);
        rec[0].game_id = "tampered".to_string();
        assert!(matches!(
            aggregate(&plan, &rec),
            Err(EvaluationError::RecordGameIdMismatch { .. })
        ));

        // Wrong seat mapping.
        let mut rec2 = build_records(&specs);
        // specs[1] = [B,A]; claim [A,B].
        rec2[1].agent_ids_by_seat = vec!["A".to_string(), "B".to_string()];
        assert!(matches!(
            aggregate(&plan, &rec2),
            Err(EvaluationError::RecordSeatMappingMismatch { .. })
        ));
    }

    #[test]
    fn aggregation_is_independent_of_map_iteration_order() {
        let plan = crate::make_plan(&["A", "B", "C"], &[1, 2]);
        let specs = expand_schedule(&plan).unwrap();
        let records = build_records(&specs);
        let sorted = aggregate(&plan, &records).unwrap();

        // Rotate the records vector to emulate a different submission order.
        let mut shuffled = records.clone();
        shuffled.rotate_left(2);
        let rotated = aggregate(&plan, &shuffled).unwrap();
        assert_eq!(sorted, rotated);
    }

    #[test]
    fn canonical_report_round_trips_strictly() {
        let plan = crate::make_plan(&["A", "B"], &[1, 2]);
        let specs = expand_schedule(&plan).unwrap();
        let records = build_records(&specs);
        let report = aggregate(&plan, &records).unwrap();

        let json = serde_json::to_string(&report).unwrap();
        let back: EvaluationReportV1 = serde_json::from_str(&json).unwrap();
        assert_eq!(report, back);

        // Unknown top-level field must be rejected.
        let noisy = json.trim_end_matches('}').to_string() + ",\"extra\":1}";
        assert!(serde_json::from_str::<EvaluationReportV1>(&noisy).is_err());
    }

    // ----- Blocker 1: aggregate binds the canonical schedule -----

    #[test]
    fn empty_records_are_missing_against_canonical_schedule() {
        // A valid, non-empty plan with zero records must NOT yield an empty
        // report. The canonical schedule has matches 0..N, so the first missing
        // one (match_index 0) is reported.
        let plan = crate::make_plan(&["A", "B"], &[1, 2]);
        let records: Vec<EvaluationMatchRecordV1> = vec![];
        let err = aggregate(&plan, &records).unwrap_err();
        assert!(matches!(err, EvaluationError::MissingRecord(0)));
    }

    #[test]
    fn partial_records_are_rejected() {
        // Submit only the first match's record; the second scheduled match is
        // missing → MissingRecord(1).
        let plan = crate::make_plan(&["A", "B"], &[1]);
        let specs = expand_schedule(&plan).unwrap();
        let partial = vec![build_records(&specs)[0].clone()];
        let err = aggregate(&plan, &partial).unwrap_err();
        assert!(matches!(err, EvaluationError::MissingRecord(1)));
    }

    #[test]
    fn duplicate_record_is_rejected() {
        let plan = crate::make_plan(&["A", "B"], &[1]);
        let specs = expand_schedule(&plan).unwrap();
        let mut records = build_records(&specs);
        // Duplicate the first record (match_index 0).
        records.push(records[0].clone());
        let err = aggregate(&plan, &records).unwrap_err();
        assert!(matches!(err, EvaluationError::DuplicateRecord(0)));
    }

    #[test]
    fn unknown_match_index_is_rejected() {
        let plan = crate::make_plan(&["A", "B"], &[1]);
        let specs = expand_schedule(&plan).unwrap();
        let mut records = build_records(&specs);
        // Point the second record at a match_index that does not exist in the
        // 2-match schedule (only 0 and 1 exist).
        records[1].match_index = 99;
        let err = aggregate(&plan, &records).unwrap_err();
        assert!(matches!(err, EvaluationError::UnknownMatchIndex(99)));
    }

    #[test]
    fn canonical_schedule_is_derived_from_plan() {
        // The public API accepts only (plan, records); the schedule is derived
        // internally. Records built from expand_schedule(plan) must aggregate
        // successfully, and the report's scheduled_matches must equal the
        // canonical schedule length — proving the binding, not a caller-supplied
        // schedule.
        let plan = crate::make_plan(&["A", "B", "C"], &[1, 2]);
        let canonical = expand_schedule(&plan).unwrap();
        let records = build_records(&canonical);
        let report = aggregate(&plan, &records).unwrap();
        assert_eq!(report.scheduled_matches, canonical.len() as u32);
        // plan_hash is real (non-empty) and bound to the same plan.
        assert_eq!(report.plan_hash.len(), 64);
        // Every agent is scheduled for every match under rotation.
        for agent in &report.agents {
            assert_eq!(agent.scheduled_matches, canonical.len() as u32);
        }
    }

    // ----- Blocker 2: completed winner bounds never panic -----

    #[test]
    fn completed_winner_out_of_bounds_is_rejected_without_panic() {
        let plan = crate::make_plan(&["A", "B"], &[1]);
        let specs = expand_schedule(&plan).unwrap();
        // Submit a COMPLETE record set so the canonical-schedule missing-record
        // check passes; replace match_index 0 with a record whose winner
        // references seat 255 (out of bounds for a 2-player match). scores/ranks
        // lengths match the player count, so the length check passes — the
        // winner bounds check must reject it without ever indexing
        // agent_ids_by_seat[255].
        let mut records = build_records(&specs);
        records[0] = completed_record(specs[0].match_index, &specs[0], &[15, 5], &[1, 2], &[255]);
        let err = aggregate(&plan, &records).unwrap_err();
        assert!(matches!(
            err,
            EvaluationError::WinnerSeatOutOfBounds {
                match_index: 0,
                seat: 255,
                player_count: 2
            }
        ));
    }

    #[test]
    fn duplicate_winner_seat_is_rejected() {
        let plan = crate::make_plan(&["A", "B"], &[1]);
        let specs = expand_schedule(&plan).unwrap();
        // Complete record set; match_index 0 names seat 0 as winner twice —
        // must be rejected, not double-counted.
        let mut records = build_records(&specs);
        records[0] = completed_record(specs[0].match_index, &specs[0], &[15, 5], &[1, 2], &[0, 0]);
        let err = aggregate(&plan, &records).unwrap_err();
        assert!(matches!(
            err,
            EvaluationError::DuplicateWinnerSeat {
                match_index: 0,
                seat: 0
            }
        ));
    }
}
