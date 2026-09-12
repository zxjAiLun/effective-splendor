//! Participant identity: humans and engines live in one league, in two kinds.
//!
//! A human is deliberately **not** an agent: the frozen `RatedAgentV1` requires an
//! executable `command`, so pushing a display name into it would corrupt the
//! research registry. Engines keep their *exact* policy identity
//! (`agent_name@agent_version`, where the version is a version string or a
//! checkpoint hash), never a display name.
//!
//! Ids are **reproducible**. An engine id is derived from its identity key, so it
//! survives deleting the database; a human id is user-authored state and lives in
//! the durable [`crate::identity_manifest`] instead. Nothing here may depend on
//! random ids that only exist inside the derived SQLite index.

use crate::error::{Result, StudioLeagueError};
use crate::identity_manifest::IdentityManifestV1;
use rand::Rng;
use rusqlite::{params, Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

/// Identity key reserved for legacy human games whose `.meta.json` is missing.
/// Those games stay in the ledger but are never attributed to the local profile.
pub const UNASSIGNED_HUMAN_KEY: &str = "unassigned-human";

/// `league_meta` key holding the single local human participant id.
pub const LOCAL_HUMAN_META_KEY: &str = "local_human_participant_id";

/// `league_meta` key holding the SHA-256 integrity hash of the identity manifest
/// used to project this derived database.
pub const IDENTITY_MANIFEST_HASH_META_KEY: &str = "identity_manifest_hash";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ParticipantKind {
    Human,
    Engine,
}

impl ParticipantKind {
    pub fn as_str(self) -> &'static str {
        match self {
            ParticipantKind::Human => "human",
            ParticipantKind::Engine => "engine",
        }
    }

    pub fn from_db(value: &str) -> Result<Self> {
        match value {
            "human" => Ok(ParticipantKind::Human),
            "engine" => Ok(ParticipantKind::Engine),
            other => Err(StudioLeagueError::Invalid(format!(
                "unknown participant kind `{other}`"
            ))),
        }
    }
}

/// Exact engine identity as recorded in arena / evaluation artifacts.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub struct EngineIdentityV1 {
    pub agent_name: String,
    pub agent_version: String,
}

impl EngineIdentityV1 {
    pub fn new(agent_name: impl Into<String>, agent_version: impl Into<String>) -> Self {
        Self {
            agent_name: agent_name.into(),
            agent_version: agent_version.into(),
        }
    }

    /// The canonical participant key. Two engines are the same participant only
    /// when this string matches; display names are never compared.
    pub fn key(&self) -> String {
        format!("{}@{}", self.agent_name, self.agent_version)
    }
}

/// A participant id derived purely from an identity key.
///
/// Deterministic on purpose: the same corpus and the same manifest must produce
/// the same participant ids after the database is deleted and rebuilt.
pub fn derived_participant_id(identity_key: &str) -> String {
    let digest = hex::encode(Sha256::digest(
        format!("studio-league-participant-v1\n{identity_key}").as_bytes(),
    ));
    format!("eng-{}", &digest[..32])
}

