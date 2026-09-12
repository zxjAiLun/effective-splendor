//! Exact policy identity recovered from the arena's `match-config.json`.
//!
//! The arena handshake reports a *runtime* name and version
//! (`effective-splendor-determinization-agent-v1@1`), which is the same for every
//! determinization invocation that did not pass `--runtime-name`. Two seats that
//! ran the same binary with `--max-nodes 2000` and `--max-nodes 1` therefore
//! look identical in the arena report even though they are different research
//! policies. Treating them as one participant fabricates self-matches and hides
//! real head-to-head results from Elo.
//!
//! This module recovers a policy identity from the *content* of the recorded
//! `match-config.json`: the program, the strategy entry point, and the argv
//! tokens that change what the policy does. Run-only details (output paths,
//! timeouts, the game id) are deliberately excluded, because two executions of
//! the same policy must collapse to one identity.
//!
//! Nothing here reads a filename. A report that has no recoverable configuration
//! stays [`AgentConfigurationResolutionV1::Unresolved`], and the seat is left
//! unmapped rather than guessed.

use crate::error::{Result, StudioLeagueError};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

/// Format tag of the arena harness configuration document.
pub const MATCH_CONFIG_FORMAT: &str = "effective-splendor-arena-config";

/// A single seat's exact policy identity, as recovered from its argv.
///
/// `key` is the canonical participant key: two seats are the same policy only
/// when this string matches. It is derived from the strategy entry point plus
/// the *semantic* tokens, with an explicit, ordered allow/deny list rather than
/// a substring guess.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub struct AgentPolicyIdentityV1 {
    /// The program invoked, reduced to its final path component (so a relocated
    /// checkout keeps the same identity). `None` when the config omitted it.
    pub program: Option<String>,
    /// The strategy entry point: the first non-flag token (e.g.
    /// `agent-determinization`, `-m`) or, for `python -m <module>`, the module.
    pub entry_point: String,
    /// The semantic strategy parameters, sorted by name so serialization is
    /// stable regardless of argv order.
    pub parameters: BTreeMap<String, String>,
}

impl AgentPolicyIdentityV1 {
    /// The canonical participant key. Deliberately stable and human-readable so
    /// a reviewer can see *why* two seats are the same policy.
    pub fn key(&self) -> String {
        let mut out = String::new();
        if let Some(program) = &self.program {
            out.push_str(program);
            out.push(':');
        }
        out.push_str(&self.entry_point);
        for (name, value) in &self.parameters {
            out.push('|');
            out.push_str(name);
            out.push('=');
            out.push_str(value);
        }
        out
    }
}

/// The recovered configuration identity for one seat.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum SeatConfigurationIdentityV1 {
    /// A policy identity was recovered from the recorded argv.
    Resolved(AgentPolicyIdentityV1),
    /// The configuration was present but did not name a strategy entry point
    /// this resolver understands; the seat is left unmapped rather than guessed.
    Unresolved { reason: String },
}

impl SeatConfigurationIdentityV1 {
    pub fn resolved(&self) -> Option<&AgentPolicyIdentityV1> {
        match self {
            SeatConfigurationIdentityV1::Resolved(identity) => Some(identity),
            SeatConfigurationIdentityV1::Unresolved { .. } => None,
        }
    }
}

/// One seat as recorded in `match-config.json`.
///
/// Only the fields needed to recover policy identity are modelled; unknown
/// fields are ignored so a future harness addition cannot silently change
/// identity.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct RawAgentCommand {
    #[serde(default)]
    program: Option<String>,
    #[serde(default)]
    args: Vec<String>,
}

/// The subset of `match-config.json` this resolver reads.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct RawMatchConfig {
    game_id: String,
    #[serde(default)]
    agents: Vec<RawAgentCommand>,
}

/// A fully resolved `match-config.json`: its game id (the join key to the arena
/// report) and the per-seat policy identity.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MatchConfigurationV1 {
    pub game_id: String,
    pub seats: Vec<SeatConfigurationIdentityV1>,
}

