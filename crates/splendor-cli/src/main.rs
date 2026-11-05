mod atomic_output;
mod environment;
mod eval_command;
mod rating_command;

use std::fs::{self, File};
use std::io::{self, BufReader, Read, Write};
use std::path::{Path, PathBuf};

use clap::{Parser, Subcommand};
use splendor_arena::{ArenaConfig, ArenaRunner};
use splendor_replay::{verify_replay, ReplayV1};

#[derive(Parser)]
#[command(name = "splendor", about = "璀璨宝石规则环境与外部 Agent 评测")]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// 输出引擎、协议与牌库版本
    Version,
    /// 输出牌库与基础规则 JSON
    Catalog,
    /// 启动持久 NDJSON 训练环境
    Env,
    /// 启动参考随机 Agent
    AgentRandom {
        #[arg(long)]
        seed: u64,
    },
    /// 运行一场外部程序对战
    RunMatch {
        #[arg(long)]
        config: PathBuf,
        #[arg(long)]
        report_out: PathBuf,
        #[arg(long)]
        replay_out: PathBuf,
    },
    /// 校验裁判回放
    VerifyReplay {
        #[arg(long)]
        input: PathBuf,
    },
    /// 按种子与座位轮换执行评测；eval --help 查看参数
    Eval,
    /// 创建 1v1 循环赛计划；rating-plan --help 查看参数
    RatingPlan,
    /// 执行 1v1 循环赛；rating-run --help 查看参数
    RatingRun,
    /// 从比赛记录计算评级；rating-report --help 查看参数
    RatingReport,
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let driver: Option<fn(&[String]) -> i32> = match args.get(1).map(String::as_str) {
        Some("eval") => Some(eval_command::run_eval),
        Some("rating-plan") => Some(rating_command::run_rating_plan),
        Some("rating-run") => Some(rating_command::run_rating_run),
        Some("rating-report") => Some(rating_command::run_rating_report),
        _ => None,
    };
    if let Some(driver) = driver {
        std::process::exit(driver(&args[2..]));
    }
    match execute(Cli::parse().command) {
        Ok(code) => std::process::exit(code),
        Err(error) => {
            eprintln!("error: {error}");
            std::process::exit(1);
        }
    }
}

fn execute(command: Command) -> Result<i32, String> {
    match command {
        Command::Version => {
            println!("engine={}", splendor_core::ENGINE_VERSION);
            println!("protocol={}", splendor_protocol::PROTOCOL_VERSION);
            println!("catalog={}", splendor_catalog::CATALOG_VERSION);
            println!("environment={}", environment::ENV_VERSION);
        }
        Command::Catalog => println!("{}", environment::catalog()),
        Command::Env => {
            environment::serve(io::stdin().lock(), io::stdout().lock())
                .map_err(|e| e.to_string())?;
        }
        Command::AgentRandom { seed } => {
            return Ok(
                if splendor_agent::run_random_agent(
                    BufReader::new(io::stdin().lock()),
                    io::stdout().lock(),
                    io::stderr().lock(),
                    seed,
                )
                .is_ok()
                {
                    0
                } else {
                    1
                },
            );
        }
        Command::RunMatch {
            config,
            report_out,
            replay_out,
        } => return run_match(&config, &report_out, &replay_out),
        Command::VerifyReplay { input } => {
            let replay: ReplayV1 = serde_json::from_reader(BufReader::new(
                File::open(input).map_err(|e| e.to_string())?,
            ))
            .map_err(|e| e.to_string())?;
            verify_replay(&replay).map_err(|e| e.to_string())?;
            println!("{}", serde_json::json!({"valid": true}));
        }
        Command::Eval | Command::RatingPlan | Command::RatingRun | Command::RatingReport => {
            unreachable!("evaluation commands are dispatched before argument parsing")
        }
    }
    Ok(0)
}

fn pretty_line(value: &impl serde::Serialize) -> Result<String, String> {
    serde_json::to_string_pretty(value)
        .map(|s| s + "\n")
        .map_err(|e| e.to_string())
}

fn run_match(config: &Path, report_out: &Path, replay_out: &Path) -> Result<i32, String> {
    if report_out == replay_out {
        return Err("--report-out and --replay-out must differ".into());
    }
    for path in [report_out, replay_out] {
        if path.exists() {
            return Err(format!("output already exists: {}", path.display()));
        }
        let parent = path.parent().filter(|p| !p.as_os_str().is_empty());
        if parent.is_some_and(|p| !p.is_dir()) {
            return Err(format!("output parent does not exist: {}", path.display()));
        }
    }
    let mut raw = Vec::new();
    File::open(config)
        .map_err(|e| e.to_string())?
        .take(1024 * 1024 + 1)
        .read_to_end(&mut raw)
        .map_err(|e| e.to_string())?;
    if raw.len() > 1024 * 1024 {
        return Err("arena config exceeds 1 MiB".into());
    }
    let config: ArenaConfig = serde_json::from_slice(&raw).map_err(|e| e.to_string())?;
    let run = ArenaRunner::run(config).map_err(|e| e.to_string())?;
    let report_json = pretty_line(&run.report)?;
    let outcome_json = serde_json::to_string(&run.report.outcome).map_err(|e| e.to_string())?;
    let code = if let Some(replay) = &run.replay {
        verify_replay(replay).map_err(|e| e.to_string())?;
        match &run.report.outcome {
            splendor_arena::ArenaOutcomeV1::Completed {
                replay_final_hash, ..
            } if replay_final_hash == replay.final_state_hash.as_str() => {}
            _ => return Err("report and replay disagree".into()),
        }
        atomic_output::commit_completed_with(
            replay_out,
            &pretty_line(replay)?,
            report_out,
            &report_json,
            atomic_output::publish_new,
        )
        .map_err(|e| e.to_string())?;
        0
    } else {
        atomic_output::commit_aborted_with(report_out, &report_json, atomic_output::publish_new)
            .map_err(|e| e.to_string())?;
        2
    };
    let mut stdout = io::stdout().lock();
    if let Err(error) = writeln!(stdout, "{outcome_json}").and_then(|_| stdout.flush()) {
        let _ = fs::remove_file(report_out);
        if run.replay.is_some() {
            let _ = fs::remove_file(replay_out);
        }
        return Err(error.to_string());
    }
    Ok(code)
}