/// A random, opaque, dash-formatted id, used only for the **user-authored** local
/// human identity, which is then pinned by the manifest.
pub fn new_participant_id() -> String {
    let mut bytes = [0u8; 16];
    rand::thread_rng().fill(&mut bytes);
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    let h = hex::encode(bytes);
    format!(
        "{}-{}-{}-{}-{}",
        &h[0..8],
        &h[8..12],
        &h[12..16],
        &h[16..20],
        &h[20..32]
    )
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ParticipantRow {
    pub participant_id: String,
    pub kind: ParticipantKind,
    pub display_name: String,
    pub identity_key: Option<String>,
    /// `None` until the participant's first rating event; the effective value
    /// comes from `StudioRatingConfigV1::initial_elo`.
    pub current_elo: Option<f64>,
    pub created_at: i64,
}

/// Mirrors the frozen M16 rule: fewer than 20 completed games is provisional.
pub const PROVISIONAL_MATCH_THRESHOLD: u32 = 20;

fn insert_participant(
    conn: &Connection,
    participant_id: &str,
    kind: ParticipantKind,
    display_name: &str,
    identity_key: Option<&str>,
    now: i64,
) -> Result<()> {
    conn.execute(
        "INSERT INTO participants
             (participant_id, kind, display_name, identity_key, current_elo, created_at)
         VALUES (?1, ?2, ?3, ?4, NULL, ?5)",
        params![
            participant_id,
            kind.as_str(),
            display_name,
            identity_key,
            now
        ],
    )?;
    Ok(())
}

/// Resolve an exact engine identity to its participant id, creating the row on
/// first sight.
///
/// The participant id is always derived from the **canonical** identity key: when
/// the identity is aliased, the alias target key decides the id. That makes the
/// result independent of declaration order, and independent of which of the two
/// keys the corpus happens to mention first (Commit A Repair 2, P1-1).
pub fn resolve_engine_participant(
    conn: &Connection,
    identity: &EngineIdentityV1,
    display_name: &str,
    now: i64,
) -> Result<String> {
    resolve_engine_participant_with_key(conn, &identity.key(), display_name, now)
}

/// Resolve (creating if needed) the engine participant identified by an exact
/// policy identity `key`.
///
/// `resolve_engine_participant` uses the handshake runtime identity
/// (`agent_name@agent_version`). When the arena's `match-config.json` is
/// available the league has a strictly better identity — the *policy* identity,
/// which also covers the search configuration — and passes it here instead. The
/// two paths share this one implementation so alias resolution and id derivation
/// can never diverge between them.
pub fn resolve_engine_participant_with_key(
    conn: &Connection,
    key: &str,
    display_name: &str,
    now: i64,
) -> Result<String> {
    let canonical_key = canonical_identity_key(conn, key)?;
    let participant_id = derived_participant_id(&canonical_key);
    if participant_row_exists(conn, &participant_id)? {
        return Ok(participant_id);
    }
    insert_participant(
        conn,
        &participant_id,
        ParticipantKind::Engine,
        display_name,
        Some(&canonical_key),
        now,
    )?;
    Ok(participant_id)
}

/// The identity key a raw key should be treated as, following an explicit alias.
///
/// Returns the input unchanged when no alias is declared, so callers never need a
/// separate "was it aliased?" branch.
pub fn canonical_identity_key(conn: &Connection, key: &str) -> Result<String> {
    Ok(resolve_alias(conn, key)?.unwrap_or_else(|| key.to_string()))
}

fn participant_row_exists(conn: &Connection, participant_id: &str) -> Result<bool> {
    Ok(conn
        .query_row(
            "SELECT 1 FROM participants WHERE participant_id = ?1",
            params![participant_id],
            |_| Ok(()),
        )
        .optional()?
        .is_some())
}

/// Follow an explicit alias to the canonical **identity key** it maps to.
///
/// The mapping is `alias_key -> canonical_identity_key`, never `-> participant_id`:
/// participant ids are derived, and storing one would reintroduce an authored id
/// that the durable manifest could not rebuild (Commit A Repair 2, P1-1).
pub fn resolve_alias(conn: &Connection, key: &str) -> Result<Option<String>> {
    Ok(conn
        .query_row(
            "SELECT canonical_identity_key FROM participant_aliases WHERE alias_key = ?1",
            params![key],
            |row| row.get::<_, String>(0),
        )
        .optional()?)
}

/// Declare that an identity key is the same participant as another.
///
/// Private on purpose: the durable copy of this decision belongs in the identity
/// manifest, and a database-only alias would be authored state that a rebuild
/// would silently lose. Only [`sync_identity_manifest`] writes this table.
fn declare_alias(
    conn: &Connection,
    alias_key: &str,
    canonical_identity_key: &str,
    note: &str,
) -> Result<()> {
    if alias_key == canonical_identity_key {
        return Err(StudioLeagueError::Invalid(format!(
            "alias `{alias_key}` points at itself; an alias must name a different identity key"
        )));
    }
    conn.execute(
        "INSERT OR REPLACE INTO participant_aliases (alias_key, canonical_identity_key, note)
         VALUES (?1, ?2, ?3)",
        params![alias_key, canonical_identity_key, note],
    )?;
    Ok(())
}

/// The reserved pseudo-participant for human games with no recorded seat
/// metadata. Those games stay in the ledger but are never attributed to the local
/// profile (boundary 5). Its id is derived, so it rebuilds identically.
pub fn unassigned_human_participant(conn: &Connection, now: i64) -> Result<String> {
    let identity_key = EngineIdentityV1::new(UNASSIGNED_HUMAN_KEY, "1").key();
    let participant_id = derived_participant_id(&identity_key);
    if participant_row_exists(conn, &participant_id)? {
        return Ok(participant_id);
    }
    insert_participant(
        conn,
        &participant_id,
        ParticipantKind::Human,
        "Unassigned human (no seat metadata)",
        Some(&identity_key),
        now,
    )?;
    Ok(participant_id)
}

/// The local human profile id, if one has been created.
pub fn local_human_participant(conn: &Connection) -> Result<Option<String>> {
    Ok(conn
        .query_row(
            "SELECT value FROM league_meta WHERE key = ?1",
            params![LOCAL_HUMAN_META_KEY],
            |row| row.get::<_, String>(0),
        )
        .optional()?)
}

/// The identity manifest hash recorded as DB integrity evidence, if one exists.
pub fn stored_identity_manifest_hash(conn: &Connection) -> Result<Option<String>> {
    Ok(conn
        .query_row(
            "SELECT value FROM league_meta WHERE key = ?1",
            params![IDENTITY_MANIFEST_HASH_META_KEY],
            |row| row.get::<_, String>(0),
        )
        .optional()?)
}

/// Create the local human profile with an id supplied by the manifest.
///
/// The id is a parameter precisely so it comes from durable user-authored state
/// rather than from this database.
pub(crate) fn ensure_local_human(
    conn: &Connection,
    participant_id: &str,
    display_name: &str,
    now: i64,
) -> Result<String> {
    if let Some(existing) = local_human_participant(conn)? {
        return Ok(existing);
    }
    insert_participant(
        conn,
        participant_id,
        ParticipantKind::Human,
        display_name,
        None,
        now,
    )?;
    conn.execute(
        "INSERT OR REPLACE INTO league_meta (key, value) VALUES (?1, ?2)",
        params![LOCAL_HUMAN_META_KEY, participant_id],
    )?;
    Ok(participant_id.to_string())
}

/// Project the durable manifest into the derived index: the local human identity
/// and every explicit alias. Idempotent, and safe to call before any ingest.
///
/// Authority invariant: if the ledger already contains historical matches,
/// an altered manifest hash is rejected. Alias or identity projection cannot
/// be mutated under existing matches without rebuilding the derived index.
pub fn sync_identity_manifest(
    conn: &Connection,
    manifest: &IdentityManifestV1,
    now: i64,
) -> Result<()> {
    manifest.validate()?;
    let manifest_hash = manifest.hash()?;

    let match_count: i64 = conn
        .query_row("SELECT COUNT(*) FROM matches", [], |row| row.get(0))
        .unwrap_or(0);
    if match_count > 0 {
        match stored_identity_manifest_hash(conn)? {
            Some(stored) if stored == manifest_hash => {}
            Some(stored) => {
                return Err(StudioLeagueError::Invalid(format!(
                    "identity manifest hash `{manifest_hash}` disagrees with stored database evidence `{stored}` on a non-empty ledger; rebuild the derived database to apply identity or alias changes"
                )));
            }
            None => {
                return Err(StudioLeagueError::Invalid(
                    "database is non-empty but has no identity manifest hash integrity evidence; rebuild the derived database".to_string(),
                ));
            }
        }
    }

    if let Some(local) = &manifest.local_human {
        match local_human_participant(conn)? {
            Some(existing) if existing == local.participant_id => {
                // Keep the manifest's display name authoritative; renames are
                // authored there, not in the derived index.
                conn.execute(
                    "UPDATE participants SET display_name = ?1 WHERE participant_id = ?2",
                    params![local.display_name, local.participant_id],
                )?;
            }
            Some(existing) => {
                return Err(StudioLeagueError::Invalid(format!(
                    "the index's local human `{existing}` disagrees with the manifest's `{}`; the index is derived, so rebuild it instead of editing it",
                    local.participant_id
                )));
            }
            None => {
                ensure_local_human(conn, &local.participant_id, &local.display_name, now)?;
            }
        }
    }
    for alias in &manifest.aliases {
        declare_alias(
            conn,
            &alias.alias_key,
            &alias.canonical_identity_key,
            &alias.note,
        )?;
    }
    conn.execute(
        "INSERT OR REPLACE INTO league_meta (key, value) VALUES (?1, ?2)",
        params![IDENTITY_MANIFEST_HASH_META_KEY, manifest_hash],
    )?;
    Ok(())
}

pub fn participant(conn: &Connection, participant_id: &str) -> Result<Option<ParticipantRow>> {
    let row = conn
        .query_row(
            "SELECT participant_id, kind, display_name, identity_key, current_elo, created_at
               FROM participants WHERE participant_id = ?1",
            params![participant_id],
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                    row.get::<_, Option<String>>(3)?,
                    row.get::<_, Option<f64>>(4)?,
                    row.get::<_, i64>(5)?,
                ))
            },
        )
        .optional()?;
    let Some((id, kind, name, key, elo, created)) = row else {
        return Ok(None);
    };
    Ok(Some(ParticipantRow {
        participant_id: id,
        kind: ParticipantKind::from_db(&kind)?,
        display_name: name,
        identity_key: key,
        current_elo: elo,
        created_at: created,
    }))
}
