//! M41A ''run-branch'': the counterfactual branch continuation command.
//!
//! Verifies a source replay, rebuilds the full state at the branch ply,
//! applies the forced action referee-side (validated against the rebuilt
//! legal set), then lets the configured agent subprocesses play the
//! continuation under the absolute ply cap. The published replay contains
//! the complete step chain from the source game''s initial state (prefix +
//! forced + continuation). See docs/m41a-counterfactual-action-value-probe.md.

use std::fs::{self, File};
use std::io::{self, BufReader, Read, Write};
use std::path::{Path, PathBuf};

use splendor_arena::{ArenaRunner, CappedRun};
use splendor_replay::verify_replay;

use crate::arena_command::{
    commit_aborted, commit_completed, compact_outcome_line, parent_dir_exists, print_stdout,
    read_config, to_pretty_line, wants_help, write_outcome_line, MatchExit, RunMatchArgs,
    RunMatchError, MAX_ARENA_CONFIG_BYTES,
};

// M41A `run-branch`: the counterfactual branch continuation command.
// ===========================================================================

const RUN_BRANCH_USAGE: &str = "\
Usage: splendor run-branch --source-replay <replay.json> \
--branch-ply <k> --forced-action <action.json> \
--config <arena-config.json> --ply-cap <n> \
--report-out <branch-report.json> --replay-out <branch-replay.json>

Run exactly one M41A counterfactual branch: verify the source replay,
rebuild the full state at the branch ply, apply the forced action
referee-side (validated against the rebuilt legal set), then let the
configured agent subprocesses play the continuation under the absolute
ply cap. The published replay contains the complete step chain from the
source game's initial state (prefix + forced + continuation).

Options:
  --source-replay <path>  Verified source game replay (JSON).
  --branch-ply <k>        The acting-decision index to branch at.
  --forced-action <path>  The forced action document (one Action JSON).
  --config <path>         Arena config naming BOTH continuation agents.
  --ply-cap <n>           ABSOLUTE ply cap from the source game's ply 0.
  --report-out <path>     Branch report output (must not exist).
  --replay-out <path>     Branch replay output (must not exist).
";

struct RunBranchArgs {
    source_replay: PathBuf,
    branch_ply: u32,
    forced_action: PathBuf,
    config: PathBuf,
    ply_cap: u32,
    report_out: PathBuf,
    replay_out: PathBuf,
}

fn parse_run_branch_args(args: &[String]) -> Result<RunBranchArgs, String> {
    let mut source_replay: Option<String> = None;
    let mut branch_ply: Option<String> = None;
    let mut forced_action: Option<String> = None;
    let mut config: Option<String> = None;
    let mut ply_cap: Option<String> = None;
    let mut report_out: Option<String> = None;
    let mut replay_out: Option<String> = None;

    let mut index = 0;
    while index < args.len() {
        let flag = args[index].as_str();
        let value = args
            .get(index + 1)
            .ok_or_else(|| format!("{flag} requires a value"))?;
        let slot = match flag {
            "--source-replay" => &mut source_replay,
            "--branch-ply" => &mut branch_ply,
            "--forced-action" => &mut forced_action,
            "--config" => &mut config,
            "--ply-cap" => &mut ply_cap,
            "--report-out" => &mut report_out,
            "--replay-out" => &mut replay_out,
            other => return Err(format!("unknown flag `{other}`")),
        };
        if slot.is_some() {
            return Err(format!("duplicate flag {flag}"));
        }
        *slot = Some(value.clone());
        index += 2;
    }
    if args.len() % 2 != 0 {
        return Err("every flag requires exactly one value".to_string());
    }

    let need = |name: &str, slot: &Option<String>| -> Result<String, String> {
        slot.clone()
            .ok_or_else(|| format!("missing required flag --{name}"))
    };
    let branch_ply: u32 = need("branch-ply", &branch_ply)?
        .parse()
        .map_err(|_| "--branch-ply must be a u32".to_string())?;
    let ply_cap: u32 = need("ply-cap", &ply_cap)?
        .parse()
        .map_err(|_| "--ply-cap must be a u32".to_string())?;

    Ok(RunBranchArgs {
        source_replay: PathBuf::from(need("source-replay", &source_replay)?),
        branch_ply,
        forced_action: PathBuf::from(need("forced-action", &forced_action)?),
        config: PathBuf::from(need("config", &config)?),
        ply_cap,
        report_out: PathBuf::from(need("report-out", &report_out)?),
        replay_out: PathBuf::from(need("replay-out", &replay_out)?),
    })
}

