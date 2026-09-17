//! Human Live League integration, Slice A: the durable human occurrence and the
//! canonical record a human-play completion produces.
//!
//! A human game is **not** an arena match. It has no arena report and no arena
//! `match-config.json`, and this module never fabricates either. What it has is a
//! verified `ReplayV1` plus a durable envelope that attests which seat was the
//! local human, which registered agent occupied the other seat, and exactly which
//! policy that agent ran.
//!
//! `ReplayV1` proves what happened on the board; the envelope proves **who** the
//! seats were. ReplayV1 alone carries only `P0`/`P1`, so it can never attribute a
//! seat to the local human — that is the whole reason this document exists.
//!
//! ## What is proven here, and what is not
//!
//! *Verified at completion time* (from the durable bytes alone): the envelope
//! format, the replay SHA, strict replay verification, player count, seed, seat
//! range, terminal result, the local human participant id, the identity manifest
//! hash, and the opponent's re-resolved policy key.
//!
//! *Attested, not re-proven*: that `runtime_name`/`runtime_version` came from a
//! **successful handshake**. There is no handshake transcript on disk, and the
//! completion outlet deliberately does not re-read the registry or re-handshake.
//! The trusted local Host producer asserts this on the envelope, exactly as the
//! arena path trusts its own producer. Stating this plainly matters: "came from a
//! handshake" is a producer-time invariant, not a completion-time check.

use crate::agent_configuration::{resolve_policy_identity, SeatConfigurationIdentityV1};
use crate::error::{Result, StudioLeagueError};
use crate::match_record::{
    is_lowercase_hex64, MatchStatus, ReplayBindingV1, ReplayStorage, ReplayVerification,
    SeatPolicyIdentityV1, StudioMatchRecordV1, StudioMatchSeatV1,
};
use crate::participant::EngineIdentityV1;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

/// Format tag of the durable human runtime occurrence envelope.
pub const HUMAN_RUNTIME_OCCURRENCE_FORMAT: &str = "effective-splendor-human-runtime-occurrence";
/// Version of the durable human runtime occurrence envelope.
pub const HUMAN_RUNTIME_OCCURRENCE_VERSION: u32 = 1;

/// The ledger source kind of a human-play occurrence. `source_identity` is
/// `runtime:<occurrence_id>`, so the human path keeps the same live-occurrence
/// canonical-tail constraint the arena path uses.
pub const HUMAN_PLAY_SOURCE_KIND: &str = "human_play";

/// Domain separator for [`human_runtime_occurrence_evidence_hash`], so a human
/// occurrence evidence hash can never be mistaken for a plain document SHA-256
/// or for an arena occurrence evidence hash.
const HUMAN_RUNTIME_OCCURRENCE_EVIDENCE_DOMAIN: &[u8] =
    b"effective-splendor-human-runtime-occurrence-evidence-v1";

/// The local human's identity evidence, captured from the identity manifest when
/// the game started. Never supplied by a browser and never read from the ledger.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct HumanOccurrenceHumanV1 {
    pub participant_id: String,
    pub display_name: String,
    /// The identity manifest hash this identity was authored under. Re-checked
    /// against the league at completion, so a manifest change since the game
    /// started is a conflict, not a silent re-attribution.
    pub identity_manifest_hash: String,
}

/// The registered opponent, frozen when the game started: the registry entry
/// that passed the handshake, and the policy key the shared resolver produced.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct HumanOccurrenceOpponentV1 {
    pub registry_id: String,
    pub agent_id: String,
    pub display_name: String,
    /// Verified by the handshake when the game started (producer-time invariant).
    pub runtime_name: String,
    pub runtime_version: String,
    /// The selected registry command, snapshotted.
    pub program: String,
    pub args: Vec<String>,
    /// The shared resolver's result at game start. Re-resolved from
    /// `program`/`args` at completion and required to match.
    pub policy_key: String,
}

