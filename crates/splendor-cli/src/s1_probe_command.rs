//! S1 Phase A feasibility probe command: replay a single decision context
//! through the LIVE determinization policy (fixed sample seed, exactly as
//! the arena agent would decide), with S1 depth diagnostics, and emit the
//! per-decision telemetry to a stats file.
//!
//! This measures the live agent's in-process decide time on a real context
//! without protocol orchestration: the context (observation + visible
//! history + legal actions) is rebuilt from a verified replay step, and the
//! same `DeterminizationAgentPolicyV1` used by `agent-determinization`
//! decides on it.

use std::io::Write;

use splendor_agent::{AgentPolicy, DecisionContext, PublicRequestMeta, StableRng};
use splendor_core::{observation_hash, Audience, PlayerId};
use splendor_determinization_agent::{DeterminizationAgentPolicyV1, PerDecisionStatsV1};
use splendor_imperfect_search::RootDeterminizationConfigV1;
use splendor_replay::{verify_replay_trace, ReplayV1};
use splendor_search::{canonical_order, SearchConfigV1};

use crate::arena_command::{print_stdout, wants_help};

const S1_PROBE_USAGE: &str = "Usage: splendor s1-probe --input <replay.json> --ply <k> \
--sample-seed <u64> --sample-count <u16> --max-depth-turns <u8> --max-nodes <u64> \
--stats-out <file>

Rebuild the verified decision context at <ply>, decide on it with the live
determinization policy (fixed sample seed — identical to the arena agent),
with S1 depth diagnostics, and append one PerDecisionStatsV1 line (including
depth_diagnostics) to --stats-out. Prints one JSON object with the chosen
action and decide_micros. Existing stats files are appended to.
";

pub fn run_s1_probe(args: &[String]) -> i32 {
    if wants_help(args) {
        print_stdout(S1_PROBE_USAGE);
        return 0;
    }
    match run(args) {
        Ok(()) => 0,
        Err(message) => {
            let mut stderr = std::io::stderr().lock();
            let _ = writeln!(stderr, "error: {message}");
            let _ = stderr.flush();
            1
        }
    }
}

fn run(args: &[String]) -> Result<(), String> {
    let mut input: Option<String> = None;
    let mut ply: Option<String> = None;
    let mut sample_seed: Option<String> = None;
    let mut sample_count: Option<String> = None;
    let mut max_depth_turns: Option<String> = None;
    let mut max_nodes: Option<String> = None;
    let mut stats_out: Option<String> = None;
    let mut i = 0;
    while i < args.len() {
        let arg = args[i].as_str();
        let slot = match arg {
            "--input" => &mut input,
            "--ply" => &mut ply,
            "--sample-seed" => &mut sample_seed,
            "--sample-count" => &mut sample_count,
            "--max-depth-turns" => &mut max_depth_turns,
            "--max-nodes" => &mut max_nodes,
            "--stats-out" => &mut stats_out,
            other if other.starts_with('-') => return Err(format!("unknown flag `{other}`")),
            other => return Err(format!("unexpected positional argument `{other}`")),
        };
        let value = args
            .get(i + 1)
            .ok_or_else(|| format!("{arg} requires a value"))?;
        if slot.is_some() {
            return Err(format!("{arg} given more than once"));
        }
        *slot = Some(value.clone());
        i += 2;
    }
    let input = input.ok_or("--input is required")?;
    let ply = parse_num::<u32>(&ply, "ply")?;
    let sample_seed = parse_num::<u64>(&sample_seed, "sample-seed")?;
    let sample_count = parse_num::<u16>(&sample_count, "sample-count")?;
    let max_depth_turns = parse_num::<u8>(&max_depth_turns, "max-depth-turns")?;
    let max_nodes = parse_num::<u64>(&max_nodes, "max-nodes")?;
    let stats_out = stats_out.ok_or("--stats-out is required")?;

    let config = RootDeterminizationConfigV1 {
        sample_seed,
        sample_count,
        continuation_search: SearchConfigV1 {
            max_depth_turns,
            max_nodes,
        },
    };
    config
        .validate()
        .map_err(|error| format!("invalid config: {error}"))?;

    let replay_text = std::fs::read_to_string(&input)
        .map_err(|error| format!("cannot read replay {input}: {error}"))?;
    let replay: ReplayV1 =
        serde_json::from_str(&replay_text).map_err(|error| format!("invalid replay: {error}"))?;
    let verified =
        verify_replay_trace(&replay).map_err(|error| format!("replay verification: {error}"))?;
    let position = verified
        .positions
        .iter()
        .find(|p| p.ply == ply)
        .ok_or_else(|| format!("ply {ply} out of range (0..{})", verified.positions.len()))?;

    let actor: PlayerId = position.recorded_actor;
    let observation = position.state.observation(actor);
    let visible_history =
        splendor_core::visible_events(&position.state.log, Audience::Player(actor));
    let legal_actions = canonical_order(&position.state.legal_actions());
    if legal_actions.is_empty() {
        return Err("no legal actions at ply".to_owned());
    }

    // Live policy with diagnostics — identical to the arena agent plus the
    // histogram collection.
    let policy = DeterminizationAgentPolicyV1::new(config)
        .map_err(|error| error.to_string())?
        .with_depth_diagnostics();
    let mut policy = policy;
    let mut rng = StableRng::new(0);
    let obs_hash = observation_hash(&observation).clone();
    let context = DecisionContext {
        observation,
        visible_history: &visible_history,
        legal_actions: &legal_actions,
        meta: PublicRequestMeta {
            game_id: format!("s1-probe-ply{ply}"),
            recipient_seat: actor,
            request_id: 1,
            observation_hash: obs_hash,
        },
        rng: &mut rng,
    };
    let action = policy
        .choose_action(context)
        .map_err(|error| error.to_string())?;
    let telemetry = policy
        .last_telemetry()
        .ok_or("telemetry missing after decision")?;

    let line = serde_json::to_string(&PerDecisionStatsV1::from(telemetry))
        .map_err(|error| format!("serialize: {error}"))?;
    let mut file = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&stats_out)
        .map_err(|error| format!("cannot open stats file {stats_out}: {error}"))?;
    writeln!(file, "{line}").map_err(|error| format!("write stats: {error}"))?;

    let summary = serde_json::json!({
        "ply": ply,
        "action": action,
        "decide_micros": telemetry.decide_micros,
    });
    let mut stdout = std::io::stdout().lock();
    writeln!(stdout, "{summary}").map_err(|error| format!("stdout: {error}"))?;
    Ok(())
}

fn parse_num<T: std::str::FromStr>(slot: &Option<String>, name: &str) -> Result<T, String> {
    slot.as_ref()
        .and_then(|v| v.parse::<T>().ok())
        .ok_or_else(|| format!("--{name} value invalid or missing"))
}
