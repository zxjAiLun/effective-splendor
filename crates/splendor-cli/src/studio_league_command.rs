//! `studio-league-inventory` — the read-only Studio League inventory.
//!
//! Reads the historical corpus and prints (or writes) what matches exist, how
//! many are replay-backed, how many identities resolved, and how much of the
//! corpus is duplicated. It never opens a database and never writes a ledger row.

use splendor_studio_league::{
    scan, write_jsonl, InventoryReportV1, InventoryScanConfig, INVENTORY_REPORT_FORMAT,
};
use std::path::PathBuf;

const USAGE: &str = r#"Usage: splendor studio-league-inventory [options]

Read-only. Scans the historical corpus for match-shaped documents and reports
candidate matches, replay coverage, identity resolution and duplication.
Never writes to the league database.

Options:
  --root <dir>            Root to scan (repeatable; default: benchmarks, local-artifacts)
  --max-bytes <n>         Skip documents larger than n bytes (default: 41943040)
  --json <path>           Write the full report JSON here
  --jsonl <path>          Write one row per candidate match here
  --summary               Print the human summary only (default when no --json)
  --help                  Print this help
"#;

pub fn run_studio_league_inventory(args: &[String]) -> i32 {
    if args.iter().any(|arg| arg == "--help" || arg == "-h") {
        println!("{USAGE}");
        return 0;
    }
    let mut config = InventoryScanConfig::default();
    let mut explicit_roots: Vec<String> = Vec::new();
    let mut json_out: Option<PathBuf> = None;
    let mut jsonl_out: Option<PathBuf> = None;

    let mut index = 0;
    while index < args.len() {
        match args[index].as_str() {
            "--root" => {
                index += 1;
                match args.get(index) {
                    Some(value) => explicit_roots.push(value.clone()),
                    None => return fail("--root needs a directory"),
                }
            }
            "--max-bytes" => {
                index += 1;
                match args.get(index).and_then(|value| value.parse::<u64>().ok()) {
                    Some(value) => config.max_document_bytes = value,
                    None => return fail("--max-bytes needs an integer"),
                }
            }
            "--json" => {
                index += 1;
                match args.get(index) {
                    Some(value) => json_out = Some(PathBuf::from(value)),
                    None => return fail("--json needs a path"),
                }
            }
            "--jsonl" => {
                index += 1;
                match args.get(index) {
                    Some(value) => jsonl_out = Some(PathBuf::from(value)),
                    None => return fail("--jsonl needs a path"),
                }
            }
            "--summary" => {}
            other => return fail(&format!("unexpected argument `{other}`")),
        }
        index += 1;
    }
    if !explicit_roots.is_empty() {
        config.roots = explicit_roots;
    }

    let report = match scan(&config) {
        Ok(report) => report,
        Err(error) => return fail(&format!("inventory scan failed: {error}")),
    };

    if let Some(path) = &json_out {
        match write_report_json(&report, path) {
            Ok(()) => println!("wrote {}", path.display()),
            Err(error) => return fail(&format!("could not write {}: {error}", path.display())),
        }
    }
    if let Some(path) = &jsonl_out {
        match write_jsonl(&report, path) {
            Ok(rows) => println!("wrote {rows} rows to {}", path.display()),
            Err(error) => return fail(&format!("could not write {}: {error}", path.display())),
        }
    }
    print_summary(&report);
    0
}

fn write_report_json(report: &InventoryReportV1, path: &PathBuf) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        if !parent.as_os_str().is_empty() {
            std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        }
    }
    let text = serde_json::to_string_pretty(report).map_err(|error| error.to_string())?;
    std::fs::write(path, text).map_err(|error| error.to_string())
}

fn print_summary(report: &InventoryReportV1) {
    let mut out = String::new();
    out.push_str(&format!("{INVENTORY_REPORT_FORMAT}\n"));
    out.push_str(&format!(
        "documents: seen {} · parsed {} · unparseable {} · skipped-too-large {}\n",
        report.documents_seen,
        report.documents_parsed,
        report.documents_unparseable,
        report.documents_skipped_too_large
    ));
    out.push_str(&format!(
        "candidate matches: {} · replays {} · evaluation reports {}\n",
        report.arena_report_documents, report.replay_documents, report.evaluation_report_documents
    ));
    out.push_str("outcomes:");
    for (status, count) in &report.status_counts {
        out.push_str(&format!(" {status} {count}"));
    }
    out.push('\n');
    out.push_str(&format!(
        "replay coverage (content join on final_state_hash): bound {} · unbound {} · no binding hash {} · completed+bound {}\n",
        report.matches_with_replay_document,
        report.matches_without_replay_document,
        report.matches_without_replay_binding_hash,
        report.completed_with_replay_document
    ));
    out.push_str(&format!(
        "replay coverage (colocated <stem>.replay.json convention): present {} · absent {}\n",
        report.matches_with_colocated_replay_file, report.matches_with_colocated_replay_missing
    ));
    out.push_str(&format!(
        "replay documents: {} · distinct sha256 {} · distinct final_state_hash {}\n",
        report.replay_documents,
        report.distinct_replay_document_sha256,
        report.distinct_replay_document_final_hash
    ));
    out.push_str(&format!(
        "duplication: match binding hash distinct {} (repeats {}) · game_id distinct {} (duplicates {})\n",
        report.distinct_replay_final_hash,
        report.repeated_replay_final_hash,
        report.distinct_game_id,
        report.duplicate_game_id
    ));
    out.push_str(&format!(
        "identity: distinct participants {} · unmapped seats {} · matches with an unmapped seat {} · distinct pairs {}\n",
        report.participant_identity_counts.len(),
        report.unmapped_seats,
        report.matches_with_unmapped_seat,
        report.pair_counts.len()
    ));
    print!("{out}");
}

fn fail(message: &str) -> i32 {
    eprintln!("studio-league-inventory: {message}");
    eprintln!();
    eprintln!("{USAGE}");
    2
}
