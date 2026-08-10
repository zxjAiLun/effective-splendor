//! The `promotion-gate` CLI command.
//!
//! This command consumes an immutable M05 evaluation plan/report pair plus an
//! M09 promotion gate, verifies all bindings by canonical re-aggregation, and
//! atomically publishes one decision artifact. A policy rejection is a normal
//! result (exit 2); malformed or inconsistent inputs are fatal (exit 1).

use std::fs::File;
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};

use serde::de::DeserializeOwned;
use splendor_eval::{
    evaluate_promotion_v1, EvaluationPlanV1, EvaluationReportV1, PromotionDecisionV1,
    PromotionGateV1,
};

use crate::atomic_output;

pub const MAX_PROMOTION_INPUT_BYTES: u64 = 1024 * 1024;

const PROMOTION_USAGE: &str = "\
Usage: splendor promotion-gate --plan <plan.json> --eval-report <eval-report.json> --gate <gate.json> --out <promotion-report.json>

Verify a deterministic evaluation and atomically publish its promotion result.

Options:
  --plan <path>          EvaluationPlanV1 JSON (UTF-8, <= 1 MiB).
  --eval-report <path>   EvaluationReportV1 JSON (UTF-8, <= 1 MiB).
  --gate <path>          PromotionGateV1 JSON (UTF-8, <= 1 MiB).
  --out <path>           New PromotionReportV1 path; never overwritten.
  -h, --help             Print this help and exit 0.

Exit codes: 0 promote, 2 reject, 1 fatal error. Both policy decisions write
the output artifact and leave stdout empty.";

#[derive(Debug)]
struct PromotionCommandError(String);

impl std::fmt::Display for PromotionCommandError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

pub fn run_promotion_gate(args: &[String]) -> i32 {
    match run_promotion_gate_inner(args) {
        Ok(None | Some(PromotionDecisionV1::Promote)) => 0,
        Ok(Some(PromotionDecisionV1::Reject)) => 2,
        Err(error) => {
            let mut stderr = io::stderr().lock();
            let _ = writeln!(stderr, "error: {error}");
            let _ = stderr.flush();
            1
        }
    }
}

fn run_promotion_gate_inner(
    args: &[String],
) -> Result<Option<PromotionDecisionV1>, PromotionCommandError> {
    if wants_help(args) {
        print_stdout(PROMOTION_USAGE);
        return Ok(None);
    }

    let parsed = parse_args(args).map_err(PromotionCommandError)?;
    if !parent_dir_exists(&parsed.out) {
        return Err(PromotionCommandError(format!(
            "output parent does not exist: {}",
            parsed.out.display()
        )));
    }
    if parsed.out.exists() {
        return Err(PromotionCommandError(format!(
            "artifact already exists: {}",
            parsed.out.display()
        )));
    }

    let plan: EvaluationPlanV1 = read_json(&parsed.plan, "evaluation plan")?;
    let report: EvaluationReportV1 = read_json(&parsed.eval_report, "evaluation report")?;
    let gate: PromotionGateV1 = read_json(&parsed.gate, "promotion gate")?;
    let promotion = evaluate_promotion_v1(&plan, &report, &gate)
        .map_err(|error| PromotionCommandError(format!("promotion evaluation failed: {error}")))?;
    let decision = promotion.decision;
    let mut json = serde_json::to_string_pretty(&promotion)
        .map_err(|error| PromotionCommandError(format!("serialize promotion report: {error}")))?;
    json.push('\n');
    atomic_output::commit_single(&parsed.out, &json)
        .map_err(|error| PromotionCommandError(error.to_string()))?;
    Ok(Some(decision))
}

fn read_json<T: DeserializeOwned>(path: &Path, label: &str) -> Result<T, PromotionCommandError> {
    let file = File::open(path).map_err(|error| {
        PromotionCommandError(format!("cannot open {label} {}: {error}", path.display()))
    })?;
    let mut raw = Vec::new();
    file.take(MAX_PROMOTION_INPUT_BYTES + 1)
        .read_to_end(&mut raw)
        .map_err(|error| {
            PromotionCommandError(format!("cannot read {label} {}: {error}", path.display()))
        })?;
    if raw.len() as u64 > MAX_PROMOTION_INPUT_BYTES {
        return Err(PromotionCommandError(format!(
            "{label} exceeds {MAX_PROMOTION_INPUT_BYTES} bytes"
        )));
    }
    let text = String::from_utf8(raw)
        .map_err(|_| PromotionCommandError(format!("{label} is not valid UTF-8")))?;
    let mut de = serde_json::Deserializer::from_str(&text);
    let value = T::deserialize(&mut de)
        .map_err(|error| PromotionCommandError(format!("invalid {label}: {error}")))?;
    de.end()
        .map_err(|_| PromotionCommandError(format!("trailing data after {label} JSON")))?;
    Ok(value)
}

#[derive(Debug)]
struct PromotionArgs {
    plan: PathBuf,
    eval_report: PathBuf,
    gate: PathBuf,
    out: PathBuf,
}

fn parse_args(args: &[String]) -> Result<PromotionArgs, String> {
    let mut plan = None;
    let mut eval_report = None;
    let mut gate = None;
    let mut out = None;
    let mut index = 0;
    while index < args.len() {
        let flag = args[index].as_str();
        let slot = match flag {
            "--plan" => &mut plan,
            "--eval-report" => &mut eval_report,
            "--gate" => &mut gate,
            "--out" => &mut out,
            other if other.starts_with('-') => return Err(format!("unknown flag `{other}`")),
            other => return Err(format!("unexpected positional argument `{other}`")),
        };
        if slot.is_some() {
            return Err(format!("duplicate flag `{flag}`"));
        }
        let value = args
            .get(index + 1)
            .filter(|value| !value.starts_with("--"))
            .ok_or_else(|| format!("flag `{flag}` is missing a value"))?;
        *slot = Some(value.clone());
        index += 2;
    }

    Ok(PromotionArgs {
        plan: PathBuf::from(plan.ok_or_else(|| "missing required --plan".to_string())?),
        eval_report: PathBuf::from(
            eval_report.ok_or_else(|| "missing required --eval-report".to_string())?,
        ),
        gate: PathBuf::from(gate.ok_or_else(|| "missing required --gate".to_string())?),
        out: PathBuf::from(out.ok_or_else(|| "missing required --out".to_string())?),
    })
}

fn wants_help(args: &[String]) -> bool {
    args.iter().any(|arg| arg == "--help" || arg == "-h")
}

fn parent_dir_exists(path: &Path) -> bool {
    match path.parent() {
        Some(parent) if parent.as_os_str().is_empty() => true,
        Some(parent) => parent.is_dir(),
        None => true,
    }
}

fn print_stdout(text: &str) {
    let mut stdout = io::stdout().lock();
    let _ = writeln!(stdout, "{text}");
    let _ = stdout.flush();
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parser_requires_every_input_and_output() {
        let error = parse_args(&["--plan".into(), "plan.json".into()])
            .err()
            .unwrap();
        assert!(error.contains("--eval-report"));
    }

    #[test]
    fn parser_rejects_unknown_duplicate_and_missing_values() {
        assert!(parse_args(&["--wat".into(), "x".into()]).is_err());
        assert!(
            parse_args(&["--plan".into(), "a".into(), "--plan".into(), "b".into()])
                .unwrap_err()
                .contains("duplicate")
        );
        assert!(parse_args(&["--plan".into(), "--gate".into()])
            .unwrap_err()
            .contains("missing a value"));
    }
}
