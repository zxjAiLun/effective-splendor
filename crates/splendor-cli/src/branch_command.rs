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

// ===========================================================================
// M41A `probe-legal`: the branch-point legal-set + identity probe.
// ===========================================================================

const PROBE_LEGAL_USAGE: &str = "\
Usage: splendor probe-legal --source-replay <replay.json> \
--branch-ply <k> [--emit-observation]

Verify the source replay, rebuild the full state at the branch ply, and
print one JSON object: the acting seat, the branch-point state hash, the
player-view observation hash, and the FULL ordered legal action set at
that state. No game is played; no agents are spawned.

Options:
  --source-replay <path>  Verified source game replay (JSON).
  --branch-ply <k>        The acting-decision index to probe.
  --emit-observation      Also emit the branch-point player-view
                          observation payload (identity-checked: its
                          hash equals the reported observation_hash).
";

/// Entry point for `splendor probe-legal ...`. Returns the process exit code.
pub fn probe_legal(args: &[String]) -> i32 {
    match probe_legal_inner(args) {
        Ok(()) => 0,
        Err(err) => {
            let mut stderr = io::stderr().lock();
            let _ = writeln!(stderr, "error: {err}");
            let _ = stderr.flush();
            1
        }
    }
}

fn probe_legal_inner(args: &[String]) -> Result<(), String> {
    if wants_help(args) {
        print_stdout(PROBE_LEGAL_USAGE);
        return Ok(());
    }
    let mut source_replay: Option<String> = None;
    let mut branch_ply: Option<String> = None;
    let mut emit_observation = false;
    let mut index = 0;
    while index < args.len() {
        let flag = args[index].as_str();
        if flag == "--emit-observation" {
            if emit_observation {
                return Err("duplicate flag --emit-observation".to_string());
            }
            emit_observation = true;
            index += 1;
            continue;
        }
        let value = args
            .get(index + 1)
            .ok_or_else(|| format!("{flag} requires a value"))?;
        match flag {
            "--source-replay" => {
                if source_replay.replace(value.clone()).is_some() {
                    return Err("duplicate flag --source-replay".to_string());
                }
            }
            "--branch-ply" => {
                if branch_ply.replace(value.clone()).is_some() {
                    return Err("duplicate flag --branch-ply".to_string());
                }
            }
            other => return Err(format!("unknown flag `{other}`")),
        }
        index += 2;
    }
    let source_replay = PathBuf::from(
        source_replay.ok_or_else(|| "missing required flag --source-replay".to_string())?,
    );
    let branch_ply: u32 = branch_ply
        .ok_or_else(|| "missing required flag --branch-ply".to_string())?
        .parse()
        .map_err(|_| "--branch-ply must be a u32".to_string())?;

    // Verify + rebuild (same discipline as run-branch).
    let source: splendor_replay::ReplayV1 = {
        let text = fs::read_to_string(&source_replay)
            .map_err(|e| format!("cannot read source replay: {e}"))?;
        let replay: splendor_replay::ReplayV1 =
            serde_json::from_str(&text).map_err(|e| format!("parse source replay: {e}"))?;
        verify_replay(&replay).map_err(|e| format!("source replay failed verification: {e}"))?;
        replay
    };
    if branch_ply >= source.steps.len() as u32 {
        return Err(format!(
            "--branch-ply {branch_ply} is out of range (source has {} steps)",
            source.steps.len()
        ));
    }

    use splendor_core::GameConfig;
    use splendor_replay::ReplayRecorder;
    let (mut rec, _) = ReplayRecorder::new_with_setup(GameConfig {
        player_count: source.player_count,
        seed: source.seed,
        ruleset: splendor_core::Ruleset::base_v1(),
    })
    .map_err(|e| format!("rebuild: {e}"))?;
    for step in &source.steps[..branch_ply as usize] {
        rec.apply(step.action)
            .map_err(|e| format!("prefix replay: {e}"))?;
    }
    // Cross-check the rebuilt state hash against the source chain.
    let rebuilt_hash = splendor_core::full_state_hash(rec.state());
    let expected_hash = if branch_ply == 0 {
        source.initial_state_hash.as_str()
    } else {
        source.steps[branch_ply as usize - 1]
            .state_hash_after
            .as_str()
    };
    if rebuilt_hash.as_str() != expected_hash {
        return Err(format!(
            "branch-point rebuild hash mismatch at ply {branch_ply}"
        ));
    }

    let state = rec.state();
    let actor = state.current_player;
    let legal = state.legal_actions();
    let observation = state.observation(actor);
    let obs_hash = splendor_core::observation_hash(&observation);

    let payload = if emit_observation {
        serde_json::json!({
            "source_replay_sha256": sha256_of(&source_replay),
            "seed": source.seed,
            "branch_ply": branch_ply,
            "acting_seat": actor.0,
            "state_hash": rebuilt_hash.as_str(),
            "observation_hash": obs_hash.as_str(),
            "observation": observation,
            "legal_actions": legal,
        })
    } else {
        serde_json::json!({
            "source_replay_sha256": sha256_of(&source_replay),
            "seed": source.seed,
            "branch_ply": branch_ply,
            "acting_seat": actor.0,
            "state_hash": rebuilt_hash.as_str(),
            "observation_hash": obs_hash.as_str(),
            "legal_actions": legal,
        })
    };
    println!(
        "{}",
        serde_json::to_string_pretty(&payload).map_err(|e| e.to_string())?
    );
    Ok(())
}

