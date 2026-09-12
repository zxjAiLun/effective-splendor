//! Duplicate-preserving ReplayV1 content index for historical migration.
//!
//! Arena reports bind to a terminal state via `replay_final_hash`, but that
//! hash is not a globally unique replay document id. The exact source bytes are
//! identified separately by SHA-256. Consequently the index stores a sorted
//! candidate list for each final-state hash; it never lets a `HashMap` overwrite
//! duplicate documents and it never guesses from a neighbouring filename.

use crate::error::{Result, StudioLeagueError};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use splendor_replay::{ReplayV1, REPLAY_FORMAT, REPLAY_VERSION};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

/// A scanned directory with an explicit or detected logical namespace.
///
/// This provides machine-portable, cross-platform logical source paths such as
/// `benchmarks/m41a-corpus/...` or `local-artifacts/m40a-run/...`. Drive letters,
/// path separator differences, and machine-specific clone roots never leak into
/// stored ledger records.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub struct CorpusRoot {
    pub namespace: String,
    pub path: PathBuf,
}

impl CorpusRoot {
    pub fn new(namespace: impl Into<String>, path: impl Into<PathBuf>) -> Self {
        Self {
            namespace: namespace.into(),
            path: path.into(),
        }
    }

    pub fn from_spec(spec: &str) -> Self {
        if let Some((namespace, path)) = spec.split_once('=') {
            Self::new(namespace.trim(), PathBuf::from(path.trim()))
        } else {
            let path = PathBuf::from(spec);
            let namespace = default_namespace_for_root(&path);
            Self::new(namespace, path)
        }
    }

    pub fn resolve_logical_path(&self, file_path: &Path) -> Result<String> {
        let rel = match file_path.strip_prefix(&self.path) {
            Ok(rel) => rel,
            Err(_) => {
                if let (Ok(canon_file), Ok(canon_root)) =
                    (file_path.canonicalize(), self.path.canonicalize())
                {
                    if let Ok(rel) = canon_file.strip_prefix(&canon_root) {
                        return Ok(format_logical(&self.namespace, rel));
                    }
                }
                return Err(StudioLeagueError::Invalid(format!(
                    "file path `{}` is not inside corpus root `{}`",
                    file_path.display(),
                    self.path.display()
                )));
            }
        };
        Ok(format_logical(&self.namespace, rel))
    }
}

pub fn default_namespace_for_root(path: &Path) -> String {
    let normalized = path.to_string_lossy().replace('\\', "/");
    if normalized == "benchmarks" || normalized.ends_with("/benchmarks") {
        return "benchmarks".to_string();
    }
    if normalized == "local-artifacts" || normalized.ends_with("/local-artifacts") {
        return "local-artifacts".to_string();
    }
    if let Some(name) = path.file_name().and_then(|n| n.to_str()) {
        if !name.is_empty() {
            return name.to_string();
        }
    }
    normalized
}

fn format_logical(namespace: &str, rel: &Path) -> String {
    let rel_str = rel.to_string_lossy().replace('\\', "/");
    let rel_clean = rel_str.trim_start_matches('/');
    if rel_clean.is_empty() {
        namespace.trim_end_matches('/').to_string()
    } else {
        format!("{}/{}", namespace.trim_end_matches('/'), rel_clean)
    }
}

/// One JSON document discovered on disk, paired with its normalized logical path.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct CorpusFile {
    pub logical_path: String,
    pub filesystem_path: PathBuf,
}

/// One exact ReplayV1 document found on disk.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ReplayContentCandidateV1 {
    /// Terminal-state binding key used by `ArenaOutcomeV1::Completed`.
    pub final_state_hash: String,
    /// SHA-256 of the exact replay document bytes; future archive address.
    pub document_sha256: String,
    /// Normalized logical source path (e.g. `benchmarks/.../replay.json`).
    pub logical_path: String,
    /// Filesystem path on the current host used for reading.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub filesystem_path: Option<PathBuf>,
}

impl ReplayContentCandidateV1 {
    pub fn new(
        final_state_hash: impl Into<String>,
        document_sha256: impl Into<String>,
        logical_path: impl Into<String>,
        filesystem_path: Option<PathBuf>,
    ) -> Self {
        Self {
            final_state_hash: final_state_hash.into(),
            document_sha256: document_sha256.into(),
            logical_path: logical_path.into(),
            filesystem_path,
        }
    }

    /// Access the normalized logical source path.
    pub fn source_path(&self) -> &str {
        &self.logical_path
    }
}

/// Deterministic, duplicate-preserving content index.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct ReplayContentIndexV1 {
    by_final_state_hash: BTreeMap<String, Vec<ReplayContentCandidateV1>>,
    documents_indexed: usize,
}

impl ReplayContentIndexV1 {
    pub fn documents_indexed(&self) -> usize {
        self.documents_indexed
    }

    pub fn distinct_final_state_hashes(&self) -> usize {
        self.by_final_state_hash.len()
    }

    /// All exact document candidates for one terminal hash, in deterministic
    /// `(document_sha256, logical_path)` order.
    pub fn candidates(&self, final_state_hash: &str) -> &[ReplayContentCandidateV1] {
        self.by_final_state_hash
            .get(final_state_hash)
            .map(Vec::as_slice)
            .unwrap_or(&[])
    }

    pub fn entries(&self) -> impl Iterator<Item = (&str, &[ReplayContentCandidateV1])> {
        self.by_final_state_hash
            .iter()
            .map(|(hash, candidates)| (hash.as_str(), candidates.as_slice()))
    }

