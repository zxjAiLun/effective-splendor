//! Profiling wrappers for live operational measurement of S3 and heuristic.
//!
//! Frozen contract (docs/s3-operational-profile.md):
//! - Same underlying policy code
//! - Same root seed and RNG consumption
//! - Exact same action choices
//! - Wrap `Instant::now() -> choose_action() -> elapsed -> emit JSONL`
//! - Telemetry emitted AFTER action selection (no policy interference)

use std::fs::OpenOptions;
use std::io::{self, BufRead, BufReader, BufWriter, Write};
use std::path::PathBuf;
use std::time::Instant;

use serde::{Deserialize, Serialize};
use splendor_agent::{
    run_agent, AgentError, AgentIdentity, AgentPolicy, DecisionContext, HeuristicAgentPolicy,
    HEURISTIC_AGENT_NAME, HEURISTIC_AGENT_VERSION,
};
use splendor_core::Action;
use splendor_determinization_agent::s3_agent::{
    S3RolloutAgentPolicy, S3_AGENT_NAME, S3_ROOT_SEED,
};

/// JSONL telemetry line schema for operational profile decisions.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DecisionTelemetryRecord {
    pub game_id: String,
    pub request_id: u64,
    pub seat: u8,
    pub decide_micros: u64,
    pub path: String,
    #[serde(rename = "override")]
    pub is_override: bool,
}

/// Profiling wrapper around `S3RolloutAgentPolicy`.
pub struct ProfiledS3Policy<W: Write> {
    inner: S3RolloutAgentPolicy,
    sink: W,
}

impl<W: Write> ProfiledS3Policy<W> {
    pub fn new(inner: S3RolloutAgentPolicy, sink: W) -> Self {
        Self { inner, sink }
    }
}

impl<W: Write> AgentPolicy for ProfiledS3Policy<W> {
    type Error = splendor_determinization_agent::DeterminizationAgentError;

    fn choose_action(&mut self, context: DecisionContext<'_>) -> Result<Action, Self::Error> {
        let game_id = context.meta.game_id.clone();
        let request_id = context.meta.request_id;
        let seat = context.meta.recipient_seat.0;

        let prior_rollout = self.inner.rollout_comparisons;
        let prior_override = self.inner.rollout_overrides;
        let prior_fallback = self.inner.ply_cap_fallbacks;

        let t0 = Instant::now();
        let result = self.inner.choose_action(context);
        let elapsed = t0.elapsed().as_micros() as u64;

        if result.is_ok() {
            let (path, is_override) = if self.inner.rollout_comparisons > prior_rollout {
                (
                    "rollout_comparison".to_string(),
                    self.inner.rollout_overrides > prior_override,
                )
            } else if self.inner.ply_cap_fallbacks > prior_fallback {
                ("ply_cap_fallback".to_string(), false)
            } else {
                ("heuristic_equivalent_fast_path".to_string(), false)
            };

            let record = DecisionTelemetryRecord {
                game_id,
                request_id,
                seat,
                decide_micros: elapsed,
                path,
                is_override,
            };
            if let Ok(line) = serde_json::to_string(&record) {
                let _ = writeln!(self.sink, "{line}");
                let _ = self.sink.flush();
            }
        }

        result
    }
}

/// Profiling wrapper around `HeuristicAgentPolicy`.
pub struct ProfiledHeuristicPolicy<W: Write> {
    inner: HeuristicAgentPolicy,
    sink: W,
}

impl<W: Write> ProfiledHeuristicPolicy<W> {
    pub fn new(inner: HeuristicAgentPolicy, sink: W) -> Self {
        Self { inner, sink }
    }
}

impl<W: Write> AgentPolicy for ProfiledHeuristicPolicy<W> {
    type Error = std::convert::Infallible;

    fn choose_action(&mut self, context: DecisionContext<'_>) -> Result<Action, Self::Error> {
        let game_id = context.meta.game_id.clone();
        let request_id = context.meta.request_id;
        let seat = context.meta.recipient_seat.0;

        let t0 = Instant::now();
        let result = self.inner.choose_action(context);
        let elapsed = t0.elapsed().as_micros() as u64;

        if result.is_ok() {
            let record = DecisionTelemetryRecord {
                game_id,
                request_id,
                seat,
                decide_micros: elapsed,
                path: "heuristic_eval".to_string(),
                is_override: false,
            };
            if let Ok(line) = serde_json::to_string(&record) {
                let _ = writeln!(self.sink, "{line}");
                let _ = self.sink.flush();
            }
        }

        result
    }
}

