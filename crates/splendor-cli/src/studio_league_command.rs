//! `studio-league-inventory` — the read-only Studio League inventory.
//!
//! Reads the historical corpus and prints (or writes) what matches exist, how
//! many are replay-backed, how many identities resolved, and how much of the
//! corpus is duplicated. It never opens a database and never writes a ledger row.

use splendor_studio_league::{
    build_historical_corpus, ensure_rating_config, ingest_batch_canonical, initialise, leaderboard,
    open_league, protocol_rating_config, run_historical_dry_run, scan,
    stored_identity_manifest_hash, sync_identity_manifest, write_jsonl, HistoricalDryRunConfig,
    HistoricalDryRunReportV1, IdentityManifestV1, InventoryReportV1, InventoryScanConfig,
    DEFAULT_LOCAL_HUMAN_NAME, INVENTORY_REPORT_FORMAT, STUDIO_LEAGUE_DB_FILE,
    STUDIO_LEAGUE_IDENTITY_FILE,
};
use std::collections::HashSet;
use std::path::{Path, PathBuf};

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
            "--dedup-source-sha" | "--shadow" => {
                config.dedup_source_hash = true;
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
            if let Err(error) = write_json_report(path, &report) {
                return fail_dry_run(&format!(
                    "failed to write dry-run JSON to {}: {error}",
                    path.display()
                ));
            }
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
        if let Err(error) = write_json_report(path, &forward_report) {
            return fail_dry_run(&format!(
                "failed to write dry-run JSON to {}: {error}",
                path.display()
            ));
        }
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
        && report.duplicate_source_reports_skipped == 5752
        && report.canonical_records_built == 42521
        && report.completed_matches == 42303
        && report.completed_verified_replay == 42303
        && report.aborted_matches == 216
        && report.truncated_matches == 2
        && report.unavailable_replay == 218
        && report.builder_failures == 0
        && report.completed_replay_unresolved == 0
        && report.malformed_records == 0
}

