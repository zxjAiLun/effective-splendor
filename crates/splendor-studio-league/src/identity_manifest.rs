//! The durable, user-authored identity manifest.
//!
//! The SQLite index is derived state and must be deletable. Everything the league
//! *cannot* re-derive from the corpus therefore lives here instead:
//!
//! * the local human participant id and display name (a human has no identity the
//!   corpus could reproduce);
//! * explicit identity aliases: a deliberate editorial act, not an artifact.
//!
//! Engine participants are deliberately **not** listed: their ids are derived
//! deterministically from their exact identity key
//! ([`crate::participant::derived_participant_id`]), so they rebuild for free.
//!
//! P1 of the Commit A review: without this file, deleting the database changed
//! every participant id and silently discarded renames and aliases.
//!
//! Commit A Repair 2 changed an alias from `alias_key -> participant_id` to
//! `alias_key -> canonical_identity_key`. Storing a participant id made the
//! manifest the author of an id that is otherwise derived, and left an
//! "alias target not created yet" ambiguity; storing the canonical identity key
//! removes both. That is a format change, so the version moved 1 -> 2.

use crate::error::{Result, StudioLeagueError};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::io::Write;
use std::path::{Path, PathBuf};

pub const IDENTITY_MANIFEST_FORMAT: &str = "effective-splendor-studio-league-identity";
/// v2 stores `canonical_identity_key` in an alias instead of `participant_id`.
pub const IDENTITY_MANIFEST_VERSION: u32 = 2;
/// Default location of the manifest, beside the derived database.
pub const DEFAULT_IDENTITY_MANIFEST_PATH: &str = "local-artifacts/studio-league/identity.json";

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LocalHumanIdentityV1 {
    pub participant_id: String,
    pub display_name: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AliasEntryV1 {
    /// The identity key the corpus records.
    pub alias_key: String,
    /// The identity key `alias_key` must be treated as. Participant ids are
    /// derived from this, so the alias never stores one.
    pub canonical_identity_key: String,
    #[serde(default)]
    pub note: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct IdentityManifestV1 {
    pub format: String,
    pub version: u32,
    pub local_human: Option<LocalHumanIdentityV1>,
    #[serde(default)]
    pub aliases: Vec<AliasEntryV1>,
}

impl Default for IdentityManifestV1 {
    fn default() -> Self {
        Self {
            format: IDENTITY_MANIFEST_FORMAT.to_string(),
            version: IDENTITY_MANIFEST_VERSION,
            local_human: None,
            aliases: Vec::new(),
        }
    }
}

/// `<path>.tmp` — the staging copy, fully written and synced before any replace.
pub fn temp_path(path: &Path) -> PathBuf {
    sibling_with_suffix(path, "tmp")
}

/// `<path>.bak` — the previous contents, kept so a lost primary is recoverable.
pub fn backup_path(path: &Path) -> PathBuf {
    sibling_with_suffix(path, "bak")
}

fn sibling_with_suffix(path: &Path, suffix: &str) -> PathBuf {
    let mut name = path
        .file_name()
        .map(|name| name.to_os_string())
        .unwrap_or_default();
    name.push(".");
    name.push(suffix);
    path.with_file_name(name)
}

impl IdentityManifestV1 {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn validate(&self) -> Result<()> {
        if self.format != IDENTITY_MANIFEST_FORMAT {
            return Err(StudioLeagueError::Invalid(format!(
                "identity manifest format `{}` is not `{IDENTITY_MANIFEST_FORMAT}`",
                self.format
            )));
        }
        if self.version != IDENTITY_MANIFEST_VERSION {
            return Err(StudioLeagueError::Invalid(format!(
                "identity manifest version {} is not {IDENTITY_MANIFEST_VERSION}; v1 stored alias participant ids, which are derived, so re-author the manifest (the index is derived and rebuilds)",
                self.version
            )));
        }
        if let Some(local) = &self.local_human {
            if local.participant_id.trim().is_empty() {
                return Err(StudioLeagueError::Invalid(
                    "the local human participant id must not be empty".to_string(),
                ));
            }
            if local.display_name.trim().is_empty() {
                return Err(StudioLeagueError::Invalid(
                    "the local human display name must not be empty".to_string(),
                ));
            }
        }
        let mut seen = std::collections::BTreeSet::new();
        for alias in &self.aliases {
            if alias.alias_key.trim().is_empty() {
                return Err(StudioLeagueError::Invalid(
                    "an alias key must not be empty".to_string(),
                ));
            }
            if alias.canonical_identity_key.trim().is_empty() {
                return Err(StudioLeagueError::Invalid(format!(
                    "alias `{}` must name the canonical identity key it maps to",
                    alias.alias_key
                )));
            }
            if alias.alias_key == alias.canonical_identity_key {
                return Err(StudioLeagueError::Invalid(format!(
                    "alias `{}` points at itself; an alias must name a different identity key",
                    alias.alias_key
                )));
            }
            if !seen.insert(alias.alias_key.as_str()) {
                return Err(StudioLeagueError::Invalid(format!(
                    "alias `{}` is declared twice",
                    alias.alias_key
                )));
            }
        }
        Ok(())
    }

    /// Canonical hash, so a rebuild can prove it used the same identities.
    pub fn hash(&self) -> Result<String> {
        self.validate()?;
        let canonical = serde_json::to_string(self)?;
        Ok(hex::encode(Sha256::digest(canonical.as_bytes())))
    }

    /// Strict read: a missing file is `None`, a present-but-unusable file is an
    /// error. Use [`Self::load_or_recover`] when a lost primary should be
    /// recovered from its staging/backup sibling.
    pub fn load(path: &Path) -> Result<Option<Self>> {
        if !path.is_file() {
            return Ok(None);
        }
        let text = std::fs::read_to_string(path)?;
        let manifest: Self = serde_json::from_str(&text)?;
        manifest.validate()?;
        Ok(Some(manifest))
    }

    /// Load, recovering from `<path>.tmp` or `<path>.bak` when the primary is
    /// missing or unusable, then heal the primary.
    ///
    /// Windows cannot rename over an existing file, so [`Self::save`] has to
    /// remove before it renames; a crash inside that window would otherwise
    /// destroy the only user-authored identity authority. Recovery prefers the
    /// newer synced `.tmp`, then the previous ` `.bak` (Commit A Repair 2, P2).
    pub fn load_or_recover(path: &Path) -> Result<Option<Self>> {
        if let Ok(Some(manifest)) = Self::load(path) {
            return Ok(Some(manifest));
        }
        for candidate in [temp_path(path), backup_path(path)] {
            if !candidate.is_file() {
                continue;
            }
            let text = std::fs::read_to_string(&candidate)?;
            let recovered: Self = match serde_json::from_str(&text) {
                Ok(value) => value,
                Err(_) => continue,
            };
            if recovered.validate().is_err() {
                continue;
            }
            // Heal the primary so the next load is a plain read.
            recovered.save(path)?;
            return Ok(Some(recovered));
        }
        Ok(None)
    }

    /// Load the manifest, recovering from a staging/backup sibling and creating
    /// one on first use.
    ///
    /// The local human id is generated exactly once and then owned by this file;
    /// renaming edits `display_name` and never the id.
    pub fn load_or_create(path: &Path, display_name: &str) -> Result<Self> {
        if let Some(manifest) = Self::load_or_recover(path)? {
            return Ok(manifest);
        }
        let mut manifest = Self::new();
        manifest.ensure_local_human(display_name);
        manifest.save(path)?;
        Ok(manifest)
    }

    /// Persist the manifest, keeping a synced `.tmp` and the previous `.bak`.
    pub fn save(&self, path: &Path) -> Result<()> {
        self.validate()?;
        if let Some(parent) = path.parent() {
            if !parent.as_os_str().is_empty() {
                std::fs::create_dir_all(parent)?;
            }
        }
        let text = serde_json::to_string_pretty(self)?;
        let temp = temp_path(path);
        {
            // Write and flush the staging copy *before* touching the primary, so
            // an interruption can never leave the primary removed with no
            // complete replacement on disk.
            let mut file = std::fs::File::create(&temp)?;
            file.write_all(text.as_bytes())?;
            file.sync_all()?;
        }
        if path.is_file() {
            // Best effort: `.tmp` above is already a complete recovery source.
            let _ = std::fs::copy(path, backup_path(path));
        }
        if path.exists() {
            std::fs::remove_file(path)?;
        }
        std::fs::rename(&temp, path)?;
        Ok(())
    }

    /// The local human identity, creating it if the manifest has none yet.
    pub fn ensure_local_human(&mut self, display_name: &str) -> &LocalHumanIdentityV1 {
        if self.local_human.is_none() {
            self.local_human = Some(LocalHumanIdentityV1 {
                participant_id: crate::participant::new_participant_id(),
                display_name: display_name.to_string(),
            });
        }
        self.local_human.as_ref().expect("just ensured")
    }

    /// Record a rename without changing the id, which is what makes the identity
    /// durable across a rebuild.
    ///
    /// This is the **only** rename path: the derived index must not be edited
    /// directly, or the rename would vanish on the next rebuild.
    pub fn rename_local_human(&mut self, display_name: &str) -> Result<()> {
        let local = self
            .local_human
            .as_mut()
            .ok_or_else(|| StudioLeagueError::Missing("local human identity".to_string()))?;
        local.display_name = display_name.to_string();
        Ok(())
    }

    pub fn declare_alias(&mut self, alias_key: &str, canonical_identity_key: &str, note: &str) {
        if let Some(existing) = self
            .aliases
            .iter_mut()
            .find(|alias| alias.alias_key == alias_key)
        {
            existing.canonical_identity_key = canonical_identity_key.to_string();
            existing.note = note.to_string();
            return;
        }
        self.aliases.push(AliasEntryV1 {
            alias_key: alias_key.to_string(),
            canonical_identity_key: canonical_identity_key.to_string(),
            note: note.to_string(),
        });
    }

    /// The canonical identity key an alias maps to, if it is declared.
    pub fn alias_target_identity_key(&self, alias_key: &str) -> Option<&str> {
        self.aliases
            .iter()
            .find(|alias| alias.alias_key == alias_key)
            .map(|alias| alias.canonical_identity_key.as_str())
    }
}