    /// Index one document already identified as ReplayV1 by a containing scan.
    /// Kept crate-private so external callers use the bounded scanner.
    pub(crate) fn index_replay_document(
        &mut self,
        logical_path: &str,
        filesystem_path: Option<&Path>,
        bytes: &[u8],
    ) -> Result<()> {
        let replay: ReplayV1 = serde_json::from_slice(bytes).map_err(|error| {
            StudioLeagueError::Invalid(format!(
                "ReplayV1 document `{logical_path}` failed strict schema parsing: {error}"
            ))
        })?;
        if replay.format != REPLAY_FORMAT || replay.version != REPLAY_VERSION {
            return Err(StudioLeagueError::Invalid(format!(
                "ReplayV1 document `{logical_path}` has unsupported format/version `{}@{}`",
                replay.format, replay.version
            )));
        }
        let candidate = ReplayContentCandidateV1 {
            final_state_hash: replay.final_state_hash.as_str().to_string(),
            document_sha256: hex::encode(Sha256::digest(bytes)),
            logical_path: logical_path.to_string(),
            filesystem_path: filesystem_path.map(PathBuf::from),
        };
        self.by_final_state_hash
            .entry(candidate.final_state_hash.clone())
            .or_default()
            .push(candidate);
        self.documents_indexed += 1;
        Ok(())
    }

    pub(crate) fn finish(&mut self) {
        for candidates in self.by_final_state_hash.values_mut() {
            candidates.sort_by(|left, right| {
                (&left.document_sha256, &left.logical_path)
                    .cmp(&(&right.document_sha256, &right.logical_path))
            });
        }
    }
}

/// Collect JSON documents from roots and sort by portable logical path.
///
/// Fail-closed against collisions: if two distinct physical files map to the
/// same logical path, this returns an error rather than silently picking one.
/// Overlapping roots pointing to the identical physical file are safely deduplicated.
pub fn collect_corpus_files(
    roots: &[CorpusRoot],
    skip_segments: &[String],
) -> Result<Vec<CorpusFile>> {
    let mut files = Vec::new();
    for root in roots {
        collect_root_json(root, &root.path, skip_segments, &mut files)?;
    }
    files.sort_by(|left, right| left.logical_path.cmp(&right.logical_path));

    let mut deduped: Vec<CorpusFile> = Vec::with_capacity(files.len());
    for file in files {
        if let Some(last) = deduped.last() {
            if last.logical_path == file.logical_path {
                if same_physical_file(&last.filesystem_path, &file.filesystem_path) {
                    // Overlapping roots pointing to the same file: safe to deduplicate.
                    continue;
                } else {
                    return Err(StudioLeagueError::Invalid(format!(
                        "logical path collision on `{}` between distinct files `{}` and `{}`",
                        file.logical_path,
                        last.filesystem_path.display(),
                        file.filesystem_path.display()
                    )));
                }
            }
        }
        deduped.push(file);
    }
    Ok(deduped)
}

fn same_physical_file(left: &Path, right: &Path) -> bool {
    if left == right {
        return true;
    }
    match (left.canonicalize(), right.canonicalize()) {
        (Ok(l), Ok(r)) => l == r,
        _ => false,
    }
}

fn collect_root_json(
    root: &CorpusRoot,
    dir: &Path,
    skip_segments: &[String],
    out: &mut Vec<CorpusFile>,
) -> Result<()> {
    let entries = match std::fs::read_dir(dir) {
        Ok(entries) => entries,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(()),
        Err(error) => return Err(error.into()),
    };
    for entry in entries {
        let path = entry?.path();
        if is_skipped(&path, skip_segments) {
            continue;
        }
        if path.is_dir() {
            collect_root_json(root, &path, skip_segments, out)?;
        } else if path.extension().and_then(|extension| extension.to_str()) == Some("json") {
            out.push(CorpusFile {
                logical_path: root.resolve_logical_path(&path)?,
                filesystem_path: path,
            });
        }
    }
    Ok(())
}

/// Scan roots for ReplayV1 documents. Non-replay JSON is ignored, while a
/// document declaring the ReplayV1 format is authority-bearing and therefore
/// fails closed if it is oversized, unreadable, malformed, wrong-versioned, or
/// structurally invalid. Filesystem traversal order cannot affect the result.
pub fn build_replay_content_index(
    roots: &[PathBuf],
    max_document_bytes: u64,
    skip_segments: &[String],
) -> Result<ReplayContentIndexV1> {
    let corpus_roots: Vec<CorpusRoot> = roots
        .iter()
        .map(|path| CorpusRoot::from_spec(&path.to_string_lossy()))
        .collect();
    build_replay_content_index_roots(&corpus_roots, max_document_bytes, skip_segments)
}

pub fn build_replay_content_index_roots(
    roots: &[CorpusRoot],
    max_document_bytes: u64,
    skip_segments: &[String],
) -> Result<ReplayContentIndexV1> {
    let files = collect_corpus_files(roots, skip_segments)?;
    let mut index = ReplayContentIndexV1::default();
    for file in files {
        if std::fs::metadata(&file.filesystem_path)?.len() > max_document_bytes {
            continue;
        }
        let bytes = std::fs::read(&file.filesystem_path)?;
        let value: serde_json::Value = match serde_json::from_slice(&bytes) {
            Ok(value) => value,
            Err(_) => continue,
        };
        if value.get("format").and_then(|value| value.as_str()) != Some(REPLAY_FORMAT) {
            continue;
        }
        index.index_replay_document(&file.logical_path, Some(&file.filesystem_path), &bytes)?;
    }
    index.finish();
    Ok(index)
}

fn is_skipped(path: &Path, skip_segments: &[String]) -> bool {
    path.components().any(|component| {
        let text = component.as_os_str().to_string_lossy();
        skip_segments.iter().any(|skip| text.contains(skip))
    })
}