/// The durable evidence that one human-play game happened, and who played it.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct HumanRuntimeOccurrenceV1 {
    pub format: String,
    pub version: u32,
    /// Identity, not content: `occurrence_id == session_id`.
    pub occurrence_id: String,
    /// Unix seconds at match completion; becomes `played_at` and therefore the
    /// canonical Elo-ordering evidence.
    pub completed_at: i64,
    pub seed: u64,
    pub human_seat: u8,
    /// SHA-256 of the exact replay document this occurrence produced.
    pub replay_sha256: String,
    pub human: HumanOccurrenceHumanV1,
    pub opponent: HumanOccurrenceOpponentV1,
}

/// The stable hash of a human occurrence's **complete** durable evidence.
///
/// This is `source_document_hash` (see [`StudioMatchRecordV1::source_document_hash`]):
/// idempotency compares it, so the same occurrence id carrying changed evidence
/// — replay, timestamp, opponent command, human identity — is a conflict rather
/// than a silent `AlreadyPresent`. The replay SHA alone cannot serve: it would
/// swallow a changed `completed_at` or a changed seat attribution.
///
/// Every field is hashed in a fixed order and length-prefixed, and `format` and
/// `version` are covered, so a future envelope format cannot reproduce an
/// earlier format's evidence hash, and shifting bytes between fields cannot
/// collide.
pub fn human_runtime_occurrence_evidence_hash(occurrence: &HumanRuntimeOccurrenceV1) -> String {
    let version = occurrence.version.to_string();
    let completed_at = occurrence.completed_at.to_string();
    let seed = occurrence.seed.to_string();
    let human_seat = occurrence.human_seat.to_string();
    let mut fields: Vec<&str> = vec![
        occurrence.format.as_str(),
        version.as_str(),
        occurrence.occurrence_id.as_str(),
        completed_at.as_str(),
        seed.as_str(),
        human_seat.as_str(),
        occurrence.replay_sha256.as_str(),
        occurrence.human.participant_id.as_str(),
        occurrence.human.display_name.as_str(),
        occurrence.human.identity_manifest_hash.as_str(),
        occurrence.opponent.registry_id.as_str(),
        occurrence.opponent.agent_id.as_str(),
        occurrence.opponent.display_name.as_str(),
        occurrence.opponent.runtime_name.as_str(),
        occurrence.opponent.runtime_version.as_str(),
        occurrence.opponent.program.as_str(),
        occurrence.opponent.policy_key.as_str(),
    ];
    let arg_count = occurrence.opponent.args.len().to_string();
    fields.push(arg_count.as_str());
    let mut hasher = Sha256::new();
    hasher.update(HUMAN_RUNTIME_OCCURRENCE_EVIDENCE_DOMAIN);
    hasher.update([0u8]);
    for field in fields {
        hasher.update((field.len() as u64).to_be_bytes());
        hasher.update(field.as_bytes());
    }
    for arg in &occurrence.opponent.args {
        hasher.update((arg.len() as u64).to_be_bytes());
        hasher.update(arg.as_bytes());
    }
    hex::encode(hasher.finalize())
}