fn sha256_of(path: &Path) -> String {
    use std::io::Read as _;
    let mut file = File::open(path).expect("reopen for hashing");
    let mut buf = Vec::new();
    file.read_to_end(&mut buf).expect("read for hashing");
    // SHA-256 via a minimal implementation (no external crate): use the
    // Windows/Unix agnostic approach — hash through the `sha2`-free path
    // by delegating to the replay document hash? The repo carries no
    // sha2 crate in splendor-cli; compute via the engine's hash utility?
    // Simplest correct: read the file bytes and hash with a tiny pure
    // SHA-256 (FIPS 180-4) below.
    sha256_bytes(&buf)
}

fn sha256_bytes(data: &[u8]) -> String {
    // Minimal FIPS 180-4 SHA-256 (constant tables inlined).
    const K: [u32; 64] = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
        0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
        0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
        0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
        0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
        0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
        0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
        0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
        0xc67178f2,
    ];
    let mut h: [u32; 8] = [
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab,
        0x5be0cd19,
    ];
    let mut msg = data.to_vec();
    let bit_len = (data.len() as u64) * 8;
    msg.push(0x80);
    while msg.len() % 64 != 56 {
        msg.push(0);
    }
    msg.extend_from_slice(&bit_len.to_be_bytes());
    for chunk in msg.chunks(64) {
        let mut w = [0u32; 64];
        for i in 0..16 {
            w[i] = u32::from_be_bytes([
                chunk[i * 4],
                chunk[i * 4 + 1],
                chunk[i * 4 + 2],
                chunk[i * 4 + 3],
            ]);
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16]
                .wrapping_add(s0)
                .wrapping_add(w[i - 7])
                .wrapping_add(s1);
        }
        let (mut a, mut b, mut c, mut d, mut e, mut f, mut g, mut hh) =
            (h[0], h[1], h[2], h[3], h[4], h[5], h[6], h[7]);
        for i in 0..64 {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let ch = (e & f) ^ ((!e) & g);
            let t1 = hh
                .wrapping_add(s1)
                .wrapping_add(ch)
                .wrapping_add(K[i])
                .wrapping_add(w[i]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            let t2 = s0.wrapping_add(maj);
            hh = g;
            g = f;
            f = e;
            e = d.wrapping_add(t1);
            d = c;
            c = b;
            b = a;
            a = t1.wrapping_add(t2);
        }
        h[0] = h[0].wrapping_add(a);
        h[1] = h[1].wrapping_add(b);
        h[2] = h[2].wrapping_add(c);
        h[3] = h[3].wrapping_add(d);
        h[4] = h[4].wrapping_add(e);
        h[5] = h[5].wrapping_add(f);
        h[6] = h[6].wrapping_add(g);
        h[7] = h[7].wrapping_add(hh);
    }
    let mut out = String::with_capacity(64);
    for word in h {
        out.push_str(&format!("{word:08x}"));
    }
    out
}

// ===========================================================================
// M41A `run-branches`: state-batch counterfactual execution + provenance
// sidecar (executor optimization: verify/rebuild ONCE per state, all
// legal actions from the cached branch point).
// ===========================================================================

const RUN_BRANCHES_USAGE: &str = "\
Usage: splendor run-branches --source-replay <replay.json> \
--branch-ply <k> --config <arena-config.json> --ply-cap <n> \
--out-dir <branch-state-dir> [--run-contract <run-contract.json>] [--resume]

