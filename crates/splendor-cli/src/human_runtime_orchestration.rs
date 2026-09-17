//! Host-only human producer orchestration. No Arena config/report and no ledger
//! authority: freeze identity, publish two documents, then re-offer disk bytes.

use std::fs;
use std::path::{Path, PathBuf};

use splendor_eval::RatedAgentV1;
use splendor_replay::ReplayV1;
use splendor_studio_league::{
    complete_human_runtime_occurrence, now_epoch_seconds, open_completion_league,
    parse_human_runtime_occurrence, replay_document_sha256, resolve_policy_identity,
    CompletionOutcomeV1, HumanCompletionRequestV1, HumanOccurrenceHumanV1,
    HumanOccurrenceOpponentV1, HumanRuntimeOccurrenceV1, IdentityManifestV1, IngestOutcome,
    SeatConfigurationIdentityV1, StudioLeagueError, StudioLeaguePathsV1,
    HUMAN_RUNTIME_OCCURRENCE_FORMAT, HUMAN_RUNTIME_OCCURRENCE_VERSION,
};

use crate::atomic_output::{commit_completed_with, publish_new};
use crate::runtime_orchestration::completion_receipt_json;

/// Present ONLY for Studio Host games. Standalone human-play never acquires it.
/// Construction checks authored identity, not availability of the derived DB.
/// The Host installs this in a Session only after the selected entry handshakes.
pub(crate) struct HumanGameAuthority {
    pub paths: StudioLeaguePathsV1,
    pub human: HumanOccurrenceHumanV1,
    pub opponent: HumanOccurrenceOpponentV1,
}

impl HumanGameAuthority {
    pub fn freeze(
        paths: &StudioLeaguePathsV1,
        registry_id: &str,
        selected: &RatedAgentV1,
    ) -> Result<Self, String> {
        let manifest = IdentityManifestV1::load(paths.identity())
            .map_err(|e| format!("cannot validate human identity authority: {e}"))?
            .ok_or("human identity authority is missing; rated game cannot start")?;
        let human = manifest
            .local_human
            .as_ref()
            .ok_or("identity manifest has no local human; rated game cannot start")?;
        let program =
            selected.command.program.to_str().ok_or(
                "registered program is not UTF-8; cannot preserve exact identity evidence",
            )?;
        let policy_key = match resolve_policy_identity(Some(program), &selected.command.args) {
            SeatConfigurationIdentityV1::Resolved(identity) => identity.key(),
            SeatConfigurationIdentityV1::Unresolved { reason } => {
                return Err(format!(
                    "opponent policy unresolved; rated game cannot start: {reason}"
                ));
            }
        };
        Ok(Self {
            paths: paths.clone(),
            human: HumanOccurrenceHumanV1 {
                participant_id: human.participant_id.clone(),
                display_name: human.display_name.clone(),
                identity_manifest_hash: manifest.hash().map_err(|e| e.to_string())?,
            },
            opponent: HumanOccurrenceOpponentV1 {
                registry_id: registry_id.to_string(),
                agent_id: selected.id.clone(),
                display_name: selected.display_name.clone(),
                runtime_name: selected.runtime_name.clone(),
                runtime_version: selected.runtime_version.clone(),
                program: program.to_string(),
                args: selected.command.args.clone(),
                policy_key,
            },
        })
    }

    pub fn occurrence(
        &self,
        session_id: &str,
        human_seat: u8,
        replay: &ReplayV1,
        replay_bytes: &[u8],
        completed_at: i64,
    ) -> HumanRuntimeOccurrenceV1 {
        HumanRuntimeOccurrenceV1 {
            format: HUMAN_RUNTIME_OCCURRENCE_FORMAT.into(),
            version: HUMAN_RUNTIME_OCCURRENCE_VERSION,
            occurrence_id: session_id.to_string(),
            completed_at,
            seed: replay.seed,
            human_seat,
            replay_sha256: replay_document_sha256(replay_bytes),
            human: self.human.clone(),
            opponent: self.opponent.clone(),
        }
    }
}

pub(crate) struct HumanOccurrenceEvidence {
    dir: PathBuf,
    pub replay: PathBuf,
    pub occurrence: PathBuf,
}

impl HumanOccurrenceEvidence {
    pub fn in_dir(dir: &Path) -> Self {
        Self {
            dir: dir.into(),
            replay: dir.join("replay.json"),
            occurrence: dir.join("occurrence.json"),
        }
    }
}

#[derive(Debug, PartialEq, Eq)]
pub(crate) enum HumanOccurrenceSlot {
    Empty,
    Complete,
    Ambiguous(String),
}