/// Parse a human runtime occurrence envelope.
///
/// `Ok(None)` when the document is not a human occurrence (a different or absent
/// format) so callers can keep scanning; `Err` when it claims to be one but is
/// malformed. Structural validation only: agreement with a replay, a league, and
/// a registry command is decided by [`human_runtime_match_record`].
pub fn parse_human_runtime_occurrence(bytes: &[u8]) -> Result<Option<HumanRuntimeOccurrenceV1>> {
    let value: serde_json::Value = match serde_json::from_slice(bytes) {
        Ok(value) => value,
        Err(_) => return Ok(None),
    };
    match value.get("format").and_then(|v| v.as_str()) {
        Some(HUMAN_RUNTIME_OCCURRENCE_FORMAT) => {}
        _ => return Ok(None),
    }
    let occurrence: HumanRuntimeOccurrenceV1 = serde_json::from_value(value).map_err(|error| {
        StudioLeagueError::Invalid(format!(
            "human runtime occurrence envelope is malformed: {error}"
        ))
    })?;
    if occurrence.version != HUMAN_RUNTIME_OCCURRENCE_VERSION {
        return Err(StudioLeagueError::Invalid(format!(
            "human runtime occurrence envelope version {} is not supported (expected {HUMAN_RUNTIME_OCCURRENCE_VERSION})",
            occurrence.version
        )));
    }
    if occurrence.occurrence_id.trim().is_empty()
        || occurrence.occurrence_id.chars().any(|c| c.is_control())
    {
        return Err(StudioLeagueError::Invalid(
            "human runtime occurrence envelope carries an empty or control-character occurrence_id"
                .to_string(),
        ));
    }
    if occurrence.completed_at < 0 {
        return Err(StudioLeagueError::Invalid(format!(
            "human runtime occurrence `{}` carries a negative completed_at",
            occurrence.occurrence_id
        )));
    }
    if occurrence.human_seat > 1 {
        return Err(StudioLeagueError::Invalid(format!(
            "human runtime occurrence `{}` carries human_seat {} for a two-player game",
            occurrence.occurrence_id, occurrence.human_seat
        )));
    }
    if !is_lowercase_hex64(&occurrence.replay_sha256) {
        return Err(StudioLeagueError::Invalid(format!(
            "human runtime occurrence `{}` carries an invalid replay_sha256",
            occurrence.occurrence_id
        )));
    }
    if !is_lowercase_hex64(&occurrence.human.identity_manifest_hash) {
        return Err(StudioLeagueError::Invalid(format!(
            "human runtime occurrence `{}` carries an invalid identity_manifest_hash",
            occurrence.occurrence_id
        )));
    }
    if occurrence.human.participant_id.trim().is_empty() {
        return Err(StudioLeagueError::Invalid(
            "human runtime occurrence carries an empty human participant_id".to_string(),
        ));
    }
    // Non-empty is the only completion-time check available on the handshake
    // evidence; *that* it came from a successful handshake is a producer-time
    // invariant this module cannot and does not re-prove.
    if occurrence.opponent.runtime_name.trim().is_empty()
        || occurrence.opponent.runtime_version.trim().is_empty()
    {
        return Err(StudioLeagueError::Invalid(format!(
            "human runtime occurrence `{}` carries an empty opponent runtime identity",
            occurrence.occurrence_id
        )));
    }
    if occurrence.opponent.agent_id.trim().is_empty() {
        return Err(StudioLeagueError::Invalid(
            "human runtime occurrence carries an empty opponent agent_id".to_string(),
        ));
    }
    if occurrence.opponent.policy_key.trim().is_empty() {
        return Err(StudioLeagueError::Invalid(
            "human runtime occurrence carries an empty opponent policy_key".to_string(),
        ));
    }
    Ok(Some(occurrence))
}

/// The league-derived facts a human completion must be checked against.
///
/// Supplied by the completion outlet, which owns the league connection — this
/// module never sees a `rusqlite::Connection`.
pub(crate) struct HumanCompletionContextV1<'a> {
    /// The league's local human participant id (`local_human_participant`).
    pub local_human_participant_id: Option<&'a str>,
    /// The league's stored identity manifest hash.
    pub stored_identity_manifest_hash: Option<&'a str>,
}

