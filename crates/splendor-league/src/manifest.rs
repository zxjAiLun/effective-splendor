use std::collections::HashSet;

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use splendor_arena::AgentCommand;
use splendor_eval::{
    EvaluationAgentV1, EvaluationPlanV1, EVALUATION_PLAN_FORMAT, EVALUATION_VERSION,
};

use crate::LeagueError;

pub const LEAGUE_MANIFEST_FORMAT: &str = "effective-splendor-league-manifest";
pub const LEAGUE_VERSION: u32 = 1;
const MAX_ID_BYTES: usize = 96;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum LeagueRoleV1 {
    Champion,
    Candidate,
    Historical,
    Exploiter,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LeagueAgentV1 {
    pub id: String,
    pub role: LeagueRoleV1,
    pub policy_version: String,
    pub model_version: Option<String>,
    pub runtime_name: String,
    pub runtime_version: String,
    pub command: AgentCommand,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LeagueManifestV1 {
    pub format: String,
    pub version: u32,
    pub league_id: String,
    pub lineup_id: String,
    pub agents: Vec<LeagueAgentV1>,
    pub game_seeds: Vec<u64>,
    pub handshake_timeout_ms: u64,
    pub move_timeout_ms: u64,
    pub shutdown_grace_ms: u64,
}

impl LeagueManifestV1 {
    pub fn validate(&self) -> Result<(), LeagueError> {
        if self.format != LEAGUE_MANIFEST_FORMAT {
            return Err(invalid(format!(
                "format must be '{LEAGUE_MANIFEST_FORMAT}'"
            )));
        }
        if self.version != LEAGUE_VERSION {
            return Err(invalid(format!("version must be {LEAGUE_VERSION}")));
        }
        validate_id("league_id", &self.league_id)?;
        validate_id("lineup_id", &self.lineup_id)?;
        let mut ids = HashSet::new();
        let mut runtime_identities = HashSet::new();
        let mut champions = 0usize;
        for agent in &self.agents {
            validate_id("agent id", &agent.id)?;
            validate_id("policy_version", &agent.policy_version)?;
            if let Some(model_version) = &agent.model_version {
                validate_id("model_version", model_version)?;
            }
            validate_id("runtime_name", &agent.runtime_name)?;
            validate_id("runtime_version", &agent.runtime_version)?;
            if !ids.insert(agent.id.clone()) {
                return Err(invalid(format!("duplicate agent id `{}`", agent.id)));
            }
            if !runtime_identities
                .insert((agent.runtime_name.clone(), agent.runtime_version.clone()))
            {
                return Err(invalid(format!(
                    "duplicate runtime identity `{}@{}`",
                    agent.runtime_name, agent.runtime_version
                )));
            }
            champions += usize::from(agent.role == LeagueRoleV1::Champion);
        }
        if champions != 1 {
            return Err(invalid("exactly one lineup agent must have role champion"));
        }
        self.evaluation_plan_v1()?;
        Ok(())
    }

    pub fn evaluation_plan_v1(&self) -> Result<EvaluationPlanV1, LeagueError> {
        let plan = EvaluationPlanV1 {
            format: EVALUATION_PLAN_FORMAT.to_string(),
            version: EVALUATION_VERSION,
            evaluation_id: format!("{}-{}", self.league_id, self.lineup_id),
            agents: self
                .agents
                .iter()
                .map(|agent| EvaluationAgentV1 {
                    id: agent.id.clone(),
                    command: agent.command.clone(),
                })
                .collect(),
            game_seeds: self.game_seeds.clone(),
            handshake_timeout_ms: self.handshake_timeout_ms,
            move_timeout_ms: self.move_timeout_ms,
            shutdown_grace_ms: self.shutdown_grace_ms,
        };
        plan.validate()
            .map_err(|error| LeagueError::InvalidEvaluationPlan(error.to_string()))?;
        Ok(plan)
    }
}

pub fn league_manifest_hash_v1(manifest: &LeagueManifestV1) -> Result<String, LeagueError> {
    manifest.validate()?;
    let json = serde_json::to_string(manifest)
        .map_err(|error| LeagueError::Serialization(error.to_string()))?;
    let mut hasher = Sha256::new();
    hasher.update(b"effective-splendor-league-manifest-v1\0");
    hasher.update(json.as_bytes());
    Ok(hex::encode(hasher.finalize()))
}

fn validate_id(label: &str, value: &str) -> Result<(), LeagueError> {
    if value.trim().is_empty()
        || value.len() > MAX_ID_BYTES
        || value.as_bytes().iter().any(|byte| *byte < 0x20)
    {
        return Err(invalid(format!(
            "{label} must be non-empty, at most {MAX_ID_BYTES} bytes, and contain no C0 controls"
        )));
    }
    Ok(())
}

fn invalid(message: impl Into<String>) -> LeagueError {
    LeagueError::InvalidManifest(message.into())
}