/// Absence, partial/foreign evidence and inspection failure are distinct. Never
/// interpret a directory, symlink, Arena slot or crash residue as an empty slot.
pub(crate) fn human_occurrence_slot(evidence: &HumanOccurrenceEvidence) -> HumanOccurrenceSlot {
    let entries = match fs::read_dir(&evidence.dir) {
        Ok(entries) => entries,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return HumanOccurrenceSlot::Empty,
        Err(e) => return HumanOccurrenceSlot::Ambiguous(format!("cannot inspect human slot: {e}")),
    };
    let mut count = 0;
    for entry in entries {
        let entry = match entry {
            Ok(entry) => entry,
            Err(e) => return HumanOccurrenceSlot::Ambiguous(e.to_string()),
        };
        if !matches!(
            entry.file_name().to_str(),
            Some("replay.json" | "occurrence.json")
        ) || !entry.file_type().is_ok_and(|kind| kind.is_file())
        {
            return HumanOccurrenceSlot::Ambiguous(
                "human slot contains foreign or non-file evidence".into(),
            );
        }
        count += 1;
    }
    if count == 0 {
        return HumanOccurrenceSlot::Empty;
    }
    if count != 2 {
        return HumanOccurrenceSlot::Ambiguous("human slot contains partial evidence".into());
    }
    match fs::read(&evidence.occurrence)
        .map_err(|e| e.to_string())
        .and_then(|bytes| parse_human_runtime_occurrence(&bytes).map_err(|e| e.to_string()))
    {
        Ok(Some(_)) => HumanOccurrenceSlot::Complete,
        Ok(None) => HumanOccurrenceSlot::Ambiguous("not a human occurrence envelope".into()),
        Err(e) => HumanOccurrenceSlot::Ambiguous(e),
    }
}

/// Legacy replay/meta must have succeeded before calling this. Each publish is
/// synced, atomic and no-overwrite; occurrence.json is the LAST commit marker.
/// A hard crash may leave partial evidence; the classifier refuses it, not heals it.
pub(crate) fn publish_human_evidence(
    evidence: &HumanOccurrenceEvidence,
    occurrence: &HumanRuntimeOccurrenceV1,
    replay_json: &str,
) -> Result<(), String> {
    if human_occurrence_slot(evidence) != HumanOccurrenceSlot::Empty {
        return Err("human occurrence slot is not empty; refusing to overwrite evidence".into());
    }
    let envelope = serde_json::to_string_pretty(occurrence).map_err(|e| e.to_string())?;
    fs::create_dir_all(&evidence.dir).map_err(|e| e.to_string())?;
    commit_completed_with(
        &evidence.replay,
        replay_json,
        &evidence.occurrence,
        &envelope,
        publish_new,
    )
    .map_err(|e| e.to_string())
}

pub(crate) enum HumanCompletionError {
    Conflict(String),
    Failed(StudioLeagueError),
}

/// No registry, agent process, recorder or caller-supplied result is available
/// here. The requested-session binding happens BEFORE opening completion.
pub(crate) fn complete_persisted_human_occurrence(
    evidence: &HumanOccurrenceEvidence,
    paths: &StudioLeaguePathsV1,
    expected_session_id: &str,
) -> Result<CompletionOutcomeV1, HumanCompletionError> {
    let read = |path: &Path| fs::read(path).map_err(|e| HumanCompletionError::Failed(e.into()));
    let envelope = read(&evidence.occurrence)?;
    let occurrence = parse_human_runtime_occurrence(&envelope)
        .map_err(|e| HumanCompletionError::Conflict(e.to_string()))?
        .ok_or_else(|| HumanCompletionError::Conflict("not a human occurrence envelope".into()))?;
    if occurrence.occurrence_id != expected_session_id {
        return Err(HumanCompletionError::Conflict(format!(
            "human occurrence `{}` is not requested session `{expected_session_id}`; internally consistent documents are not this occurrence's",
            occurrence.occurrence_id
        )));
    }
    let replay_bytes = read(&evidence.replay)?;
    let mut league =
        open_completion_league(paths, now_epoch_seconds()).map_err(HumanCompletionError::Failed)?;
    complete_human_runtime_occurrence(
        &mut league,
        &HumanCompletionRequestV1 {
            occurrence: &occurrence,
            replay_bytes: &replay_bytes,
            replay_source_path: &evidence.replay.to_string_lossy(),
        },
    )
    .map_err(HumanCompletionError::Failed)
}

#[derive(Debug, Clone, serde::Serialize)]
pub(crate) struct HumanLeagueCompletion {
    pub status: &'static str,
    pub retryable: bool,
    pub receipt: Option<serde_json::Value>,
    pub error: Option<String>,
}

impl HumanLeagueCompletion {
    pub fn failed(message: String, retryable: bool) -> Self {
        Self {
            status: "failed",
            retryable,
            receipt: None,
            error: Some(message),
        }
    }

    pub fn from_result(result: Result<CompletionOutcomeV1, HumanCompletionError>) -> Self {
        match result {
            Ok(completion) => Self {
                status: match completion.ingest {
                    IngestOutcome::Inserted { .. } => "inserted",
                    IngestOutcome::AlreadyPresent { .. } => "already_present",
                },
                retryable: false,
                receipt: Some(completion_receipt_json(&completion)),
                error: None,
            },
            Err(HumanCompletionError::Conflict(message)) => Self::failed(message, false),
            Err(HumanCompletionError::Failed(error)) => {
                // Structural identity/policy/evidence failures and canonical-tail
                // rejection (Invalid, with rebuild guidance) are NOT transient.
                // IO/DB availability can be retried, never promised to converge.
                let retryable = matches!(
                    error,
                    StudioLeagueError::Io(_) | StudioLeagueError::Database(_)
                );
                Self::failed(error.to_string(), retryable)
            }
        }
    }
}