/// Build the canonical ledger record for one human-play occurrence.
///
/// Every check here is answerable from the durable bytes plus the league's own
/// identity evidence; anything that requires the registry or a live agent
/// process is deliberately absent (see the module documentation).
///
/// The two seats are shaped differently on purpose:
/// * the **human** seat carries an explicit `participant_id` and **no**
///   `identity` — the ledger prefers the explicit id, and a human has no engine
///   identity to invent;
/// * the **engine** seat carries the handshake runtime identity and a resolved
///   policy key — resolved exactly as the arena path resolves it, through the
///   one shared resolver.
pub(crate) fn human_runtime_match_record(
    occurrence: &HumanRuntimeOccurrenceV1,
    replay_bytes: &[u8],
    context: &HumanCompletionContextV1<'_>,
    replay_source_path: &str,
) -> Result<StudioMatchRecordV1> {
    // 1. The envelope's own structural rules (also enforced on parse, repeated
    //    here so this function is safe for any caller-held value).
    let parsed =
        parse_human_runtime_occurrence(&serde_json::to_vec(occurrence).map_err(|error| {
            StudioLeagueError::Invalid(format!(
                "human runtime occurrence is not serializable: {error}"
            ))
        })?)?
        .ok_or_else(|| {
            StudioLeagueError::Invalid(
                "human runtime occurrence is not a human occurrence document".to_string(),
            )
        })?;
    debug_assert_eq!(&parsed, occurrence);

    // 2. The replay is exactly the bytes the envelope attests to.
    let replay_sha = hex::encode(Sha256::digest(replay_bytes));
    if replay_sha != occurrence.replay_sha256 {
        return Err(StudioLeagueError::Invalid(format!(
            "human occurrence `{}` envelopes replay sha `{}`, but the provided replay document is `{replay_sha}`",
            occurrence.occurrence_id, occurrence.replay_sha256
        )));
    }

    // 3. Strict schema parse and full replay verification.
    let replay: splendor_replay::ReplayV1 =
        serde_json::from_slice(replay_bytes).map_err(|error| {
            StudioLeagueError::Invalid(format!(
                "human occurrence replay failed strict schema parsing: {error}"
            ))
        })?;
    let verified = splendor_replay::verify_replay(&replay).map_err(|error| {
        StudioLeagueError::Invalid(format!(
            "human occurrence replay failed verification: {error}"
        ))
    })?;

    // 4. The replay must describe the game the envelope claims.
    if replay.player_count != 2 {
        return Err(StudioLeagueError::Invalid(format!(
            "human occurrence `{}` replay is a {}-player game; a rated human match is 1v1",
            occurrence.occurrence_id, replay.player_count
        )));
    }
    if replay.seed != occurrence.seed {
        return Err(StudioLeagueError::Invalid(format!(
            "human occurrence `{}` records seed {} but its replay was played with seed {}",
            occurrence.occurrence_id, occurrence.seed, replay.seed
        )));
    }
    if occurrence.human_seat > 1 {
        return Err(StudioLeagueError::Invalid(format!(
            "human occurrence `{}` carries human_seat {} for a two-player game",
            occurrence.occurrence_id, occurrence.human_seat
        )));
    }
    // `verify_replay` above proves the replay re-executes to a terminal result;
    // the winners it recorded are that result.
    if replay.result.winners.is_empty() {
        return Err(StudioLeagueError::Invalid(format!(
            "human occurrence `{}` replay is not a completed game: it records no winner",
            occurrence.occurrence_id
        )));
    }

    // 5. The human identity must be the league's own local human, under the
    //    manifest hash the league currently stores. Either mismatch means the
    //    envelope describes a different identity authority than this league's.
    let Some(local_human) = context.local_human_participant_id else {
        return Err(StudioLeagueError::Invalid(
            "this league has no local human participant; a human occurrence cannot be attributed"
                .to_string(),
        ));
    };
    if occurrence.human.participant_id != local_human {
        return Err(StudioLeagueError::Invalid(format!(
            "human occurrence `{}` names human participant `{}`, but this league's local human is `{local_human}`",
            occurrence.occurrence_id, occurrence.human.participant_id
        )));
    }
    let Some(stored_manifest_hash) = context.stored_identity_manifest_hash else {
        return Err(StudioLeagueError::Invalid(
            "this league has no stored identity manifest hash; the human identity authority cannot be confirmed"
                .to_string(),
        ));
    };
    if occurrence.human.identity_manifest_hash != stored_manifest_hash {
        return Err(StudioLeagueError::Invalid(format!(
            "human occurrence `{}` was authored under identity manifest `{}`, but this league stores `{stored_manifest_hash}`; the identity authority changed since the game started",
            occurrence.occurrence_id, occurrence.human.identity_manifest_hash
        )));
    }

    // 6. The opponent's policy key is re-derived from the raw command through
    //    the one shared resolver, and must reproduce the envelope's key. This is
    //    what stops durable evidence from being silently re-interpreted later.
    let policy_identity = resolve_policy_identity(
        Some(&occurrence.opponent.program),
        &occurrence.opponent.args,
    );
    let resolved_key = match &policy_identity {
        SeatConfigurationIdentityV1::Resolved(identity) => identity.key(),
        SeatConfigurationIdentityV1::Unresolved { reason } => {
            return Err(StudioLeagueError::Invalid(format!(
                "human occurrence `{}` opponent command cannot be attributed: {reason}",
                occurrence.occurrence_id
            )))
        }
    };
    if resolved_key != occurrence.opponent.policy_key {
        return Err(StudioLeagueError::Invalid(format!(
            "human occurrence `{}` opponent command re-resolves to policy `{resolved_key}`, but the envelope records `{}`",
            occurrence.occurrence_id, occurrence.opponent.policy_key
        )));
    }

    // 7. Two seats, shaped per the frozen contract. Scores, ranks, and winners
    //    come from the verified replay's terminal result.
    let scores = &replay.result.scores;
    let ranks = &replay.result.ranks;
    let winners = &replay.result.winners;
    let seat_facts = |seat: u8| -> Result<(i32, i32, bool)> {
        let index = seat as usize;
        let score = scores.get(index).copied().ok_or_else(|| {
            StudioLeagueError::Invalid(format!(
                "human occurrence `{}` replay result has no score for seat {seat}",
                occurrence.occurrence_id
            ))
        })?;
        let rank = ranks.get(index).copied().ok_or_else(|| {
            StudioLeagueError::Invalid(format!(
                "human occurrence `{}` replay result has no rank for seat {seat}",
                occurrence.occurrence_id
            ))
        })?;
        Ok((score as i32, rank as i32, winners.contains(&seat)))
    };

    let human_seat = occurrence.human_seat;
    let engine_seat = 1 - human_seat;
    let (human_score, human_rank, human_won) = seat_facts(human_seat)?;
    let (engine_score, engine_rank, engine_won) = seat_facts(engine_seat)?;

    let mut seats = vec![
        StudioMatchSeatV1 {
            seat: human_seat,
            // A human has no engine identity; the ledger prefers the explicit
            // participant id. Inventing an EngineIdentityV1 here would claim the
            // human ran as an engine runtime.
            identity: None,
            policy_identity: SeatPolicyIdentityV1::NoConfigEvidence,
            participant_id: Some(occurrence.human.participant_id.clone()),
            display_name: Some(occurrence.human.display_name.clone()),
            score: Some(human_score),
            rank: Some(human_rank),
            won: human_won,
        },
        StudioMatchSeatV1 {
            seat: engine_seat,
            identity: Some(EngineIdentityV1::new(
                occurrence.opponent.runtime_name.clone(),
                occurrence.opponent.runtime_version.clone(),
            )),
            policy_identity: SeatPolicyIdentityV1::Resolved {
                policy_key: occurrence.opponent.policy_key.clone(),
            },
            participant_id: None,
            display_name: Some(occurrence.opponent.display_name.clone()),
            score: Some(engine_score),
            rank: Some(engine_rank),
            won: engine_won,
        },
    ];
    seats.sort_by_key(|seat| seat.seat);

    let record = StudioMatchRecordV1 {
        source_kind: HUMAN_PLAY_SOURCE_KIND.to_string(),
        source_identity: format!("runtime:{}", occurrence.occurrence_id),
        source_path: Some(replay_source_path.to_string()),
        // The complete occurrence evidence, never the replay SHA alone.
        source_document_hash: human_runtime_occurrence_evidence_hash(occurrence),
        played_at: Some(occurrence.completed_at),
        ruleset_fingerprint: replay.ruleset_fingerprint.as_str().to_string(),
        engine_version: Some(replay.engine_version.clone()),
        player_count: replay.player_count,
        status: MatchStatus::Completed,
        seats,
        completed_plies: Some(replay.steps.len() as u32),
        main_turn_count: None,
        replay: ReplayBindingV1 {
            document_hash: Some(occurrence.replay_sha256.clone()),
            final_hash: Some(verified.final_state_hash.clone()),
            storage: Some(ReplayStorage::InPlaceReference),
            path: Some(replay_source_path.to_string()),
            verification: Some(ReplayVerification::Verified),
        },
        diagnostic: false,
    };
    record.validate_for_ingest()?;
    Ok(record)
}