/// Parse and resolve a `match-config.json` document.
///
/// Returns `Ok(None)` when the document is not an arena config (a different
/// `format`, or the field is absent) so callers can keep scanning; returns
/// `Err` only when the document *claims* to be an arena config but is malformed.
pub fn parse_match_configuration(bytes: &[u8]) -> Result<Option<MatchConfigurationV1>> {
    let value: serde_json::Value = match serde_json::from_slice(bytes) {
        Ok(value) => value,
        Err(_) => return Ok(None),
    };
    match value.get("format").and_then(|v| v.as_str()) {
        Some(MATCH_CONFIG_FORMAT) => {}
        // Some harnesses omit `format`; fall back to shape detection.
        None if value.get("agents").is_some() && value.get("game_id").is_some() => {}
        _ => return Ok(None),
    }
    let raw: RawMatchConfig = serde_json::from_value(value).map_err(|e| {
        StudioLeagueError::Invalid(format!(
            "match-config.json is not a valid arena config: {e}"
        ))
    })?;
    if raw.game_id.trim().is_empty() {
        return Err(StudioLeagueError::Invalid(
            "match-config.json has an empty game_id".to_string(),
        ));
    }
    let seats = raw
        .agents
        .iter()
        .map(resolve_seat_identity)
        .collect::<Vec<_>>();
    Ok(Some(MatchConfigurationV1 {
        game_id: raw.game_id,
        seats,
    }))
}

/// Recover one seat's policy identity from its recorded argv.
fn resolve_seat_identity(agent: &RawAgentCommand) -> SeatConfigurationIdentityV1 {
    let args = &agent.args;
    let program = agent
        .program
        .as_deref()
        .map(|p| {
            // Reduce to the final component so a relocated checkout is the same
            // program. Never used as a content source on its own.
            p.replace('\\', "/")
                .rsplit('/')
                .next()
                .unwrap_or(p)
                .to_string()
        })
        .filter(|p| !p.is_empty());

    // The entry point is the first token that is not a flag and not the value of
    // the `-m` module switch.
    let entry_point = match args.first().map(String::as_str) {
        Some("-m") => args.get(1).cloned().unwrap_or_default(),
        Some(first) if !first.starts_with('-') => first.to_string(),
        _ => String::new(),
    };
    if entry_point.is_empty() {
        return SeatConfigurationIdentityV1::Unresolved {
            reason: "argv does not name a strategy entry point".to_string(),
        };
    }

    let parameters = semantic_parameters(args, &entry_point);
    SeatConfigurationIdentityV1::Resolved(AgentPolicyIdentityV1 {
        program,
        entry_point,
        parameters,
    })
}

/// Extract the argv tokens that change what the policy does.
///
/// The allow/exclude lists are explicit. Run-only details — output paths, time
/// budgets, seeds that select which games are played — are excluded so that two
/// executions of the same policy collapse to one identity.
fn semantic_parameters(args: &[String], entry_point: &str) -> BTreeMap<String, String> {
    // Switches whose *value* changes the resulting policy.
    //
    // `--runtime-name` / `--runtime-version` are the operator's declared labels
    // for the policy. They are part of the identity: two runs that declare
    // different runtime names are different named policies even if their search
    // budgets happen to coincide, and a runtime name is the only semantic label
    // older corpora carry. They are still combined with the search parameters
    // below so a name reused across budgets does not merge them.
    const MEANINGFUL: &[&str] = &[
        "--runtime-name",
        "--runtime-version",
        "--max-nodes",
        "--max-depth-turns",
        "--sample-count",
        "--attribution-profile",
        "--exploration-bias",
        "--model-id",
        "--device",
        "--catalog",
        "--heuristic-buy-overlay",
    ];
    // Switches that only describe where/how a run is recorded or scheduled.
    const RUN_ONLY: &[&str] = &["--stats-out", "--sample-seed", "--seed", "--log", "--out"];

    let mut parameters = BTreeMap::new();
    let mut index = 0;
    while index < args.len() {
        let token = args[index].as_str();
        if !token.starts_with("--") {
            index += 1;
            continue;
        }
        let name = token.trim_start_matches('-');
        let value = args.get(index + 1);
        if RUN_ONLY.contains(&token) {
            // Consume a value if the run-only switch takes one.
            if value.is_some() && !value.unwrap().starts_with("--") {
                index += 2;
            } else {
                index += 1;
            }
            continue;
        }
        if MEANINGFUL.contains(&token) {
            if let Some(value) = value.filter(|v| !v.starts_with("--")) {
                parameters.insert(name.to_string(), value.clone());
                index += 2;
                continue;
            }
            // A boolean-valued meaningful switch.
            parameters.insert(name.to_string(), "true".to_string());
        }
        index += 1;
    }

    // `python -m module` carries the entry point as the first token; record it as
    // a parameter so the key stays stable.
    if entry_point.starts_with("splendor_") {
        parameters.insert("entry-module".to_string(), entry_point.to_string());
    }
    parameters
}