pub fn run_s3_rollout_profile_agent<R, W, E>(
    input: R,
    output: W,
    mut diagnostics: E,
    stats_out: PathBuf,
) -> Result<(), AgentError>
where
    R: BufRead,
    W: Write,
    E: Write,
{
    let stats_file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&stats_out)
        .map_err(|e| {
            let agent_err = AgentError::Policy(format!(
                "cannot open stats file {}: {e}",
                stats_out.display()
            ));
            let _ = writeln!(diagnostics, "error: {agent_err}");
            let _ = diagnostics.flush();
            agent_err
        })?;
    let stats_writer = BufWriter::new(stats_file);
    let inner_policy = match S3RolloutAgentPolicy::new() {
        Ok(p) => p,
        Err(e) => {
            let _ = writeln!(diagnostics, "error: {e}");
            let _ = diagnostics.flush();
            return Err(e);
        }
    };
    let policy = ProfiledS3Policy::new(inner_policy, stats_writer);
    let identity = AgentIdentity {
        name: S3_AGENT_NAME,
        version: "1",
    };
    run_agent(input, output, diagnostics, identity, S3_ROOT_SEED, policy)
}

pub fn run_heuristic_profile_agent<R, W, E>(
    input: R,
    output: W,
    mut diagnostics: E,
    seed: u64,
    stats_out: PathBuf,
) -> Result<(), AgentError>
where
    R: BufRead,
    W: Write,
    E: Write,
{
    let stats_file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&stats_out)
        .map_err(|e| {
            let agent_err = AgentError::Policy(format!(
                "cannot open stats file {}: {e}",
                stats_out.display()
            ));
            let _ = writeln!(diagnostics, "error: {agent_err}");
            let _ = diagnostics.flush();
            agent_err
        })?;
    let stats_writer = BufWriter::new(stats_file);
    let inner_policy = HeuristicAgentPolicy::new();
    let policy = ProfiledHeuristicPolicy::new(inner_policy, stats_writer);
    let identity = AgentIdentity {
        name: HEURISTIC_AGENT_NAME,
        version: HEURISTIC_AGENT_VERSION,
    };
    run_agent(input, output, diagnostics, identity, seed, policy)
}

fn wants_help(args: &[String]) -> bool {
    args.iter().any(|a| a == "-h" || a == "--help")
}

fn print_stdout(text: &str) {
    let mut stdout = io::stdout().lock();
    let _ = stdout.write_all(text.as_bytes());
    let _ = stdout.flush();
}

pub fn parse_s3_profile_args(args: &[String]) -> Result<PathBuf, String> {
    let mut stats_out: Option<String> = None;
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--stats-out" => {
                if stats_out.is_some() {
                    return Err("duplicate --stats-out flag".to_string());
                }
                stats_out = Some(
                    args.get(i + 1)
                        .ok_or_else(|| "missing value for --stats-out".to_string())?
                        .clone(),
                );
                i += 2;
            }
            other if other.starts_with('-') => return Err(format!("unknown flag `{other}`")),
            other => return Err(format!("unexpected positional argument `{other}`")),
        }
    }
    let path = stats_out.ok_or_else(|| "missing required --stats-out".to_string())?;
    Ok(PathBuf::from(path))
}

pub fn parse_heuristic_profile_args(args: &[String]) -> Result<(PathBuf, u64), String> {
    let mut stats_out: Option<String> = None;
    let mut seed: Option<u64> = None;
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--stats-out" => {
                if stats_out.is_some() {
                    return Err("duplicate --stats-out flag".to_string());
                }
                stats_out = Some(
                    args.get(i + 1)
                        .ok_or_else(|| "missing value for --stats-out".to_string())?
                        .clone(),
                );
                i += 2;
            }
            "--seed" => {
                if seed.is_some() {
                    return Err("duplicate --seed flag".to_string());
                }
                let s = args
                    .get(i + 1)
                    .ok_or_else(|| "missing value for --seed".to_string())?;
                let val = s
                    .parse::<u64>()
                    .map_err(|_| format!("--seed must be a u64 (got `{s}`)"))?;
                seed = Some(val);
                i += 2;
            }
            other if other.starts_with('-') => return Err(format!("unknown flag `{other}`")),
            other => return Err(format!("unexpected positional argument `{other}`")),
        }
    }
    let path = stats_out.ok_or_else(|| "missing required --stats-out".to_string())?;
    let seed = seed.unwrap_or(20_260_812);
    Ok((PathBuf::from(path), seed))
}

