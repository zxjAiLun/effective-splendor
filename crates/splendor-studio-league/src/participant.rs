//! Participant identity: humans and engines live in one league, in two kinds.
//!
//! A human is deliberately **not** an agent: the frozen `RatedAgentV1` requires an
//! executable `command`, so pushing a display name into it would corrupt the
//! research registry. Engines keep their *exact* policy identity
//! (`agent_name@agent_version`, where the version is a version string or a
//! checkpoint hash), never a display name.

use crate::error::{Result, StudioLeagueError};
use rand::Rng;
use rusqlite::{params, Connection, OptionalExtension};
use serde::{Deserialize, Serialize};

/// Identity key reserved for legacy human games whose `.meta.json` is missing.
/// Those games stay in the ledger but are never attributed to the local profile.
pub const UNASSIGNED_HUMAN_KEY: &str = "unassigned-human";

/// `league_meta` key holding the single local human participant id.
pub const LOCAL_HUMAN_META_KEY: &str = "local_human_participant_id";

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

impl ParticipantRow {
    pub fn is_provisional(&self, completed: u32) -> bool {
        completed < PROVISIONAL_MATCH_THRESHOLD
    }
}

/// Mirrors the frozen M16 rule: fewer than 20 completed games is provisional.
pub const PROVISIONAL_MATCH_THRESHOLD: u32 = 20;

/// A random, opaque, dash-formatted participant id. Not derived from the display
/// name, so renaming a participant never changes its identity.
pub fn new_participant_id() -> String {
    let mut bytes = [0u8; 16];
    rand::thread_rng().fill(&mut bytes);
    // RFC 4122 version 4 / variant bits, so the id is recognisably a UUID.
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

fn insert_participant(
    conn: &Connection,
    kind: ParticipantKind,
    display_name: &str,
    identity_key: Option<&str>,
    now: i64,
) -> Result<String> {
    let participant_id = new_participant_id();
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
    Ok(participant_id)
}

/// Resolve an exact engine identity to a participant id, creating the row on
/// first sight. Never merges by display name: the identity key is the only key,
/// and an explicitly declared alias always wins over a same-shaped key.
pub fn resolve_engine_participant(
    conn: &Connection,
    identity: &EngineIdentityV1,
    display_name: &str,
    now: i64,
) -> Result<String> {
    let key = identity.key();
    if let Some(canonical) = resolve_alias(conn, &key)? {
        return Ok(canonical);
    }
    if let Some(existing) = conn
        .query_row(
            "SELECT participant_id FROM participants WHERE identity_key = ?1",
            params![key],
            |row| row.get::<_, String>(0),
        )
        .optional()?
    {
        return Ok(existing);
    }
    insert_participant(conn, ParticipantKind::Engine, display_name, Some(&key), now)
}

/// Follow an explicit alias to its canonical participant, if one was declared.
pub fn resolve_alias(conn: &Connection, key: &str) -> Result<Option<String>> {
    Ok(conn
        .query_row(
            "SELECT participant_id FROM participant_aliases WHERE alias_key = ?1",
            params![key],
            |row| row.get::<_, String>(0),
        )
        .optional()?)
}

/// Declare that an identity key belonging to an engine is the same participant as
/// an existing one. Merging is only ever this explicit act.
pub fn declare_alias(
    conn: &Connection,
    alias_key: &str,
    participant_id: &str,
    note: &str,
) -> Result<()> {
    conn.execute(
        "INSERT OR REPLACE INTO participant_aliases (alias_key, participant_id, note)
         VALUES (?1, ?2, ?3)",
        params![alias_key, participant_id, note],
    )?;
    Ok(())
}

/// The reserved pseudo-participant for human games with no recorded seat
/// metadata. Those games stay in the ledger but are never attributed to the
/// local profile (boundary 5).
pub fn unassigned_human_participant(conn: &Connection, now: i64) -> Result<String> {
    let identity = EngineIdentityV1::new(UNASSIGNED_HUMAN_KEY, "1");
    let existing: Option<String> = conn
        .query_row(
            "SELECT participant_id FROM participants WHERE identity_key = ?1",
            params![identity.key()],
            |row| row.get(0),
        )
        .optional()?;
    match existing {
        Some(id) => Ok(id),
        None => insert_participant(
            conn,
            ParticipantKind::Human,
            "Unassigned human (no seat metadata)",
            Some(&identity.key()),
            now,
        ),
    }
}

/// The local human profile id, if one has been created.
pub fn local_human_participant(conn: &Connection) -> Result<Option<String>> {
    let meta = conn
        .query_row(
            "SELECT value FROM league_meta WHERE key = ?1",
            params![LOCAL_HUMAN_META_KEY],
            |row| row.get::<_, String>(0),
        )
        .optional()?;
    Ok(meta)
}

/// Create the local human profile exactly once. Renaming later keeps the id.
pub fn ensure_local_human(conn: &Connection, display_name: &str, now: i64) -> Result<String> {
    if let Some(id) = local_human_participant(conn)? {
        return Ok(id);
    }
    let id = insert_participant(conn, ParticipantKind::Human, display_name, None, now)?;
    conn.execute(
        "INSERT OR REPLACE INTO league_meta (key, value) VALUES (?1, ?2)",
        params![LOCAL_HUMAN_META_KEY, id],
    )?;
    Ok(id)
}

pub fn rename_participant(
    conn: &Connection,
    participant_id: &str,
    display_name: &str,
) -> Result<()> {
    let changed = conn.execute(
        "UPDATE participants SET display_name = ?1 WHERE participant_id = ?2",
        params![display_name, participant_id],
    )?;
    if changed == 0 {
        return Err(StudioLeagueError::Missing(format!(
            "participant `{participant_id}`"
        )));
    }
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