/// True when the resolved parameters denote a diagnostic or deliberately altered
/// temporary configuration that must not enter the default rating pool.
///
/// The rule is deliberately narrow and exact rather than prefix-based. The
/// definitive signal is the attribution profile, and only the explicit `full`
/// profile is competitive; the arena omits the flag entirely for the default
/// competitive determinization policy, so both `None` and `Some("full")` are
/// treated as competitive.
pub fn is_diagnostic_configuration(identity: &AgentPolicyIdentityV1) -> bool {
    // 1. An explicit attribution profile is the study's own classifier. The
    //    canonical `AttributionProfile` has exactly one competitive value,
    //    `full`; every other value (`drop_*`, `only_*`, `zero_progress`,
    //    `engine_scale_*`, `equal_*`, `shift_*`) is a calibrated deviation
    //    studied in a comparison, so the match is a study match.
    if let Some(profile) = identity.parameters.get("attribution-profile") {
        if profile != "full" {
            return true;
        }
    }
    false
}

#[cfg(test)]
mod tests {
    use super::*;

    fn config(agents: &[&[&str]]) -> Vec<u8> {
        let seats: Vec<serde_json::Value> = agents
            .iter()
            .map(|args| {
                serde_json::json!({
                    "program": "E:\\proj\\target\\release\\splendor.exe",
                    "args": args,
                })
            })
            .collect();
        serde_json::to_vec_pretty(&serde_json::json!({
            "game_id": "s0-p3_n1_vs_m07-b10-s5800074-r1",
            "seed": 5800074,
            "handshake_timeout_ms": 10000,
            "move_timeout_ms": 60000,
            "shutdown_grace_ms": 2000,
            "agents": seats,
        }))
        .unwrap()
    }

    #[test]
    fn same_binary_different_max_nodes_are_distinct_policies() {
        // The exact S0 n1 vs M07 counterexample: same runtime, different budget.
        let bytes = config(&[
            &[
                "agent-determinization",
                "--sample-seed",
                "20260703",
                "--sample-count",
                "4",
                "--max-depth-turns",
                "1",
                "--max-nodes",
                "2000",
                "--stats-out",
                "E:\\out\\seat0.ndjson",
            ],
            &[
                "agent-determinization",
                "--sample-seed",
                "20260703",
                "--sample-count",
                "4",
                "--max-depth-turns",
                "1",
                "--max-nodes",
                "1",
                "--stats-out",
                "E:\\out\\seat1.ndjson",
            ],
        ]);
        let parsed = parse_match_configuration(&bytes).unwrap().unwrap();
        let a = parsed.seats[0].resolved().unwrap();
        let b = parsed.seats[1].resolved().unwrap();
        assert_ne!(a.key(), b.key(), "different budgets must differ");
        assert_eq!(a.parameters.get("max-nodes"), Some(&"2000".to_string()));
        assert_eq!(b.parameters.get("max-nodes"), Some(&"1".to_string()));
        // Run-only details must not appear in the identity.
        assert!(!a.key().contains("stats-out"));
        assert!(!a.key().contains("ndjson"));
    }