pub fn agent_s3_rollout_profile(args: &[String]) -> i32 {
    if wants_help(args) {
        print_stdout(
            "Usage: splendor agent-s3-rollout-profile --stats-out <path>

The S3 rollout-enhanced heuristic agent wrapped in operational telemetry.
Bit-identical action decisions to agent-s3-rollout. Appends one JSONL
telemetry record per decision to --stats-out.
",
        );
        return 0;
    }
    let stats_out = match parse_s3_profile_args(args) {
        Ok(path) => path,
        Err(msg) => {
            let mut stderr = io::stderr().lock();
            let _ = writeln!(stderr, "error: {msg}");
            let _ = stderr.flush();
            return 1;
        }
    };
    let stdin = io::stdin();
    let input = BufReader::new(stdin.lock());
    let stdout = io::stdout();
    let output = stdout.lock();
    let stderr = io::stderr();
    let diagnostics = stderr.lock();
    match run_s3_rollout_profile_agent(input, output, diagnostics, stats_out) {
        Ok(()) => 0,
        Err(_) => 1,
    }
}

pub fn agent_heuristic_profile(args: &[String]) -> i32 {
    if wants_help(args) {
        print_stdout(
            "Usage: splendor agent-heuristic-profile --stats-out <path> [--seed <u64>]

The standalone heuristic agent wrapped in operational telemetry.
Bit-identical action decisions to agent-heuristic. Appends one JSONL
telemetry record per decision to --stats-out.
",
        );
        return 0;
    }
    let (stats_out, seed) = match parse_heuristic_profile_args(args) {
        Ok(parsed) => parsed,
        Err(msg) => {
            let mut stderr = io::stderr().lock();
            let _ = writeln!(stderr, "error: {msg}");
            let _ = stderr.flush();
            return 1;
        }
    };
    let stdin = io::stdin();
    let input = BufReader::new(stdin.lock());
    let stdout = io::stdout();
    let output = stdout.lock();
    let stderr = io::stderr();
    let diagnostics = stderr.lock();
    match run_heuristic_profile_agent(input, output, diagnostics, seed, stats_out) {
        Ok(()) => 0,
        Err(_) => 1,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use splendor_agent::{PublicRequestMeta, StableRng};
    use splendor_core::{
        observation_hash, visible_events, Audience, FullState, GameConfig, PlayerId,
    };
    use splendor_search::canonical_order;

    #[test]
    fn parse_s3_profile_args_strict() {
        assert!(parse_s3_profile_args(&[]).is_err());
        assert!(parse_s3_profile_args(&["--unknown".to_string()]).is_err());
        assert!(parse_s3_profile_args(&["extra".to_string()]).is_err());
        let res = parse_s3_profile_args(&["--stats-out".to_string(), "out.jsonl".to_string()]);
        assert_eq!(res.unwrap(), PathBuf::from("out.jsonl"));
    }

    #[test]
    fn parse_heuristic_profile_args_strict() {
        assert!(parse_heuristic_profile_args(&[]).is_err());
        let res = parse_heuristic_profile_args(&[
            "--stats-out".to_string(),
            "out.jsonl".to_string(),
            "--seed".to_string(),
            "12345".to_string(),
        ])
        .unwrap();
        assert_eq!(res.0, PathBuf::from("out.jsonl"));
        assert_eq!(res.1, 12345);

        // default seed
        let res_default =
            parse_heuristic_profile_args(&["--stats-out".to_string(), "out.jsonl".to_string()])
                .unwrap();
        assert_eq!(res_default.1, 20_260_812);
    }

    #[test]
    fn profiled_heuristic_parity_and_telemetry() {
        let (state, setup) = FullState::new(GameConfig {
            player_count: 2,
            seed: 20260812,
            ..Default::default()
        })
        .unwrap();
        let viewer = PlayerId(0);
        let observation = state.observation(viewer);
        let history = visible_events(&setup.events, Audience::Player(viewer));
        let legal = canonical_order(&state.legal_actions());
        let obs_hash = observation_hash(&observation);

        let mut plain = HeuristicAgentPolicy::new();
        let mut plain_rng = StableRng::new(20260812);
        let plain_act = plain
            .choose_action(DecisionContext {
                observation: observation.clone(),
                visible_history: &history,
                legal_actions: &legal,
                meta: PublicRequestMeta {
                    game_id: "test-game".to_string(),
                    recipient_seat: viewer,
                    request_id: 1,
                    observation_hash: obs_hash.clone(),
                },
                rng: &mut plain_rng,
            })
            .unwrap();

        let mut sink = Vec::new();
        let mut profiled = ProfiledHeuristicPolicy::new(HeuristicAgentPolicy::new(), &mut sink);
        let mut prof_rng = StableRng::new(20260812);
        let prof_act = profiled
            .choose_action(DecisionContext {
                observation: observation.clone(),
                visible_history: &history,
                legal_actions: &legal,
                meta: PublicRequestMeta {
                    game_id: "test-game".to_string(),
                    recipient_seat: viewer,
                    request_id: 1,
                    observation_hash: obs_hash.clone(),
                },
                rng: &mut prof_rng,
            })
            .unwrap();

        assert_eq!(plain_act, prof_act);
        let output = String::from_utf8(sink).unwrap();
        assert!(!output.is_empty());
        let rec: DecisionTelemetryRecord = serde_json::from_str(output.trim()).unwrap();
        assert_eq!(rec.game_id, "test-game");
        assert_eq!(rec.request_id, 1);
        assert_eq!(rec.seat, 0);
        assert_eq!(rec.path, "heuristic_eval");
        assert!(!rec.is_override);
    }

    #[test]
    fn profiled_s3_parity_and_telemetry() {
        let (state, setup) = FullState::new(GameConfig {
            player_count: 2,
            seed: 20260812,
            ..Default::default()
        })
        .unwrap();
        let viewer = PlayerId(0);
        let observation = state.observation(viewer);
        let history = visible_events(&setup.events, Audience::Player(viewer));
        let legal = canonical_order(&state.legal_actions());
        let obs_hash = observation_hash(&observation);

        let mut plain = S3RolloutAgentPolicy::new().unwrap();
        let mut plain_rng = StableRng::new(20260812);
        let plain_act = plain
            .choose_action(DecisionContext {
                observation: observation.clone(),
                visible_history: &history,
                legal_actions: &legal,
                meta: PublicRequestMeta {
                    game_id: "test-game".to_string(),
                    recipient_seat: viewer,
                    request_id: 1,
                    observation_hash: obs_hash.clone(),
                },
                rng: &mut plain_rng,
            })
            .unwrap();

        let mut sink = Vec::new();
        let mut profiled = ProfiledS3Policy::new(S3RolloutAgentPolicy::new().unwrap(), &mut sink);
        let mut prof_rng = StableRng::new(20260812);
        let prof_act = profiled
            .choose_action(DecisionContext {
                observation: observation.clone(),
                visible_history: &history,
                legal_actions: &legal,
                meta: PublicRequestMeta {
                    game_id: "test-game".to_string(),
                    recipient_seat: viewer,
                    request_id: 1,
                    observation_hash: obs_hash.clone(),
                },
                rng: &mut prof_rng,
            })
            .unwrap();

        assert_eq!(plain_act, prof_act);
        let output = String::from_utf8(sink).unwrap();
        assert!(!output.is_empty());
        let rec: DecisionTelemetryRecord = serde_json::from_str(output.trim()).unwrap();
        assert_eq!(rec.game_id, "test-game");
        assert_eq!(rec.request_id, 1);
        assert_eq!(rec.seat, 0);
        assert!(rec.path == "heuristic_equivalent_fast_path" || rec.path == "rollout_comparison");
    }
}
