//! M16 1v1 round-robin planning, execution, and rating commands.

use std::fs::{self, File};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};

use serde::de::DeserializeOwned;
use splendor_eval::{
    build_rating_report_v1, build_round_robin_plan_v1, round_robin_plan_hash_v1,
    EvaluationReportV1, RatingConfigV1, RatingRegistryV1, RatingReportV1, RoundRobinPlanV1,
};

use crate::{atomic_output, eval_command};

const MAX_DOCUMENT_BYTES: u64 = 8 * 1024 * 1024;
const PLAN_USAGE: &str = "Usage: splendor rating-plan --registry <registry.json> --config <config.json> --out <round-robin-plan.json>";
const RUN_USAGE: &str = "Usage: splendor rating-run --plan <round-robin-plan.json> --out-dir <dir>";
const REPORT_USAGE: &str = "Usage: splendor rating-report --plan <round-robin-plan.json> --evaluation-dir <rating-run-dir> --out <rating-report.json>";

pub fn run_rating_plan(args: &[String]) -> i32 {
    command(|| {
        if wants_help(args) {
            print_help(PLAN_USAGE);
            return Ok(());
        }
        let flags = parse_flags(args, &["--registry", "--config", "--out"])?;
        let registry: RatingRegistryV1 = read_json(path(&flags, "--registry")?)?;
        let config: RatingConfigV1 = read_json(path(&flags, "--config")?)?;
        let plan = build_round_robin_plan_v1(&registry, &config)?;
        commit_json(path(&flags, "--out")?, &plan)
    })
}

pub fn run_rating_run(args: &[String]) -> i32 {
    command(|| {
        if wants_help(args) {
            print_help(RUN_USAGE);
            return Ok(());
        }
        let flags = parse_flags(args, &["--plan", "--out-dir"])?;
        let plan_path = path(&flags, "--plan")?;
        let out_dir = path(&flags, "--out-dir")?;
        let plan: RoundRobinPlanV1 = read_json(plan_path)?;
        plan.validate()?;
        ensure_output_parent(out_dir)?;
        let report_path = out_dir.join("rating-report.json");
        let persisted_plan = out_dir.join("round-robin-plan.json");
        let persisted_hash = out_dir.join("round-robin-plan-hash.txt");
        for target in [&report_path, &persisted_plan, &persisted_hash] {
            ensure_absent(target)?;
        }
        for pair in &plan.pairs {
            let pair_dir = pair_dir(out_dir, pair.pair_index);
            if pair_dir.exists() {
                return Err(format!(
                    "pair output already exists: {}",
                    pair_dir.display()
                ));
            }
        }
        fs::create_dir_all(out_dir).map_err(|e| format!("create output directory failed: {e}"))?;
        fs::create_dir_all(out_dir.join("pairs"))
            .map_err(|e| format!("create pairs directory failed: {e}"))?;

        for pair in &plan.pairs {
            eval_command::execute_plan(
                pair.evaluation_plan.clone(),
                &pair_dir(out_dir, pair.pair_index),
            )?;
        }
        let reports = read_pair_reports(&plan, out_dir)?;
        let report = build_rating_report_v1(&plan, &reports)?;
        publish_run_markers(&plan, &report, out_dir)
    })
}

pub fn run_rating_report(args: &[String]) -> i32 {
    command(|| {
        if wants_help(args) {
            print_help(REPORT_USAGE);
            return Ok(());
        }
        let flags = parse_flags(args, &["--plan", "--evaluation-dir", "--out"])?;
        let plan: RoundRobinPlanV1 = read_json(path(&flags, "--plan")?)?;
        plan.validate()?;
        let reports = read_pair_reports(&plan, path(&flags, "--evaluation-dir")?)?;
        let report = build_rating_report_v1(&plan, &reports)?;
        commit_json(path(&flags, "--out")?, &report)
    })
}

fn publish_run_markers(
    plan: &RoundRobinPlanV1,
    report: &RatingReportV1,
    out_dir: &Path,
) -> Result<(), String> {
    let plan_path = out_dir.join("round-robin-plan.json");
    let hash_path = out_dir.join("round-robin-plan-hash.txt");
    let report_path = out_dir.join("rating-report.json");
    commit_json(&plan_path, plan)?;
    if let Err(error) = commit_text(
        &hash_path,
        &format!("{}\n", round_robin_plan_hash_v1(plan)?),
    ) {
        let _ = fs::remove_file(&plan_path);
        return Err(error);
    }
    if let Err(error) = commit_json(&report_path, report) {
        let _ = fs::remove_file(&plan_path);
        let _ = fs::remove_file(&hash_path);
        return Err(error);
    }
    Ok(())
}

