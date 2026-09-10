//! The durable, user-authored identity manifest.
//!
//! The SQLite index is derived state and must be deletable. Everything the league
//! *cannot* re-derive from the corpus therefore lives here instead:
//!
//! * the local human participant id and display name (a human has no identity the
//!   corpus could reproduce);
//! * explicit `participant_aliases` (a deliberate editorial act, not an artifact);
//!
//! Engine participants are deliberately **not** listed: their ids are derived
//! deterministically from their exact identity key
//! ([`crate::participant::derived_participant_id`]), so they rebuild for free.
//!
//! P1 of the Commit A review: without this file, deleting the database changed
//! every participant id and silently discarded renames and aliases.

use crate::error::{Result, StudioLeagueError};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::path::Path;

pub const IDENTITY_MANIFEST_FORMAT: &str = "effective-splendor-studio-league-identity";
pub const IDENTITY_MANIFEST_VERSION: u32 = 1;
/// Default location of the manifest, beside the derived database.
pub const DEFAULT_IDENTITY_MANIFEST_PATH: &str = "local-artifacts/studio-league/identity.json";

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LocalHumanIdentityV1 {
    pub participant_id: String,
    pub display_name: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AliasEntryV1 {
    pub alias_key: String,
    pub participant_id: String,
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
                "identity manifest version {} is not {IDENTITY_MANIFEST_VERSION}",
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

    pub fn load(path: &Path) -> Result<Option<Self>> {
        if !path.is_file() {
            return Ok(None);
        }
        let text = std::fs::read_to_string(path)?;
        let manifest: Self = serde_json::from_str(&text)?;
        manifest.validate()?;
        Ok(Some(manifest))
    }

    /// Load the manifest, creating and persisting one on first use.
    ///
    /// The local human id is generated exactly once and then owned by this file;
    /// renaming edits `display_name` and never the id.
    pub fn load_or_create(path: &Path, display_name: &str) -> Result<Self> {
        if let Some(manifest) = Self::load(path)? {
            return Ok(manifest);
        }
        let mut manifest = Self::new();
        manifest.ensure_local_human(display_name);
        manifest.save(path)?;
        Ok(manifest)
    }

    pub fn save(&self, path: &Path) -> Result<()> {
        self.validate()?;
        if let Some(parent) = path.parent() {
            if !parent.as_os_str().is_empty() {
                std::fs::create_dir_all(parent)?;
            }
        }
        let text = serde_json::to_string_pretty(self)?;
        // Write-then-rename so a crash cannot leave a half-written manifest.
        let temp = path.with_extension("json.tmp");
        std::fs::write(&temp, text)?;
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
    pub fn rename_local_human(&mut self, display_name: &str) -> Result<()> {
        let local = self
            .local_human
            .as_mut()
            .ok_or_else(|| StudioLeagueError::Missing("local human identity".to_string()))?;
        local.display_name = display_name.to_string();
        Ok(())
    }

    pub fn declare_alias(&mut self, alias_key: &str, participant_id: &str, note: &str) {
        if let Some(existing) = self
            .aliases
            .iter_mut()
            .find(|alias| alias.alias_key == alias_key)
        {
            existing.participant_id = participant_id.to_string();
            existing.note = note.to_string();
            return;
        }
        self.aliases.push(AliasEntryV1 {
            alias_key: alias_key.to_string(),
            participant_id: participant_id.to_string(),
            note: note.to_string(),
        });
    }

    pub fn alias_target(&self, alias_key: &str) -> Option<&str> {
        self.aliases
            .iter()
            .find(|alias| alias.alias_key == alias_key)
            .map(|alias| alias.participant_id.as_str())
    }
}
