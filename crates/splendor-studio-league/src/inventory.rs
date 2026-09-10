//! Read-only historical inventory.
//!
//! Before any importer exists, this answers "what matches are actually on this
//! disk?". It only reads: it opens no database, writes no ledger row, and never
//! guesses an unknown participant — identities it cannot resolve are counted as
//! unmapped.
//!
//! Two distinct things are measured about replay coverage, because conflating them
//! produced a wrong number once already (see `docs/studio-league-v1.md`):
//!
//! * **colocated** — a `<stem>.replay.json` sitting next to `<stem>.report.json`.
//!   This is only the naming convention of some corpora (m13-formal, m35a, m27a).
//! * **bound** — a real `ReplayV1` document exists anywhere in the corpus whose
//!   `final_state_hash` equals the arena report's `outcome.replay_final_hash`.
//!   This is the binding the importer must use; filenames are incidental.
//!
//! Deliberately bounded: documents above `max_document_bytes` are skipped, and
//! `skip_segments` prunes corpora that are irrelevant to the ledger.

use crate::error::Result;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};

pub const INVENTORY_REPORT_FORMAT: &str = "effective-splendor-studio-league-inventory";
pub const INVENTORY_REPORT_VERSION: u32 = 1;

const ARENA_REPORT_FORMAT: &str = "effective-splendor-arena-report";
const REPLAY_FORMAT: &str = "effective-splendor-replay";
const EVALUATION_REPORT_FORMAT: &str = "effective-splendor-evaluation-report";

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct InventoryScanConfig {
    pub roots: Vec<String>,
    pub max_document_bytes: u64,
    pub skip_segments: Vec<String>,
}

impl Default for InventoryScanConfig {
    fn default() -> Self {
        Self {
            roots: vec!["benchmarks".to_string(), "local-artifacts".to_string()],
            max_document_bytes: 40 * 1024 * 1024,
            skip_segments: vec![
                "node_modules".to_string(),
                ".git".to_string(),
                ".uv-cache".to_string(),
                "m24-torch-cu124".to_string(),
                "splendor-runtime-architecture".to_string(),
                "visual-check".to_string(),
            ],
        }
    }
}