fn read_pair_reports(
    plan: &RoundRobinPlanV1,
    root: &Path,
) -> Result<Vec<EvaluationReportV1>, String> {
    plan.pairs
        .iter()
        .map(|pair| read_json(&pair_dir(root, pair.pair_index).join("eval-report.json")))
        .collect()
}

fn pair_dir(root: &Path, pair_index: u32) -> PathBuf {
    root.join("pairs").join(format!("pair-{pair_index:04}"))
}

fn command<F>(run: F) -> i32
where
    F: FnOnce() -> Result<(), String>,
{
    match run() {
        Ok(()) => 0,
        Err(error) => {
            let _ = writeln!(io::stderr().lock(), "error: {error}");
            1
        }
    }
}

fn read_json<T: DeserializeOwned>(path: &Path) -> Result<T, String> {
    let file = File::open(path).map_err(|e| format!("cannot open {}: {e}", path.display()))?;
    let mut bytes = Vec::new();
    file.take(MAX_DOCUMENT_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|e| format!("cannot read {}: {e}", path.display()))?;
    if bytes.len() as u64 > MAX_DOCUMENT_BYTES {
        return Err(format!("document exceeds {MAX_DOCUMENT_BYTES} bytes"));
    }
    let text = String::from_utf8(bytes).map_err(|_| format!("{} is not UTF-8", path.display()))?;
    let mut de = serde_json::Deserializer::from_str(&text);
    let value =
        T::deserialize(&mut de).map_err(|e| format!("invalid JSON {}: {e}", path.display()))?;
    de.end()
        .map_err(|_| format!("trailing data after JSON in {}", path.display()))?;
    Ok(value)
}

fn commit_json<T: serde::Serialize>(target: &Path, value: &T) -> Result<(), String> {
    let mut text = serde_json::to_string_pretty(value).map_err(|e| e.to_string())?;
    text.push('\n');
    commit_text(target, &text)
}

fn commit_text(target: &Path, text: &str) -> Result<(), String> {
    ensure_output_parent(target)?;
    ensure_absent(target)?;
    atomic_output::commit_single_with(target, text, atomic_output::publish_new)
        .map_err(|e| e.to_string())
}

fn ensure_absent(path: &Path) -> Result<(), String> {
    if path.exists() {
        Err(format!("artifact already exists: {}", path.display()))
    } else {
        Ok(())
    }
}

fn ensure_output_parent(path: &Path) -> Result<(), String> {
    match path.parent() {
        Some(parent) if !parent.as_os_str().is_empty() && !parent.is_dir() => Err(format!(
            "output parent does not exist: {}",
            parent.display()
        )),
        _ => Ok(()),
    }
}

fn parse_flags(
    args: &[String],
    allowed: &[&str],
) -> Result<std::collections::HashMap<String, PathBuf>, String> {
    let mut values = std::collections::HashMap::new();
    let mut i = 0;
    while i < args.len() {
        let flag = args[i].as_str();
        if !allowed.contains(&flag) {
            return Err(format!("unknown argument '{flag}'"));
        }
        let value = args
            .get(i + 1)
            .ok_or_else(|| format!("flag '{flag}' is missing a value"))?;
        if value.starts_with("--") {
            return Err(format!("flag '{flag}' is missing a value"));
        }
        if values
            .insert(flag.to_string(), PathBuf::from(value))
            .is_some()
        {
            return Err(format!("duplicate flag '{flag}'"));
        }
        i += 2;
    }
    for flag in allowed {
        if !values.contains_key(*flag) {
            return Err(format!("missing required {flag}"));
        }
    }
    Ok(values)
}

fn path<'a>(
    flags: &'a std::collections::HashMap<String, PathBuf>,
    name: &str,
) -> Result<&'a Path, String> {
    flags
        .get(name)
        .map(PathBuf::as_path)
        .ok_or_else(|| format!("missing required {name}"))
}

fn wants_help(args: &[String]) -> bool {
    args.iter().any(|arg| arg == "-h" || arg == "--help")
}
fn print_help(text: &str) {
    let _ = writeln!(io::stdout().lock(), "{text}");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn strict_flags_reject_unknown_and_duplicate() {
        assert!(parse_flags(
            &["--x".into(), "a".into(), "--bad".into(), "b".into()],
            &["--x"]
        )
        .is_err());
        assert!(parse_flags(
            &["--x".into(), "a".into(), "--x".into(), "b".into()],
            &["--x"]
        )
        .is_err());
    }

    #[test]
    fn pair_paths_never_use_agent_ids() {
        assert_eq!(
            pair_dir(Path::new("out"), 7),
            Path::new("out").join("pairs").join("pair-0007")
        );
    }
}