Verify the source replay and rebuild the branch point ONCE, then run
EVERY legal action of that state as an independent branch continuation,
publishing per-action artifacts under out-dir:

  action-<i>/replay.json     the branch replay (or prefix when truncated)
  action-<i>/report.json     the branch arena report
  state-probe.json           branch-point identity + ordered legal set
  state-manifest.json        per-action provenance sidecar (v2: forced
                             action, acting-seat return, final/cap hash,
                             report/replay SHAs — for BOTH fresh and
                             resumed entries; resume re-validates the
                             SHAs against the prior manifest and fails
                             closed on any mismatch; resume without a
                             manifest is refused)

Options:
  --source-replay <path>  Verified source game replay (JSON).
  --branch-ply <k>        The acting-decision index to branch at.
  --config <path>         Arena config naming BOTH continuation agents
                          (resident-proxy agents expected).
  --ply-cap <n>           ABSOLUTE ply cap from the source game's ply 0.
  --out-dir <path>        Per-state output directory.
  --run-contract <path>   The corpus run-contract document (identity
                          content is the corpus driver's; this command
                          binds its SHA-256 into the manifest and
                          refuses to resume artifacts produced under a
                          different contract).
  --resume                Reuse actions whose artifact pair matches the
                          prior manifest EXACTLY (SHA re-validation).
";

struct RunBranchesArgs {
    source_replay: PathBuf,
    branch_ply: u32,
    config: PathBuf,
    ply_cap: u32,
    out_dir: PathBuf,
    run_contract: Option<PathBuf>,
    resume: bool,
}