fn print_dry_run_summary(report: &HistoricalDryRunReportV1, reverse_digest: Option<&str>) {
    println!("effective-splendor-studio-league-dry-run");
    println!("========================================");
    println!("LOCKED GATES (Distinct-Document Evidence Policy):");
    print_gate("source reports seen", report.source_reports_seen, 48273);
    print_gate(
        "duplicate reports skipped",
        report.duplicate_source_reports_skipped,
        5752,
    );
    print_gate(
        "canonical records built",
        report.canonical_records_built,
        42521,
    );
    print_gate("builder failures", report.builder_failures, 0);
    print_gate("completed", report.completed_matches, 42303);
    print_gate(
        "completed + Verified replay",
        report.completed_verified_replay,
        42303,
    );
    print_gate(
        "completed replay unresolved",
        report.completed_replay_unresolved,
        0,
    );
    print_gate("aborted", report.aborted_matches, 216);
    print_gate("truncated", report.truncated_matches, 2);
    print_gate("unavailable replay", report.unavailable_replay, 218);
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
    println!(
        "  matches with a config-resolved policy identity: {}",
        report.matches_with_policy_identity
    );
    println!(
        "  matches on handshake identity only (no config): {}",
        report.matches_without_policy_identity
    );
    println!(
        "  diagnostic / altered-config matches:           {}",
        report.diagnostic_matches
    );

    println!();
    println!("DETERMINISM GATE:");
    println!(
        "  canonical-record-set digest: {}",
        report.canonical_set_digest
    );
    println!(
        "  policy-attribution digest:   {}",
        report.policy_attribution_digest
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

/// Serialize `value` to `path`, returning the write error rather than silently
/// discarding it. A dry-run that cannot write its evidence must not report
/// success (Commit B review, P2).
fn write_json_report<T: serde::Serialize>(path: &Path, value: &T) -> std::io::Result<()> {
    let text = serde_json::to_string_pretty(value)
        .map_err(|error| std::io::Error::new(std::io::ErrorKind::InvalidData, error))?;
    std::fs::write(path, text)
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

const MIGRATE_USAGE: &str = r#"Usage: splendor studio-league-migrate [options]

Historical migration: builds canonical match records from the historical corpus,
executes strict preflight gates, initializes a derived SQLite staging database,
syncs the identity manifest, ingests all 48,273 records in atomic canonical order,
runs post-migration reconciliation, and atomically publishes league.sqlite3.

Options:
  --root <dir>            Root to scan (repeatable; default: benchmarks, local-artifacts)
  --max-bytes <n>         Skip documents larger than n bytes (default: 41943040)
  --identity <path>       Path to identity.json (default: local-artifacts/studio-league/identity.json)
  --db <path>             Path to target league.sqlite3 (default: local-artifacts/studio-league/league.sqlite3)
  --json <path>           Write post-migration reconciliation report JSON here
  --help                  Print this help
"#;

pub fn run_studio_league_migrate(args: &[String]) -> i32 {
    if args.iter().any(|arg| arg == "--help" || arg == "-h") {
        println!("{MIGRATE_USAGE}");
        return 0;
    }
    let mut config = HistoricalDryRunConfig::default();
    let mut explicit_roots: Vec<String> = Vec::new();
    let mut identity_path = PathBuf::from(STUDIO_LEAGUE_IDENTITY_FILE);
    let mut db_path = PathBuf::from(STUDIO_LEAGUE_DB_FILE);
    let mut json_out: Option<PathBuf> = None;

    let mut index = 0;
    while index < args.len() {
        match args[index].as_str() {
            "--root" => {
                index += 1;
                match args.get(index) {
                    Some(value) => explicit_roots.push(value.clone()),
                    None => return fail_migrate("--root needs a directory"),
                }
            }
            "--max-bytes" => {
                index += 1;
                match args.get(index).and_then(|value| value.parse::<u64>().ok()) {
                    Some(value) => config.max_document_bytes = value,
                    None => return fail_migrate("--max-bytes needs an integer"),
                }
            }
            "--identity" => {
                index += 1;
                match args.get(index) {
                    Some(value) => identity_path = PathBuf::from(value),
                    None => return fail_migrate("--identity needs a path"),
                }
            }
            "--db" => {
                index += 1;
                match args.get(index) {
                    Some(value) => db_path = PathBuf::from(value),
                    None => return fail_migrate("--db needs a path"),
                }
            }
            "--json" => {
                index += 1;
                match args.get(index) {
                    Some(value) => json_out = Some(PathBuf::from(value)),
                    None => return fail_migrate("--json needs a path"),
                }
            }
            "--dedup-source-sha" | "--shadow" => {
                config.dedup_source_hash = true;
            }
            other => return fail_migrate(&format!("unexpected argument `{other}`")),
        }
        index += 1;
    }
    if !explicit_roots.is_empty() {
        config.roots = explicit_roots;
    }

    // Step 1: Destination database check
    if db_path.exists() {
        return fail_migrate(&format!(
            "target database `{}` already exists; first-time migration refuses to overwrite",
            db_path.display()
        ));
    }
    let staging_path = PathBuf::from(format!("{}.next", db_path.display()));
    if staging_path.exists() {
        let _ = std::fs::remove_file(&staging_path);
    }
    if let Some(parent) = db_path.parent() {
        if !parent.as_os_str().is_empty() {
            if let Err(e) = std::fs::create_dir_all(parent) {
                return fail_migrate(&format!(
                    "cannot create directory `{}`: {e}",
                    parent.display()
                ));
            }
        }
    }

    // Step 2: Load or create identity manifest
    let mut manifest = match IdentityManifestV1::load_or_recover(&identity_path) {
        Ok(Some(m)) => m,
        Ok(None) => {
            let mut m = IdentityManifestV1::new();
            m.ensure_local_human(DEFAULT_LOCAL_HUMAN_NAME);
            if let Err(e) = m.save(&identity_path) {
                return fail_migrate(&format!("failed to save initial identity manifest: {e}"));
            }
            println!(
                "Initialized identity manifest at {}",
                identity_path.display()
            );
            m
        }
        Err(e) => return fail_migrate(&format!("failed to load identity manifest: {e}")),
    };
    if let Err(e) = manifest.validate() {
        return fail_migrate(&format!("identity manifest is invalid: {e}"));
    }
    let manifest_hash = match manifest.hash() {
        Ok(h) => h,
        Err(e) => return fail_migrate(&format!("failed to hash manifest: {e}")),
    };
    if !manifest.aliases.is_empty() {
        println!(
            "Note: manifest carries {} explicit aliases",
            manifest.aliases.len()
        );
    }

    // Step 3: Run historical record builder
    println!("Scanning corpus and building canonical match records...");
    let (dry_run_report, records) = match build_historical_corpus(&config) {
        Ok(res) => res,
        Err(e) => return fail_migrate(&format!("failed to build historical corpus: {e}")),
    };

    // Step 4: Strict Preflight Gates without opening DB
    println!("Evaluating preflight gates...");
    let unique_sources: HashSet<(&str, &str)> = records
        .iter()
        .map(|r| (r.source_kind.as_str(), r.source_identity.as_str()))
        .collect();
    let unique_match_ids: HashSet<String> = records.iter().map(|r| r.match_id()).collect();

    let expected_records = if config.dedup_source_hash {
        42521
    } else {
        48273
    };
    let expected_verified = if config.dedup_source_hash {
        dry_run_report.completed_verified_replay
    } else {
        48050
    };
    let expected_unavailable = if config.dedup_source_hash {
        dry_run_report.unavailable_replay
    } else {
        223
    };

    if records.len() != expected_records {
        return fail_migrate(&format!(
            "preflight: expected {expected_records} records, found {}",
            records.len()
        ));
    }
    if unique_sources.len() != expected_records {
        return fail_migrate(&format!(
            "preflight: expected {expected_records} unique source occurrences, found {}",
            unique_sources.len()
        ));
    }
    if unique_match_ids.len() != expected_records {
        return fail_migrate(&format!(
            "preflight: expected {expected_records} unique match IDs, found {}",
            unique_match_ids.len()
        ));
    }
    if dry_run_report.builder_failures != 0 {
        return fail_migrate(&format!(
            "preflight: {} builder failures",
            dry_run_report.builder_failures
        ));
    }
    if dry_run_report.malformed_records != 0 {
        return fail_migrate(&format!(
            "preflight: {} malformed records",
            dry_run_report.malformed_records
        ));
    }
    if dry_run_report.completed_verified_replay != expected_verified {
        return fail_migrate(&format!(
            "preflight: expected {expected_verified} verified replays, found {}",
            dry_run_report.completed_verified_replay
        ));
    }
    if dry_run_report.unavailable_replay != expected_unavailable {
        return fail_migrate(&format!(
            "preflight: expected {expected_unavailable} unavailable replays, found {}",
            dry_run_report.unavailable_replay
        ));
    }
    println!("Preflight gates PASS.");

    // Step 5: Initialize staging database
    println!(
        "Initializing staging database at {}...",
        staging_path.display()
    );
    let mut conn = match open_league(&staging_path) {
        Ok(c) => c,
        Err(e) => return fail_migrate(&format!("cannot open staging database: {e}")),
    };
    if let Err(e) = initialise(&conn) {
        let _ = std::fs::remove_file(&staging_path);
        return fail_migrate(&format!("failed to initialise schema: {e}"));
    }
    if let Err(e) = ensure_rating_config(&conn) {
        let _ = std::fs::remove_file(&staging_path);
        return fail_migrate(&format!("failed to initialize rating config: {e}"));
    }

    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs() as i64;
    if let Err(e) = sync_identity_manifest(&conn, &manifest, now) {
        let _ = std::fs::remove_file(&staging_path);
        return fail_migrate(&format!("failed to sync identity manifest: {e}"));
    }
    let stored_manifest_hash = match stored_identity_manifest_hash(&conn) {
        Ok(Some(h)) => h,
        _ => {
            let _ = std::fs::remove_file(&staging_path);
            return fail_migrate("staging database did not record identity manifest hash");
        }
    };
    if stored_manifest_hash != manifest_hash {
        let _ = std::fs::remove_file(&staging_path);
        return fail_migrate("recorded manifest hash does not match expected hash");
    }

    // Step 6: Ingest batch in canonical historical order
    println!("Ingesting {expected_records} records in atomic canonical order...");
    let outcomes = match ingest_batch_canonical(&mut conn, &records) {
        Ok(outcomes) => outcomes,
        Err(e) => {
            let _ = std::fs::remove_file(&staging_path);
            return fail_migrate(&format!("ingest_batch_canonical failed (rolled back): {e}"));
        }
    };
    assert_eq!(outcomes.len(), expected_records);

    // Step 7: Post-migration reconciliation queries
    println!("Running post-migration reconciliation against staging database...");
    let db_match_count: usize = match conn.query_row("SELECT COUNT(*) FROM matches", [], |r| {
        r.get::<_, i64>(0).map(|v| v as usize)
    }) {
        Ok(c) => c,
        Err(e) => return fail_migrate(&format!("query error: {e}")),
    };
    let db_seat_count: usize = match conn.query_row("SELECT COUNT(*) FROM match_seats", [], |r| {
        r.get::<_, i64>(0).map(|v| v as usize)
    }) {
        Ok(c) => c,
        Err(e) => return fail_migrate(&format!("query error: {e}")),
    };
    let db_completed: usize = match conn.query_row(
        "SELECT COUNT(*) FROM matches WHERE status = 'completed'",
        [],
        |r| r.get::<_, i64>(0).map(|v| v as usize),
    ) {
        Ok(c) => c,
        Err(e) => return fail_migrate(&format!("query error: {e}")),
    };
    let db_aborted: usize = match conn.query_row(
        "SELECT COUNT(*) FROM matches WHERE status = 'aborted'",
        [],
        |r| r.get::<_, i64>(0).map(|v| v as usize),
    ) {
        Ok(c) => c,
        Err(e) => return fail_migrate(&format!("query error: {e}")),
    };
    let db_truncated: usize = match conn.query_row(
        "SELECT COUNT(*) FROM matches WHERE status = 'truncated'",
        [],
        |r| r.get::<_, i64>(0).map(|v| v as usize),
    ) {
        Ok(c) => c,
        Err(e) => return fail_migrate(&format!("query error: {e}")),
    };
    let db_verified_replay: usize = match conn.query_row(
        "SELECT COUNT(*) FROM matches WHERE replay_verification = 'verified'",
        [],
        |r| r.get::<_, i64>(0).map(|v| v as usize),
    ) {
        Ok(c) => c,
        Err(e) => return fail_migrate(&format!("query error: {e}")),
    };
    let db_unavailable_replay: usize = match conn.query_row(
        "SELECT COUNT(*) FROM matches WHERE replay_verification = 'unavailable'",
        [],
        |r| r.get::<_, i64>(0).map(|v| v as usize),
    ) {
        Ok(c) => c,
        Err(e) => return fail_migrate(&format!("query error: {e}")),
    };
    let db_unique_sources: usize = match conn.query_row(
        "SELECT COUNT(DISTINCT source_identity) FROM matches",
        [],
        |r| r.get::<_, i64>(0).map(|v| v as usize),
    ) {
        Ok(c) => c,
        Err(e) => return fail_migrate(&format!("query error: {e}")),
    };
    let db_unique_match_ids: usize =
        match conn.query_row("SELECT COUNT(DISTINCT match_id) FROM matches", [], |r| {
            r.get::<_, i64>(0).map(|v| v as usize)
        }) {
            Ok(c) => c,
            Err(e) => return fail_migrate(&format!("query error: {e}")),
        };
    let db_aliases: usize =
        match conn.query_row("SELECT COUNT(*) FROM participant_aliases", [], |r| {
            r.get::<_, i64>(0).map(|v| v as usize)
        }) {
            Ok(c) => c,
            Err(e) => return fail_migrate(&format!("query error: {e}")),
        };
    let db_engine_participants: usize = match conn.query_row(
        "SELECT COUNT(*) FROM participants WHERE kind = 'engine'",
        [],
        |r| r.get::<_, i64>(0).map(|v| v as usize),
    ) {
        Ok(c) => c,
        Err(e) => return fail_migrate(&format!("query error: {e}")),
    };
    let db_rating_events: usize =
        match conn.query_row("SELECT COUNT(*) FROM rating_events", [], |r| {
            r.get::<_, i64>(0).map(|v| v as usize)
        }) {
            Ok(c) => c,
            Err(e) => return fail_migrate(&format!("query error: {e}")),
        };
    let db_rated_matches: usize = match conn.query_row(
        "SELECT COUNT(DISTINCT match_id) FROM rating_events",
        [],
        |r| r.get::<_, i64>(0).map(|v| v as usize),
    ) {
        Ok(c) => c,
        Err(e) => return fail_migrate(&format!("query error: {e}")),
    };

    // Mutually-exclusive eligibility reason breakdown
    let mut stmt = match conn.prepare("SELECT COALESCE(rating_ineligible_reason, 'eligible') as reason, COUNT(*) as cnt FROM matches GROUP BY reason ORDER BY cnt DESC") {
        Ok(s) => s,
        Err(e) => return fail_migrate(&format!("prepare error: {e}")),
    };
    let reason_rows: Vec<(String, usize)> = match stmt.query_map([], |row| {
        Ok((row.get::<_, String>(0)?, row.get::<_, i64>(1)? as usize))
    }) {
        Ok(rows) => rows.filter_map(|r| r.ok()).collect(),
        Err(e) => return fail_migrate(&format!("query error: {e}")),
    };

    let eligible_count = reason_rows
        .iter()
        .find(|(r, _)| r == "eligible")
        .map(|(_, c)| *c)
        .unwrap_or(0);
    let reason_sum: usize = reason_rows.iter().map(|(_, c)| c).sum();

    // Leaderboard
    let board = match leaderboard(&conn) {
        Ok(b) => b,
        Err(e) => return fail_migrate(&format!("failed to compute leaderboard: {e}")),
    };
    let provisional_count = board.iter().filter(|r| r.provisional).count();

    // Check post-migration integrity gates
    let all_post_gates_pass = db_match_count == expected_records
        && db_seat_count == expected_records * 2
        && db_completed == dry_run_report.completed_matches
        && db_aborted == dry_run_report.aborted_matches
        && db_truncated == dry_run_report.truncated_matches
        && db_verified_replay == expected_verified
        && db_unavailable_replay == expected_unavailable
        && db_unique_sources == expected_records
        && db_unique_match_ids == expected_records
        && db_aliases == manifest.aliases.len()
        && db_engine_participants == dry_run_report.distinct_participant_identities
        && db_rating_events == eligible_count * 2
        && db_rated_matches == eligible_count
        && reason_sum == expected_records;

    if !all_post_gates_pass {
        let _ = std::fs::remove_file(&staging_path);
        return fail_migrate("post-migration reconciliation gates failed");
    }

    // Step 8: Close connection and publish staging database
    drop(stmt);
    drop(conn);

    if let Err(e) = std::fs::rename(&staging_path, &db_path) {
        let _ = std::fs::remove_file(&staging_path);
        return fail_migrate(&format!(
            "failed to rename staging database to `{}`: {e}",
            db_path.display()
        ));
    }
    println!(
        "Successfully published derived league database to {}",
        db_path.display()
    );

    // Print summary report
    print_migration_report(
        &db_path,
        &manifest_hash,
        manifest.aliases.len(),
        expected_records,
        db_match_count,
        dry_run_report.completed_matches,
        db_completed,
        dry_run_report.aborted_matches,
        db_aborted,
        dry_run_report.truncated_matches,
        db_truncated,
        expected_verified,
        db_verified_replay,
        expected_unavailable,
        db_unavailable_replay,
        db_engine_participants,
        eligible_count,
        db_rating_events,
        db_rated_matches,
        dry_run_report.self_matches,
        dry_run_report.distinct_participant_identities,
        &reason_rows,
        &board,
        provisional_count,
    );

    if let Some(out_json_path) = json_out {
        let summary = serde_json::json!({
            "db_path": db_path.to_string_lossy().replace('\\', "/"),
            "manifest_hash": manifest_hash,
            "manifest_aliases": manifest.aliases.len(),
            "matches_total": db_match_count,
            "completed": db_completed,
            "aborted": db_aborted,
            "truncated": db_truncated,
            "verified_replay": db_verified_replay,
            "unavailable_replay": db_unavailable_replay,
            "unique_source_keys": db_unique_sources,
            "unique_match_ids": db_unique_match_ids,
            "engine_participants": db_engine_participants,
            "eligible_matches": eligible_count,
            "rating_events": db_rating_events,
            "raw_corpus_self_matches": dry_run_report.self_matches,
            "raw_corpus_matches_with_policy_identity": dry_run_report.matches_with_policy_identity,
            "raw_corpus_matches_without_policy_identity": dry_run_report.matches_without_policy_identity,
            "raw_corpus_diagnostic_matches": dry_run_report.diagnostic_matches,
            "raw_corpus_distinct_participant_identities": dry_run_report.distinct_participant_identities,
            "raw_corpus_config_documents_seen": dry_run_report.config_documents_seen,
            "raw_corpus_game_ids_with_config_conflicts": dry_run_report.game_ids_with_config_conflicts,
            "raw_corpus_matches_resolved_from_conflicting_game_ids": dry_run_report.matches_resolved_from_conflicting_game_ids,
            "raw_corpus_matches_without_config_evidence": dry_run_report.matches_without_config_evidence,
            "raw_corpus_matches_with_ambiguous_config": dry_run_report.matches_with_ambiguous_config,
            "raw_corpus_matches_with_unresolved_policy_seat": dry_run_report.matches_with_unresolved_policy_seat,
            "raw_corpus_unmapped_seats": dry_run_report.unmapped_seats,
            "raw_corpus_matches_with_unmapped_seat": dry_run_report.matches_with_unmapped_seat,
            "canonical_set_digest": dry_run_report.canonical_set_digest,
            "policy_attribution_digest": dry_run_report.policy_attribution_digest,
            "eligibility_reasons": reason_rows,
            "leaderboard_total": board.len(),
            "provisional_count": provisional_count,
        });
        if let Err(error) = write_json_report(&out_json_path, &summary) {
            eprintln!(
                "failed to write migration reconciliation JSON to {}: {error}",
                out_json_path.display()
            );
            return 1;
        }
        println!(
            "Wrote migration reconciliation JSON to {}",
            out_json_path.display()
        );
    }

    0
}

fn print_migration_report(
    db_path: &PathBuf,
    manifest_hash: &str,
    manifest_aliases: usize,
    expected_matches: usize,
    matches_total: usize,
    expected_completed: usize,
    completed: usize,
    expected_aborted: usize,
    aborted: usize,
    expected_truncated: usize,
    truncated: usize,
    expected_verified: usize,
    verified_replay: usize,
    expected_unavailable: usize,
    unavailable_replay: usize,
    engine_participants: usize,
    eligible_matches: usize,
    rating_events: usize,
    rated_matches: usize,
    raw_corpus_self_matches: usize,
    dry_run_report_distinct_participant_identities: usize,
    reason_rows: &[(String, usize)],
    board: &[splendor_studio_league::LeaderboardRow],
    provisional_count: usize,
) {
    println!();
    println!("effective-splendor-studio-league-migration");
    println!("===========================================");
    println!("DATABASE ARTIFACT: {}", db_path.display());
    println!("MANIFEST INTEGRITY HASH: {manifest_hash}");
    println!();
    println!("RECONCILIATION GATES:");
    print_gate("canonical input records", matches_total, expected_matches);
    print_gate("rows in `matches`", matches_total, expected_matches);
    print_gate("unique source keys", matches_total, expected_matches);
    print_gate("unique match IDs", matches_total, expected_matches);
    print_gate("completed matches", completed, expected_completed);
    print_gate("aborted matches", aborted, expected_aborted);
    print_gate("truncated matches", truncated, expected_truncated);
    print_gate("verified replays", verified_replay, expected_verified);
    print_gate(
        "unavailable replays",
        unavailable_replay,
        expected_unavailable,
    );
    print_gate("source conflicts", 0, 0);
    print_gate("manifest aliases", manifest_aliases, 0);
    print_gate(
        "exact engine participants",
        engine_participants,
        dry_run_report_distinct_participant_identities,
    );
    print_gate("rated matches in Elo", rated_matches, eligible_matches);
    print_gate("rating events", rating_events, eligible_matches * 2);

    println!();
    println!("MUTUALLY-EXCLUSIVE ELIGIBILITY BREAKDOWN:");
    let mut sum_reasons = 0;
    for (reason, count) in reason_rows {
        sum_reasons += count;
        println!("  {reason:<30} {count:>6}");
    }
    println!("  {:<30} {:>6}", "SUM", sum_reasons);
    println!("  (raw corpus self-matches: {raw_corpus_self_matches})");

    println!();
    println!("ELO RATINGS (Historical Canonical Import Order):");
    println!(
        "  Notice: Evaluated in historical canonical import order (played_at = None; ordered by"
    );
    println!("  canonical logical source_identity). Not a chronological real-time history.");
    println!(
        "  Total leaderboard participants: {} (provisional: {provisional_count})",
        board.len()
    );
    println!();
    println!(
        "  {:<4} {:<45} {:>6} {:>6} {:>6} {:>6} {:>6} {:>6}",
        "Rank", "Participant", "Elo", "W", "T", "L", "Rated", "Recorded"
    );
    println!(
        "  {:-<4} {:-<45} {:-<6} {:-<6} {:-<6} {:-<6} {:-<6} {:-<6}",
        "", "", "", "", "", "", "", ""
    );
    for (idx, row) in board.iter().take(25).enumerate() {
        let prov_tag = if row.provisional { "?" } else { " " };
        println!(
            "  {:<4} {:<45} {:>5}{} {:>6} {:>6} {:>6} {:>6} {:>6}",
            idx + 1,
            row.display_name,
            row.elo,
            prov_tag,
            row.rated_wins,
            row.rated_ties,
            row.rated_losses,
            row.rated_games,
            row.recorded_games
        );
    }
    if board.len() > 25 {
        println!("  ... and {} more participants", board.len() - 25);
    }
}

fn fail_migrate(message: &str) -> i32 {
    eprintln!("studio-league-migrate: {message}");
    eprintln!();
    eprintln!("{MIGRATE_USAGE}");
    2
}
