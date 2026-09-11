//! `studio-league-inventory` — the read-only Studio League inventory.
//!
//! Reads the historical corpus and prints (or writes) what matches exist, how
//! many are replay-backed, how many identities resolved, and how much of the
//! corpus is duplicated. It never opens a database and never writes a ledger row.

use splendor_studio_league::{
    run_historical_dry_run, scan, write_jsonl, HistoricalDryRunConfig, HistoricalDryRunReportV1,
    InventoryReportV1, InventoryScanConfig, INVENTORY_REPORT_FORMAT,
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

const DRY_RUN_USAGE: &str = r#"Usage: splendor studio-league-dry-run [options]

Read-only. Executes the full historical migration path on all arena reports:
  read bytes -> hash -> parse report -> resolve replay -> verify -> canonical StudioMatchRecordV1 -> validate_for_ingest()

Never opens SQLite or writes to the league database.

Options:
  --root <dir>            Root to scan (repeatable; default: benchmarks, local-artifacts)
  --max-bytes <n>         Skip documents larger than n bytes (default: 41943040)
  --json <path>           Write the forward dry-run report JSON here
  --roots-reverse         Run roots in reverse order only (no forward/reverse check)
  --check-determinism     Run forward AND reverse roots and assert identical digest (default)
  --help                  Print this help
"#;

pub fn run_studio_league_dry_run(args: &[String]) -> i32 {
    if args.iter().any(|arg| arg == "--help" || arg == "-h") {
        println!("{DRY_RUN_USAGE}");
        return 0;
    }
    let mut config = HistoricalDryRunConfig::default();
    let mut explicit_roots: Vec<String> = Vec::new();
    let mut json_out: Option<PathBuf> = None;
    let mut reverse_only = false;
    let mut check_determinism = true;

    let mut index = 0;
    while index < args.len() {
        match args[index].as_str() {
            "--root" => {
                index += 1;
                match args.get(index) {
                    Some(value) => explicit_roots.push(value.clone()),
                    None => return fail_dry_run("--root needs a directory"),
                }
            }
            "--max-bytes" => {
                index += 1;
                match args.get(index).and_then(|value| value.parse::<u64>().ok()) {
                    Some(value) => config.max_document_bytes = value,
                    None => return fail_dry_run("--max-bytes needs an integer"),
                }
            }
            "--json" => {
                index += 1;
                match args.get(index) {
                    Some(value) => json_out = Some(PathBuf::from(value)),
                    None => return fail_dry_run("--json needs a path"),
                }
            }
            "--roots-reverse" => {
                reverse_only = true;
                check_determinism = false;
            }
            "--check-determinism" => {
                check_determinism = true;
                reverse_only = false;
            }
            other => return fail_dry_run(&format!("unexpected argument `{other}`")),
        }
        index += 1;
    }
    if !explicit_roots.is_empty() {
        config.roots = explicit_roots;
    }

    if reverse_only {
        config.roots.reverse();
        let report = match run_historical_dry_run(&config) {
            Ok(r) => r,
            Err(e) => return fail_dry_run(&format!("dry-run failed: {e}")),
        };
        if let Some(path) = &json_out {
            let _ = std::fs::write(
                path,
                serde_json::to_string_pretty(&report).unwrap_or_default(),
            );
        }
        print_dry_run_summary(&report, None);
        return if dry_run_gates_pass(&report) { 0 } else { 1 };
    }

    // Forward run
    let forward_report = match run_historical_dry_run(&config) {
        Ok(r) => r,
        Err(e) => return fail_dry_run(&format!("forward dry-run failed: {e}")),
    };

    let reverse_digest = if check_determinism {
        let mut rev_config = config.clone();
        rev_config.roots.reverse();
        let rev_report = match run_historical_dry_run(&rev_config) {
            Ok(r) => r,
            Err(e) => return fail_dry_run(&format!("reverse dry-run failed: {e}")),
        };
        Some(rev_report.canonical_set_digest)
    } else {
        None
    };

    if let Some(path) = &json_out {
        let _ = std::fs::write(
            path,
            serde_json::to_string_pretty(&forward_report).unwrap_or_default(),
        );
    }
    print_dry_run_summary(&forward_report, reverse_digest.as_deref());

    let gates_ok = dry_run_gates_pass(&forward_report);
    let determinism_ok = match reverse_digest {
        Some(digest) => digest == forward_report.canonical_set_digest,
        None => true,
    };

    if gates_ok && determinism_ok {
        0
    } else {
        1
    }
}

fn dry_run_gates_pass(report: &HistoricalDryRunReportV1) -> bool {
    report.source_reports_seen == 48273
        && report.canonical_records_built == 48273
        && report.builder_failures == 0
        && report.completed_matches == 48050
        && report.completed_verified_replay == 48050
        && report.completed_replay_unresolved == 0
        && report.aborted_matches == 221
        && report.truncated_matches == 2
        && report.unavailable_replay == 223
        && report.malformed_records == 0
}

fn print_dry_run_summary(report: &HistoricalDryRunReportV1, reverse_digest: Option<&str>) {
    println!("effective-splendor-studio-league-dry-run");
    println!("========================================");
    println!("LOCKED GATES:");
    print_gate("source reports", report.source_reports_seen, 48273);
    print_gate(
        "canonical records built",
        report.canonical_records_built,
        48273,
    );
    print_gate("builder failures", report.builder_failures, 0);
    print_gate("completed", report.completed_matches, 48050);
    print_gate(
        "completed + Verified replay",
        report.completed_verified_replay,
        48050,
    );
    print_gate(
        "completed replay unresolved",
        report.completed_replay_unresolved,
        0,
    );
    print_gate("aborted", report.aborted_matches, 221);
    print_gate("truncated", report.truncated_matches, 2);
    print_gate("unavailable replay", report.unavailable_replay, 223);
    print_gate("malformed canonical records", report.malformed_records, 0);

    println!();
    println!("REPORTED CORPUS CHARACTERISTICS:");
    println!(
        "  completed with >1 index candidate:             {}",
        report.completed_with_multiple_candidates
    );
    println!(
        "  completed with >1 verification-pass candidate: {}",
        report.completed_with_multiple_passing_candidates
    );
    println!(
        "  selected distinct replay document SHA:         {}",
        report.selected_distinct_replay_document_sha
    );
    println!(
        "  distinct source document SHA:                  {}",
        report.distinct_source_document_sha
    );
    println!(
        "  source-document SHA duplicates:                {}",
        report.source_document_sha_duplicates
    );
    println!(
        "  unmapped seats:                                {}",
        report.unmapped_seats
    );
    println!(
        "  matches with unmapped seats:                   {}",
        report.matches_with_unmapped_seat
    );
    println!(
        "  self-matches (same participant 1v1):           {}",
        report.self_matches
    );
    println!(
        "  exact participant identities:                  {}",
        report.distinct_participant_identities
    );

    println!();
    println!("DETERMINISM GATE:");
    println!(
        "  canonical-record-set digest: {}",
        report.canonical_set_digest
    );
    if let Some(rev) = reverse_digest {
        println!("  reverse-root order digest:   {}", rev);
        let match_str = if rev == report.canonical_set_digest {
            "PASS (identical)"
        } else {
            "FAIL (diverged)"
        };
        println!("  root-order independence:     {}", match_str);
    }
}

fn print_gate(label: &str, actual: usize, expected: usize) {
    let status = if actual == expected { "PASS" } else { "FAIL" };
    println!("  {label:<30} {actual:>6} (expected {expected:>5}) [{status}]");
}

fn fail_dry_run(message: &str) -> i32 {
    eprintln!("studio-league-dry-run: {message}");
    eprintln!();
    eprintln!("{DRY_RUN_USAGE}");
    2
}

fn fail(message: &str) -> i32 {
    eprintln!("studio-league-inventory: {message}");
    eprintln!();
    eprintln!("{USAGE}");
    2
}