    #[test]
    fn run_only_differences_collapse_to_one_identity() {
        // Same policy, different output path and stats file only.
        let bytes = config(&[
            &[
                "agent-determinization",
                "--sample-count",
                "4",
                "--max-nodes",
                "2000",
                "--stats-out",
                "E:\\out\\a.ndjson",
            ],
            &[
                "agent-determinization",
                "--sample-count",
                "4",
                "--max-nodes",
                "2000",
                "--stats-out",
                "E:\\out\\b.ndjson",
            ],
        ]);
        let parsed = parse_match_configuration(&bytes).unwrap().unwrap();
        // Same key modulo the per-seat program path (identical here).
        assert_eq!(
            parsed.seats[0].resolved().unwrap().key(),
            parsed.seats[1].resolved().unwrap().key()
        );
    }

    #[test]
    fn runtime_name_participates_in_identity() {
        let bytes = config(&[
            &[
                "agent-determinization",
                "--max-nodes",
                "1",
                "--runtime-name",
                "m44a-full",
                "--runtime-version",
                "1",
            ],
            &[
                "agent-determinization",
                "--max-nodes",
                "1",
                "--runtime-name",
                "det-s4-d1-n1",
                "--runtime-version",
                "1",
            ],
        ]);
        let parsed = parse_match_configuration(&bytes).unwrap().unwrap();
        assert_ne!(
            parsed.seats[0].resolved().unwrap().key(),
            parsed.seats[1].resolved().unwrap().key()
        );
    }

    #[test]
    fn python_module_entry_point_is_resolved() {
        let bytes = config(&[&[
            "-m",
            "splendor_gpu.m35a_agent",
            "--model-id",
            "M25-D2-v2",
            "--catalog",
            "E:\\catalog.json",
            "--device",
            "cuda",
        ]]);
        let parsed = parse_match_configuration(&bytes).unwrap().unwrap();
        let identity = parsed.seats[0].resolved().unwrap();
        assert_eq!(identity.entry_point, "splendor_gpu.m35a_agent");
        assert_eq!(
            identity.parameters.get("model-id"),
            Some(&"M25-D2-v2".to_string())
        );
    }

    #[test]
    fn non_arena_documents_are_ignored() {
        let bytes = br#"{"format":"effective-splendor-arena-report","version":1}"#;
        assert!(parse_match_configuration(bytes).unwrap().is_none());
    }

    #[test]
    fn non_full_profiles_are_diagnostic() {
        // Every `AttributionProfile` value except `full` is a calibrated
        // deviation studied in a comparison (the M44A/M44B/M44C/M45A
        // ablation and scale-shift families), so it is a study match even
        // though the handshake runtime name may look like a normal agent.
        for profile in [
            "drop_score",
            "drop_engine",
            "drop_liquidity",
            "drop_convertibility",
            "zero_progress",
            "only_score",
            "engine_scale_50",
            "equal_drop_bonus",
            "shift_f4_e2",
        ] {
            let bytes = config(&[&[
                "agent-determinization",
                "--max-nodes",
                "1",
                "--attribution-profile",
                profile,
                "--runtime-name",
                "study",
                "--runtime-version",
                "1",
            ]]);
            let parsed = parse_match_configuration(&bytes).unwrap().unwrap();
            assert!(
                is_diagnostic_configuration(parsed.seats[0].resolved().unwrap()),
                "profile `{profile}` must be classified diagnostic"
            );
        }
    }

    #[test]
    fn full_profile_is_not_diagnostic() {
        let bytes = config(&[&[
            "agent-determinization",
            "--max-nodes",
            "1",
            "--attribution-profile",
            "full",
            "--runtime-name",
            "m44a-full",
            "--runtime-version",
            "1",
        ]]);
        let parsed = parse_match_configuration(&bytes).unwrap().unwrap();
        assert!(!is_diagnostic_configuration(
            parsed.seats[0].resolved().unwrap()
        ));
    }
}