fn parse_run_branches_args(args: &[String]) -> Result<RunBranchesArgs, String> {
    let mut source_replay: Option<String> = None;
    let mut branch_ply: Option<String> = None;
    let mut config: Option<String> = None;
    let mut ply_cap: Option<String> = None;
    let mut out_dir: Option<String> = None;
    let mut run_contract: Option<String> = None;
    let mut resume = false;

    let mut index = 0;
    while index < args.len() {
        let flag = args[index].as_str();
        if flag == "--resume" {
            if resume {
                return Err("duplicate flag --resume".to_string());
            }
            resume = true;
            index += 1;
            continue;
        }
        let value = args
            .get(index + 1)
            .ok_or_else(|| format!("{flag} requires a value"))?;
        let slot = match flag {
            "--source-replay" => &mut source_replay,
            "--branch-ply" => &mut branch_ply,
            "--config" => &mut config,
            "--ply-cap" => &mut ply_cap,
            "--out-dir" => &mut out_dir,
            "--run-contract" => &mut run_contract,
            other => return Err(format!("unknown flag `{other}`")),
        };
        if slot.is_some() {
            return Err(format!("duplicate flag {flag}"));
        }
        *slot = Some(value.clone());
        index += 2;
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
    Ok(RunBranchesArgs {
        source_replay: PathBuf::from(need("source-replay", &source_replay)?),
        branch_ply,
        config: PathBuf::from(need("config", &config)?),
        ply_cap,
        out_dir: PathBuf::from(need("out-dir", &out_dir)?),
        run_contract: run_contract.map(PathBuf::from),
        resume,
    })
}

/// Entry point for `splendor run-branches ...`. Returns the process exit code.
pub fn run_branches(args: &[String]) -> i32 {
    match run_branches_inner(args) {
        Ok(()) => 0,
        Err(err) => {
            let mut stderr = io::stderr().lock();
            let _ = writeln!(stderr, "error: {err}");
            let _ = stderr.flush();
            1
        }
    }
}

fn run_branches_inner(args: &[String]) -> Result<(), String> {
    if wants_help(args) {
        print_stdout(RUN_BRANCHES_USAGE);
        return Ok(());
    }
    let parsed = parse_run_branches_args(args)?;

    // 1. Verify the source replay once.
    let source: splendor_replay::ReplayV1 = {
        let text = fs::read_to_string(&parsed.source_replay)
            .map_err(|e| format!("cannot read source replay: {e}"))?;
        let replay: splendor_replay::ReplayV1 =
            serde_json::from_str(&text).map_err(|e| format!("parse source replay: {e}"))?;
        verify_replay(&replay).map_err(|e| format!("source replay failed verification: {e}"))?;
        replay
    };
    if parsed.branch_ply >= source.steps.len() as u32 {
        return Err(format!(
            "--branch-ply {} is out of range (source has {} steps)",
            parsed.branch_ply,
            source.steps.len()
        ));
    }
    if parsed.branch_ply + 1 >= parsed.ply_cap {
        return Err(format!(
            "--branch-ply {} + forced ply must be strictly below --ply-cap {}",
            parsed.branch_ply, parsed.ply_cap
        ));
    }

    // 2. Rebuild the branch point ONCE.
    let (state, prefix_steps, prefix_events) = {
        use splendor_core::GameConfig;
        use splendor_replay::ReplayRecorder;
        let (mut rec, _setup) = ReplayRecorder::new_with_setup(GameConfig {
            player_count: source.player_count,
            seed: source.seed,
            ruleset: splendor_core::Ruleset::base_v1(),
        })
        .map_err(|e| format!("branch rebuild: {e}"))?;
        let mut events = Vec::with_capacity(parsed.branch_ply as usize);
        for step in &source.steps[..parsed.branch_ply as usize] {
            let res = rec
                .apply(step.action)
                .map_err(|e| format!("prefix replay: {e}"))?;
            events.push(res.events);
        }
        let rebuilt_hash = splendor_core::full_state_hash(rec.state());
        let expected_hash = if parsed.branch_ply == 0 {
            source.initial_state_hash.as_str()
        } else {
            source.steps[parsed.branch_ply as usize - 1]
                .state_hash_after
                .as_str()
        };
        if rebuilt_hash.as_str() != expected_hash {
            return Err(format!(
                "branch-point rebuild hash mismatch at ply {}",
                parsed.branch_ply
            ));
        }
        (
            rec.state().clone(),
            source.steps[..parsed.branch_ply as usize].to_vec(),
            events,
        )
    };

    let acting_seat = state.current_player.0;
    let legal = state.legal_actions();
    let observation = state.observation(state.current_player);
    let obs_hash = splendor_core::observation_hash(&observation);
    let state_hash = splendor_core::full_state_hash(&state);
    let source_sha = sha256_of(&parsed.source_replay);

    // 3. Output layout + resume semantics.
    let out_dir = &parsed.out_dir;
    fs::create_dir_all(out_dir).map_err(|e| format!("create out dir: {e}"))?;
    let probe_path = out_dir.join("state-probe.json");
    if probe_path.exists() && !parsed.resume {
        return Err(format!("output already exists: {}", probe_path.display()));
    }
    let probe_doc = serde_json::json!({
        "format": "effective-splendor-m41a-branch-state-probe",
        "version": 1,
        "source_replay_sha256": source_sha,
        "seed": source.seed,
        "branch_ply": parsed.branch_ply,
        "acting_seat": acting_seat,
        "state_hash": state_hash.as_str(),
        "observation_hash": obs_hash.as_str(),
        "legal_actions": legal,
    });
    // On resume, the existing probe must match EXACTLY (identity gate).
    if probe_path.exists() {
        let existing: serde_json::Value = serde_json::from_str(
            &fs::read_to_string(&probe_path).map_err(|e| format!("read probe: {e}"))?,
        )
        .map_err(|e| format!("parse existing probe: {e}"))?;
        if existing != probe_doc {
            return Err(
                "existing state-probe.json differs from the rebuilt branch point".to_string(),
            );
        }
    } else {
        write_pretty(&probe_path, &probe_doc)?;
    }

    // 4. Arena config (seed overridden to the source's).
    let mut config = read_config(&parsed.config).map_err(|e| format!("{}", e))?;
    config.seed = source.seed;
    config.game_id = format!("m41a-branch-{}", sha256_of(&parsed.source_replay));

    // 4b. Run-contract binding (formal provenance): an existing manifest
    // must have been produced under the SAME run contract; a fresh run
    // records the contract SHA into the manifest. The contract document
    // is caller-supplied (the corpus driver writes one canonical
    // run-contract.json per formal generation run).
    let run_contract_sha: Option<String> = match &parsed.run_contract {
        Some(path) => {
            let text = fs::read_to_string(path)
                .map_err(|e| format!("cannot read run contract {}: {e}", path.display()))?;
            // Validate it parses as JSON (identity content is the corpus
            // driver's contract; this command only binds its SHA).
            let _: serde_json::Value =
                serde_json::from_str(&text).map_err(|e| format!("parse run contract: {e}"))?;
            Some(sha256_of(path))
        }
        None => None,
    };

    // Existing manifest (for resume provenance validation).
    let manifest_path = out_dir.join("state-manifest.json");
    let existing_manifest: Option<serde_json::Value> = if manifest_path.is_file() {
        Some(
            serde_json::from_str(
                &fs::read_to_string(&manifest_path).map_err(|e| format!("read manifest: {e}"))?,
            )
            .map_err(|e| format!("parse existing manifest: {e}"))?,
        )
    } else {
        None
    };
    // An --resume run without a manifest must fail closed (no blind
    // resume of complete artifacts: their provenance cannot be checked).
    if parsed.resume && existing_manifest.is_none() {
        return Err(
            "--resume requires an existing state-manifest.json (blind resume of \
             artifacts without provenance is forbidden; clear deliberately)"
                .to_string(),
        );
    }
    // A resume with a run contract must match the manifest's contract.
    if let (Some(contract_sha), Some(manifest)) = (&run_contract_sha, &existing_manifest) {
        if manifest.get("run_contract_sha256").and_then(|v| v.as_str())
            != Some(contract_sha.as_str())
        {
            return Err(
                "existing state-manifest was produced under a DIFFERENT run \
                 contract; stale artifacts must be cleared deliberately"
                    .to_string(),
            );
        }
    }
    let prior_actions: std::collections::HashMap<u64, &serde_json::Value> = existing_manifest
        .as_ref()
        .and_then(|m| m.get("actions"))
        .and_then(|a| a.as_array())
        .map(|arr| {
            arr.iter()
                .map(|e| {
                    (
                        e.get("action_index")
                            .and_then(|v| v.as_u64())
                            .unwrap_or(u64::MAX),
                        e,
                    )
                })
                .collect()
        })
        .unwrap_or_default();

    let mut manifest_entries: Vec<serde_json::Value> = Vec::new();

    for (action_index, action) in legal.iter().enumerate() {
        let adir = out_dir.join(format!("action-{action_index:03}"));
        let replay_path = adir.join("replay.json");
        let report_path = adir.join("report.json");

        if adir.exists() && (replay_path.exists() || report_path.exists()) {
            // Complete pair under --resume: fail-closed SHA re-validation
            // against the PRIOR manifest entry (tampered replay/report
            // is rejected, never silently reused).
            if parsed.resume && replay_path.is_file() && report_path.is_file() {
                let prior = prior_actions
                    .get(&(action_index as u64))
                    .copied()
                    .ok_or_else(|| {
                        format!(
                            "action {action_index} has artifacts but no prior manifest \
                         entry; provenance cannot be validated (clear deliberately)"
                        )
                    })?;
                let actual_report_sha = sha256_of(&report_path);
                let actual_replay_sha = sha256_of(&replay_path);
                let prior_report = prior
                    .get("report_sha256")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                let prior_replay = prior
                    .get("replay_sha256")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                if actual_report_sha != prior_report || actual_replay_sha != prior_replay {
                    return Err(format!(
                        "action {action_index} artifact SHA mismatch vs the prior \
                         manifest (report {} != {}, replay {} != {}) — tampered or \
                         corrupted; fail closed",
                        &actual_report_sha[..16],
                        &prior_report[..16],
                        &actual_replay_sha[..16],
                        &prior_replay[..16],
                    ));
                }
                // Rebuild the full entry from the prior manifest (identity
                // preserved; only `resumed` flips).
                let mut entry = prior.clone();
                entry["resumed"] = serde_json::json!(true);
                manifest_entries.push(entry);
                continue;
            }
            // Partial artifacts, or artifacts without --resume: an error.
            return Err(format!(
                "partial or pre-existing artifacts at {} (replay/report must be \
                 a complete pair under --resume with a valid manifest); clear \
                 deliberately",
                adir.display()
            ));
        }
        fs::create_dir_all(&adir).map_err(|e| format!("create action dir: {e}"))?;

        // Fresh BranchStart per action (the recorder consumes the state).
        let start = splendor_arena::BranchStart {
            state: state.clone(),
            prefix_steps: prefix_steps.clone(),
            initial_state_hash: source.initial_state_hash.clone(),
            ruleset: source.ruleset.clone(),
            ruleset_fingerprint: source.ruleset_fingerprint.clone(),
            seed: source.seed,
            prefix_events: prefix_events.clone(),
        };

        let capped = ArenaRunner::run_branch(config.clone(), start, *action, parsed.ply_cap)
            .map_err(|e| format!("action {action_index} internal error: {e}"))?;

        let (report, replay_doc, truncated, return_value, final_hash) = match capped {
            CappedRun::Terminal(run) => match run.replay {
                Some(replay) => {
                    let (ret, hash) = terminal_identity(&run.report, acting_seat);
                    (
                        run.report,
                        serde_json::to_value(&replay).map_err(|e| e.to_string())?,
                        false,
                        ret,
                        hash,
                    )
                }
                None => {
                    return Err(format!(
                        "action {action_index} ABORTED: {:?}",
                        run.report.outcome
                    ));
                }
            },
            CappedRun::Truncated { report, prefix } => {
                let (ret, hash) = truncated_identity(&report, acting_seat);
                (
                    report,
                    serde_json::to_value(&prefix).map_err(|e| e.to_string())?,
                    true,
                    ret,
                    hash,
                )
            }
        };
        write_pretty(
            &report_path,
            &serde_json::to_value(&report).map_err(|e| e.to_string())?,
        )?;
        write_pretty(&replay_path, &replay_doc)?;

        manifest_entries.push(serde_json::json!({
            "action_index": action_index,
            "resumed": false,
            "forced_action": action,
            "truncated": truncated,
            "acting_seat_return": return_value,
            "final_state_hash": final_hash,
            "report_sha256": sha256_of(&report_path),
            "replay_sha256": sha256_of(&replay_path),
        }));
    }

    // 5. State manifest (the provenance sidecar).
    let mut manifest = serde_json::json!({
        "format": "effective-splendor-m41a-branch-state-manifest",
        "version": 2,
        "source_replay_sha256": source_sha,
        "seed": source.seed,
        "branch_ply": parsed.branch_ply,
        "acting_seat": acting_seat,
        "state_hash": state_hash.as_str(),
        "observation_hash": obs_hash.as_str(),
        "legal_set_size": legal.len(),
        "ply_cap": parsed.ply_cap,
        "actions": manifest_entries,
    });
    if let Some(contract_sha) = &run_contract_sha {
        manifest["run_contract_sha256"] = serde_json::json!(contract_sha);
    }
    if manifest_path.exists() {
        fs::remove_file(&manifest_path).map_err(|e| format!("replace manifest: {e}"))?;
    }
    write_pretty(&manifest_path, &manifest)?;
    println!(
        "{}",
        serde_json::to_string(&serde_json::json!({
            "status": "run-branches-complete",
            "actions": legal.len(),
            "out_dir": out_dir.display().to_string(),
        }))
        .map_err(|e| e.to_string())?
    );
    Ok(())
}

/// Acting-seat centered return + final-state hash from a TERMINAL branch
/// report ({+1, 0, -1} win/draw/loss).
fn terminal_identity(report: &splendor_arena::ArenaReportV1, acting_seat: u8) -> (f64, String) {
    match &report.outcome {
        splendor_arena::ArenaOutcomeV1::Completed {
            result,
            replay_final_hash,
            ..
        } => {
            let ret = if result.winners.len() == 2 {
                0.0
            } else if result.winners.iter().any(|p| p.0 == acting_seat) {
                1.0
            } else {
                -1.0
            };
            (ret, replay_final_hash.clone())
        }
        _ => panic!("terminal identity requested for a non-completed outcome"),
    }
}

/// Acting-seat cap-return + cap-state hash from a TRUNCATED branch
/// report (-0.5 + 0.5*tanh(d/4), the frozen M39A/M40A/M41A formula).
fn truncated_identity(report: &splendor_arena::ArenaReportV1, acting_seat: u8) -> (f64, String) {
    match &report.outcome {
        splendor_arena::ArenaOutcomeV1::Truncated {
            cap_state_hash,
            cap_scores,
            ..
        } => {
            let seat = acting_seat as usize;
            let opp = 1 - seat;
            let d = cap_scores.get(seat).copied().unwrap_or(0) as f64
                - cap_scores.get(opp).copied().unwrap_or(0) as f64;
            let ret = -0.5 + 0.5 * (d / 4.0).tanh();
            (ret, cap_state_hash.clone())
        }
        _ => panic!("truncated identity requested for a non-truncated outcome"),
    }
}

fn write_pretty(path: &Path, value: &serde_json::Value) -> Result<(), String> {
    let text = serde_json::to_string_pretty(value).map_err(|e| e.to_string())?;
    let temp = path.with_extension("tmp-write");
    fs::write(&temp, text.as_bytes()).map_err(|e| format!("write {}: {e}", path.display()))?;
    fs::rename(&temp, path)
        .or_else(|_| fs::copy(&temp, path).and_then(|_| fs::remove_file(&temp)))
        .map_err(|e| format!("publish {}: {e}", path.display()))?;
    Ok(())
}