/// Entry point for `splendor run-branch ...`. Returns the process exit code.
pub fn run_branch(args: &[String]) -> i32 {
    match run_branch_inner(args) {
        Ok(MatchExit::Completed(code)) | Ok(MatchExit::Aborted(code)) => code,
        Err(err) => {
            let mut stderr = io::stderr().lock();
            let _ = writeln!(stderr, "error: {err}");
            let _ = stderr.flush();
            1
        }
    }
}

fn run_branch_inner(args: &[String]) -> Result<MatchExit, RunMatchError> {
    if wants_help(args) {
        print_stdout(RUN_BRANCH_USAGE);
        return Ok(MatchExit::Completed(0));
    }

    let parsed = parse_run_branch_args(args).map_err(RunMatchError::Cli)?;

    // Output-path invariants (same discipline as run-match).
    if parsed.report_out == parsed.replay_out {
        return Err(RunMatchError::Cli(
            "--report-out and --replay-out must differ".to_string(),
        ));
    }
    for (name, path) in [
        ("--report-out", &parsed.report_out),
        ("--replay-out", &parsed.replay_out),
    ] {
        if path.exists() {
            return Err(RunMatchError::Cli(format!(
                "{name} output already exists: {}",
                path.display()
            )));
        }
        if !parent_dir_exists(path) {
            return Err(RunMatchError::Cli(format!(
                "{name} parent directory does not exist: {}",
                path.display()
            )));
        }
    }

    // 1. Load + STRICTLY verify the source replay, capturing the branch
    //    position (the whole replay verifies, not just the prefix).
    let source: splendor_replay::ReplayV1 = {
        let file = File::open(&parsed.source_replay).map_err(|e| {
            RunMatchError::ConfigRead(format!(
                "cannot open source replay {}: {e}",
                parsed.source_replay.display()
            ))
        })?;
        let reader = BufReader::new(file);
        let mut buf = Vec::new();
        reader
            .take(MAX_ARENA_CONFIG_BYTES * 16)
            .read_to_end(&mut buf)
            .map_err(|e| RunMatchError::ConfigRead(format!("read source replay: {e}")))?;
        let replay: splendor_replay::ReplayV1 = serde_json::from_slice(&buf)
            .map_err(|e| RunMatchError::ConfigParse(format!("parse source replay: {e}")))?;
        verify_replay(&replay).map_err(|e| {
            RunMatchError::ConfigRead(format!("source replay failed verification: {e}"))
        })?;
        replay
    };
    if parsed.branch_ply >= source.steps.len() as u32 {
        return Err(RunMatchError::Cli(format!(
            "--branch-ply {} is out of range (source has {} steps)",
            parsed.branch_ply,
            source.steps.len()
        )));
    }

    // 2. Load the forced action document.
    let forced: splendor_core::Action = {
        let text = fs::read_to_string(&parsed.forced_action).map_err(|e| {
            RunMatchError::ConfigRead(format!(
                "cannot read forced action {}: {e}",
                parsed.forced_action.display()
            ))
        })?;
        serde_json::from_str(&text)
            .map_err(|e| RunMatchError::ConfigParse(format!("parse forced action: {e}")))?
    };

    // 3. Load the arena config (names BOTH continuation agents; seed is
    //    overridden to the source seed — the hidden world being branched).
    let mut config = read_config(&parsed.config)?;
    config.seed = source.seed;

    // 4. Rebuild the branch start: prefix steps + per-ply referee events
    //    (rebuilt on a fresh recorder from the source seed), plus the
    //    verify_replay_position cross-check of the branch-point state.
    let start = {
        use splendor_arena::BranchStart;
        use splendor_core::GameConfig;
        use splendor_replay::ReplayRecorder;
        let ruleset = splendor_core::Ruleset::base_v1();
        let (mut rec, _setup) = ReplayRecorder::new_with_setup(GameConfig {
            player_count: source.player_count,
            seed: source.seed,
            ruleset,
        })
        .map_err(|e| RunMatchError::Internal(format!("branch rebuild: {e}")))?;
        let mut events = Vec::with_capacity(parsed.branch_ply as usize);
        for step in &source.steps[..parsed.branch_ply as usize] {
            let res = rec
                .apply(step.action)
                .map_err(|e| RunMatchError::Internal(format!("prefix replay: {e}")))?;
            events.push(res.events);
        }
        // Cross-check the rebuilt branch-point state against the source's
        // recorded hash chain (defense in depth on top of verify_replay).
        let rebuilt_hash = splendor_core::full_state_hash(rec.state());
        let expected_hash = if parsed.branch_ply == 0 {
            source.initial_state_hash.as_str()
        } else {
            source.steps[parsed.branch_ply as usize - 1]
                .state_hash_after
                .as_str()
        };
        if rebuilt_hash.as_str() != expected_hash {
            return Err(RunMatchError::Internal(format!(
                "branch-point rebuild hash mismatch at ply {}",
                parsed.branch_ply
            )));
        }
        BranchStart {
            state: rec.state().clone(),
            prefix_steps: source.steps[..parsed.branch_ply as usize].to_vec(),
            initial_state_hash: source.initial_state_hash.clone(),
            ruleset: source.ruleset.clone(),
            ruleset_fingerprint: source.ruleset_fingerprint.clone(),
            seed: source.seed,
            prefix_events: events,
        }
    };

    // 5. Branch ply must be strictly below the absolute cap (a branch at or
    //    past the cap cannot continue).
    if parsed.branch_ply + 1 >= parsed.ply_cap {
        return Err(RunMatchError::Cli(format!(
            "--branch-ply {} + forced ply must be strictly below --ply-cap {}",
            parsed.branch_ply, parsed.ply_cap
        )));
    }

    // 6. Run the branch.
    let capped = ArenaRunner::run_branch(config, start, forced, parsed.ply_cap)
        .map_err(|e| RunMatchError::Internal(e.to_string()))?;

    // 7. Publish (identical discipline to run-rollout).
    match capped {
        CappedRun::Terminal(run) => match run.replay {
            Some(replay) => commit_completed(
                &RunMatchArgs {
                    config: parsed.config,
                    report_out: parsed.report_out.clone(),
                    replay_out: parsed.replay_out.clone(),
                },
                &run.report,
                &replay,
            ),
            None => commit_aborted(
                &RunMatchArgs {
                    config: parsed.config,
                    report_out: parsed.report_out.clone(),
                    replay_out: parsed.replay_out.clone(),
                },
                &run.report,
            ),
        },
        CappedRun::Truncated { report, prefix } => {
            // A branch truncation publishes the prefix as the replay-out
            // document's sibling? No — run-branch's replay-out receives the
            // PREFIX document when truncated (the continuation replay does
            // not exist); the report is the branch report.
            let prefix_json = to_pretty_line(&prefix)
                .map_err(|e| RunMatchError::Internal(format!("serialize prefix failed: {e}")))?;
            let report_json = to_pretty_line(&report)
                .map_err(|e| RunMatchError::Internal(format!("serialize report failed: {e}")))?;
            let line = compact_outcome_line(&report.outcome)?;
            let temp_report = parsed.report_out.with_extension("tmp-report");
            let temp_prefix = parsed.replay_out.with_extension("tmp-prefix");
            std::fs::write(&temp_report, report_json.as_bytes())
                .and_then(|_| std::fs::write(&temp_prefix, prefix_json.as_bytes()))
                .map_err(|e| RunMatchError::Io(format!("temp write failed: {e}")))?;
            let publish = |temp: &Path, target: &Path| -> io::Result<()> {
                std::fs::rename(temp, target).or_else(|_| {
                    std::fs::copy(temp, target).and_then(|_| std::fs::remove_file(temp))
                })
            };
            if let Err(e) = publish(&temp_report, &parsed.report_out) {
                let _ = std::fs::remove_file(&temp_report);
                let _ = std::fs::remove_file(&temp_prefix);
                return Err(RunMatchError::Io(format!(
                    "publish branch report failed: {e}"
                )));
            }
            if let Err(e) = publish(&temp_prefix, &parsed.replay_out) {
                let _ = std::fs::remove_file(&parsed.report_out);
                let _ = std::fs::remove_file(&temp_prefix);
                return Err(RunMatchError::Io(format!(
                    "publish branch prefix failed: {e}"
                )));
            }
            let mut stdout = io::stdout().lock();
            if let Err(e) = write_outcome_line(&mut stdout, &line) {
                let _ = std::fs::remove_file(&parsed.report_out);
                let _ = std::fs::remove_file(&parsed.replay_out);
                return Err(RunMatchError::Io(e));
            }
            Ok(MatchExit::Completed(0))
        }
    }
}