/// One candidate match, as seen on disk.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct InventoryMatchRowV1 {
    pub report_path: String,
    pub game_id: Option<String>,
    pub status: Option<String>,
    pub player_count: Option<u8>,
    pub ruleset_fingerprint: Option<String>,
    pub engine_version: Option<String>,
    pub seats: Vec<InventorySeatV1>,
    pub replay_final_hash: Option<String>,
    pub completed_plies: Option<u32>,
    pub scores: Vec<i32>,
    pub winners: Vec<u8>,
    /// Set only when a colocated `<stem>.replay.json` exists.
    pub colocated_replay_path: Option<String>,
    /// A real ReplayV1 whose `final_state_hash` matches this match's binding hash.
    pub replay_document_path: Option<String>,
    pub replay_document_sha256: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct InventorySeatV1 {
    pub seat: u8,
    pub agent_name: Option<String>,
    pub agent_version: Option<String>,
    /// `agent_name@agent_version` when both halves exist; the exact policy identity.
    pub identity_key: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct InventoryReportV1 {
    pub format: String,
    pub version: u32,
    pub roots: Vec<String>,
    pub documents_seen: u64,
    pub documents_parsed: u64,
    pub documents_unparseable: u64,
    pub documents_skipped_too_large: u64,
    pub arena_report_documents: u64,
    pub replay_documents: u64,
    pub evaluation_report_documents: u64,
    pub status_counts: BTreeMap<String, u64>,
    pub player_count_counts: BTreeMap<String, u64>,
    pub ruleset_fingerprint_counts: BTreeMap<String, u64>,
    pub engine_version_counts: BTreeMap<String, u64>,
    // --- replay coverage, measured two ways on purpose ---
    pub matches_with_colocated_replay_file: u64,
    pub matches_with_colocated_replay_missing: u64,
    /// Matches whose binding hash resolved to a real ReplayV1 anywhere in the corpus.
    pub matches_with_replay_document: u64,
    pub matches_without_replay_document: u64,
    pub matches_without_replay_binding_hash: u64,
    pub distinct_replay_document_sha256: u64,
    pub distinct_replay_document_final_hash: u64,
    // --- duplication ---
    pub distinct_replay_final_hash: u64,
    pub repeated_replay_final_hash: u64,
    pub distinct_game_id: u64,
    pub duplicate_game_id: u64,
    // --- identity ---
    pub participant_identity_counts: BTreeMap<String, u64>,
    pub pair_counts: BTreeMap<String, u64>,
    pub unmapped_seats: u64,
    pub matches_with_unmapped_seat: u64,
    /// Candidate matches whose status is `completed` and which bind a replay.
    pub completed_with_replay_document: u64,
    pub rows: Vec<InventoryMatchRowV1>,
}

impl InventoryReportV1 {
    /// Candidate matches that would be rating-eligible *on status alone*; the
    /// real decision also needs resolved identities and verification.
    pub fn completed_matches(&self) -> u64 {
        self.status_counts.get("completed").copied().unwrap_or(0)
    }
}

fn is_skipped(path: &Path, skip_segments: &[String]) -> bool {
    path.components().any(|component| {
        let text = component.as_os_str().to_string_lossy();
        skip_segments
            .iter()
            .any(|skip| text.contains(skip.as_str()))
    })
}

fn collect_json(root: &Path, config: &InventoryScanConfig, out: &mut Vec<PathBuf>) {
    let entries = match std::fs::read_dir(root) {
        Ok(entries) => entries,
        Err(_) => return,
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if is_skipped(&path, &config.skip_segments) {
            continue;
        }
        if path.is_dir() {
            collect_json(&path, config, out);
        } else if path.extension().and_then(|e| e.to_str()) == Some("json") {
            out.push(path);
        }
    }
}

fn as_string(value: &serde_json::Value, key: &str) -> Option<String> {
    value.get(key).and_then(|v| v.as_str()).map(str::to_string)
}

fn as_u64(value: &serde_json::Value, key: &str) -> Option<u64> {
    value.get(key).and_then(|v| v.as_u64())
}

fn display_path(path: &Path) -> String {
    path.to_string_lossy().replace('\\', "/")
}

/// Read a document, honouring the size bound.
fn read_document(path: &Path, config: &InventoryScanConfig) -> Option<serde_json::Value> {
    let size = std::fs::metadata(path).ok()?.len();
    if size > config.max_document_bytes {
        return None;
    }
    let text = std::fs::read_to_string(path).ok()?;
    serde_json::from_str(&text).ok()
}

/// Walk the configured roots and summarise every match-shaped document found.
pub fn scan(config: &InventoryScanConfig) -> Result<InventoryReportV1> {
    let mut report = InventoryReportV1 {
        format: INVENTORY_REPORT_FORMAT.to_string(),
        version: INVENTORY_REPORT_VERSION,
        roots: config.roots.clone(),
        ..Default::default()
    };
    let mut paths: Vec<PathBuf> = Vec::new();
    for root in &config.roots {
        collect_json(Path::new(root), config, &mut paths);
    }
    paths.sort();
    report.documents_seen = paths.len() as u64;

    // ---- pass 1: index the corpus, and build the replay binding index ----
    let mut replay_final_index: BTreeMap<String, PathBuf> = BTreeMap::new();
    let mut replay_shas: BTreeSet<String> = BTreeSet::new();
    let mut arena_paths: Vec<PathBuf> = Vec::new();

    for path in &paths {
        let size = match std::fs::metadata(path) {
            Ok(meta) => meta.len(),
            Err(_) => continue,
        };
        if size > config.max_document_bytes {
            report.documents_skipped_too_large += 1;
            continue;
        }
        let text = match std::fs::read_to_string(path) {
            Ok(text) => text,
            Err(_) => {
                report.documents_unparseable += 1;
                continue;
            }
        };
        let value: serde_json::Value = match serde_json::from_str(&text) {
            Ok(value) => value,
            Err(_) => {
                report.documents_unparseable += 1;
                continue;
            }
        };
        report.documents_parsed += 1;
        match value.get("format").and_then(|v| v.as_str()).unwrap_or("") {
            REPLAY_FORMAT => {
                report.replay_documents += 1;
                replay_shas.insert(hex::encode(Sha256::digest(text.as_bytes())));
                if let Some(hash) = value.get("final_state_hash").and_then(|v| v.as_str()) {
                    // First writer wins; duplicates are counted elsewhere.
                    replay_final_index
                        .entry(hash.to_string())
                        .or_insert_with(|| path.clone());
                }
            }
            EVALUATION_REPORT_FORMAT => report.evaluation_report_documents += 1,
            ARENA_REPORT_FORMAT => {
                report.arena_report_documents += 1;
                arena_paths.push(path.clone());
            }
            _ => {}
        }
    }
    report.distinct_replay_document_sha256 = replay_shas.len() as u64;
    report.distinct_replay_document_final_hash = replay_final_index.len() as u64;

    // ---- pass 2: per-match rows and joins ----
    let mut replay_final_hashes: BTreeMap<String, u64> = BTreeMap::new();
    let mut game_ids: BTreeMap<String, u64> = BTreeMap::new();

    for path in &arena_paths {
        let Some(value) = read_document(path, config) else {
            continue;
        };
        let outcome = value
            .get("outcome")
            .cloned()
            .unwrap_or(serde_json::Value::Null);
        let status = outcome
            .get("status")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown")
            .to_string();
        *report.status_counts.entry(status.clone()).or_insert(0) += 1;

        let player_count = as_u64(&value, "player_count");
        *report
            .player_count_counts
            .entry(
                player_count
                    .map(|v| v.to_string())
                    .unwrap_or_else(|| "?".into()),
            )
            .or_insert(0) += 1;

        let ruleset = as_string(&value, "ruleset_fingerprint");
        *report
            .ruleset_fingerprint_counts
            .entry(ruleset.clone().unwrap_or_else(|| "(none)".into()))
            .or_insert(0) += 1;

        let engine_version = as_string(&value, "engine_version");
        *report
            .engine_version_counts
            .entry(engine_version.clone().unwrap_or_else(|| "(none)".into()))
            .or_insert(0) += 1;

        let game_id = as_string(&value, "game_id");
        if let Some(id) = &game_id {
            *game_ids.entry(id.clone()).or_insert(0) += 1;
        }

        let mut seats: Vec<InventorySeatV1> = Vec::new();
        if let Some(array) = value.get("agents").and_then(|v| v.as_array()) {
            for agent in array {
                let agent_name = as_string(agent, "agent_name");
                let agent_version = as_string(agent, "agent_version");
                let identity_key = match (&agent_name, &agent_version) {
                    (Some(name), Some(version)) => Some(format!("{name}@{version}")),
                    _ => None,
                };
                if let Some(key) = &identity_key {
                    *report
                        .participant_identity_counts
                        .entry(key.clone())
                        .or_insert(0) += 1;
                } else {
                    report.unmapped_seats += 1;
                }
                seats.push(InventorySeatV1 {
                    seat: as_u64(agent, "seat").unwrap_or(seats.len() as u64) as u8,
                    agent_name,
                    agent_version,
                    identity_key,
                });
            }
        }
        if seats.iter().any(|seat| seat.identity_key.is_none()) {
            report.matches_with_unmapped_seat += 1;
        }
        let mut pair: Vec<String> = seats
            .iter()
            .map(|seat| {
                seat.identity_key
                    .clone()
                    .unwrap_or_else(|| "(unmapped)".into())
            })
            .collect();
        pair.sort();
        *report.pair_counts.entry(pair.join(" ~ ")).or_insert(0) += 1;

        let replay_final_hash = outcome
            .get("replay_final_hash")
            .and_then(|v| v.as_str())
            .map(str::to_string);
        if let Some(hash) = &replay_final_hash {
            *replay_final_hashes.entry(hash.clone()).or_insert(0) += 1;
        }
        let completed_plies = outcome
            .get("completed_plies")
            .and_then(|v| v.as_u64())
            .map(|v| v as u32);
        let scores = outcome
            .get("result")
            .and_then(|r| r.get("scores"))
            .and_then(|v| v.as_array())
            .map(|a| {
                a.iter()
                    .filter_map(|v| v.as_i64().map(|n| n as i32))
                    .collect()
            })
            .unwrap_or_default();
        let winners = outcome
            .get("result")
            .and_then(|r| r.get("winners"))
            .and_then(|v| v.as_array())
            .map(|a| {
                a.iter()
                    .filter_map(|v| v.as_u64().map(|n| n as u8))
                    .collect()
            })
            .unwrap_or_default();

        // (a) colocated convention: `<stem>.report.json` beside `<stem>.replay.json`.
        let colocated = path
            .file_name()
            .and_then(|name| name.to_str())
            .and_then(|name| name.strip_suffix(".report.json"))
            .map(|stem| path.with_file_name(format!("{stem}.replay.json")))
            .filter(|candidate| candidate.is_file());

        // (b) the binding that actually matters: content join on final_state_hash.
        let bound = replay_final_hash
            .as_ref()
            .and_then(|hash| replay_final_index.get(hash).cloned());
        let bound_sha = bound
            .as_ref()
            .and_then(|path| std::fs::read(path).ok())
            .map(|bytes| hex::encode(Sha256::digest(&bytes)));

        match (&colocated, &bound) {
            (Some(_), _) => {
                report.matches_with_colocated_replay_file += 1;
            }
            (None, _) => report.matches_with_colocated_replay_missing += 1,
        }
        match &bound {
            Some(_) => {
                report.matches_with_replay_document += 1;
                if status == "completed" {
                    report.completed_with_replay_document += 1;
                }
            }
            None => {
                report.matches_without_replay_document += 1;
                if replay_final_hash.is_none() {
                    report.matches_without_replay_binding_hash += 1;
                }
            }
        }

        report.rows.push(InventoryMatchRowV1 {
            report_path: display_path(path),
            game_id,
            status: Some(status),
            player_count: player_count.map(|v| v as u8),
            ruleset_fingerprint: ruleset,
            engine_version,
            seats,
            replay_final_hash,
            completed_plies,
            scores,
            winners,
            colocated_replay_path: colocated.as_ref().map(|p| display_path(p)),
            replay_document_path: bound.as_ref().map(|p| display_path(p)),
            replay_document_sha256: bound_sha,
        });
    }

    report.distinct_replay_final_hash = replay_final_hashes.len() as u64;
    report.repeated_replay_final_hash = replay_final_hashes
        .values()
        .map(|count| count.saturating_sub(1))
        .sum();
    report.distinct_game_id = game_ids.len() as u64;
    report.duplicate_game_id = game_ids.values().map(|count| count.saturating_sub(1)).sum();
    Ok(report)
}

/// Write the per-match rows as JSONL. Local artifact; never a source of truth.
pub fn write_jsonl(report: &InventoryReportV1, path: &Path) -> Result<usize> {
    if let Some(parent) = path.parent() {
        if !parent.as_os_str().is_empty() {
            std::fs::create_dir_all(parent)?;
        }
    }
    let mut buffer = String::new();
    for row in &report.rows {
        buffer.push_str(&serde_json::to_string(row)?);
        buffer.push('\n');
    }
    std::fs::write(path, buffer)?;
    Ok(report.rows.len())
}
