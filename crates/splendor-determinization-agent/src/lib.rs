//! Live Arena policy for the frozen M07 root-determinization baseline.
//!
//! The policy consumes only the public [`splendor_agent::DecisionContext`]:
//! the acting player's observation, cumulative player-projected visible event
//! history, server-certified legal actions, and public request metadata. It
//! never receives a replay, raw game seed, referee event, or `FullState`.

use splendor_agent::{run_agent, AgentError, AgentIdentity, AgentPolicy, DecisionContext};
use splendor_core::{Action, Ruleset};
use splendor_imperfect_search::{
    aggregate_root_determinizations_with_depth_diagnostics_v1, analyze_player_view_attribution_v1,
    analyze_player_view_v1, ContinuationDepthDiagnosticsV1, ImperfectSearchError,
    RootDeterminizationConfigV1,
};
use splendor_search::{canonical_order, AttributionProfile};
use thiserror::Error;

pub mod s2b_overlay;
pub mod s3_rollout;
pub use s2b_overlay::{
    run_n1_buy_overlay_agent_v1, N1BuyOverlayPolicy, S2B_OVERLAY_AGENT_NAME,
};

/// Stable Arena identity for the first live M07-backed policy.
pub const DETERMINIZATION_AGENT_NAME: &str = "effective-splendor-determinization-agent-v1";
/// Policy release version, independent of the engine crate version.
pub const DETERMINIZATION_AGENT_VERSION: &str = "1";

/// A player-view-only live policy backed by M07 root determinization.
#[derive(Debug, Clone)]
pub struct DeterminizationAgentPolicyV1 {
    ruleset: Ruleset,
    config: RootDeterminizationConfigV1,
    last_telemetry: Option<PerDecisionTelemetry>,
    emit_depth_diagnostics: bool,
}

/// What [`DeterminizationAgentPolicyV1`] records about its most recent
/// decision — all values the policy already computes or receives publicly.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PerDecisionTelemetry {
    pub game_id: String,
    pub request_id: u64,
    pub decide_micros: u64,
    pub stats: splendor_imperfect_search::RootDeterminizationStatsV1,
    /// Present only when the S1 depth-diagnostics variant was used.
    pub depth_diagnostics: Option<ContinuationDepthDiagnosticsV1>,
}

impl DeterminizationAgentPolicyV1 {
    /// Create a base-rules policy after validating all deterministic budgets.
    pub fn new(config: RootDeterminizationConfigV1) -> Result<Self, DeterminizationAgentError> {
        config.validate()?;
        Ok(Self {
            ruleset: Ruleset::base_v1(),
            config,
            last_telemetry: None,
            emit_depth_diagnostics: false,
        })
    }

    /// Enable S1 depth diagnostics (per-continuation completed-depth and
    /// stop-reason histograms in the telemetry). This only selects the
    /// diagnostics aggregation variant; the chosen action and the frozen
    /// stats are identical.
    pub fn with_depth_diagnostics(mut self) -> Self {
        self.emit_depth_diagnostics = true;
        self
    }

    pub fn config(&self) -> RootDeterminizationConfigV1 {
        self.config
    }

    /// Diagnostics aggregation: build the player information set and run the
    /// depth-diagnostics aggregation variant. The frozen action/stats equal
    /// those of `analyze_player_view_v1` by construction (same pipeline).
    fn analyze_with_diagnostics(
        &self,
        observation: &splendor_core::Observation,
        visible_history: &[splendor_core::VisibleEvent],
    ) -> Result<
        (
            splendor_imperfect_search::RootDeterminizationResultV1,
            ContinuationDepthDiagnosticsV1,
        ),
        DeterminizationAgentError,
    > {
        use splendor_belief::build_information_set_v1;

        let information_set = build_information_set_v1(self.ruleset, observation, visible_history)
            .map_err(|error| {
                DeterminizationAgentError::Search(splendor_imperfect_search::ImperfectSearchError::from(
                    error,
                ))
            })?;
        let (result, diagnostics) = aggregate_root_determinizations_with_depth_diagnostics_v1(
            &information_set,
            self.config,
        )
        .map_err(DeterminizationAgentError::Search)?;
        Ok((result, diagnostics))
    }

    /// Telemetry of the most recent successful decision, if any.
    pub fn last_telemetry(&self) -> Option<&PerDecisionTelemetry> {
        self.last_telemetry.as_ref()
    }
}

/// Fail-closed live-policy errors.
#[derive(Debug, Error)]
pub enum DeterminizationAgentError {
    #[error(transparent)]
    Search(#[from] ImperfectSearchError),
    #[error("request recipient does not match observation viewer")]
    RecipientViewerMismatch,
    #[error("server-certified legal actions do not match the player-view search root")]
    LegalActionSetMismatch,
}

impl AgentPolicy for DeterminizationAgentPolicyV1 {
    type Error = DeterminizationAgentError;

    fn choose_action(&mut self, context: DecisionContext<'_>) -> Result<Action, Self::Error> {
        if context.meta.recipient_seat != context.observation.viewer {
            return Err(DeterminizationAgentError::RecipientViewerMismatch);
        }

        let started = std::time::Instant::now();
        let outcome = if self.emit_depth_diagnostics {
            // S1 diagnostics variant: identical action and frozen stats,
            // plus per-continuation depth/stop histograms.
            let (result, diagnostics) = self.analyze_with_diagnostics(
                &context.observation,
                context.visible_history,
            )?;
            (result, Some(diagnostics))
        } else {
            (
                analyze_player_view_v1(
                    self.ruleset,
                    &context.observation,
                    context.visible_history,
                    self.config,
                )?
                .result()
                .clone(),
                None,
            )
        };
        let decide_micros = u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX);
        let (result, depth_diagnostics) = outcome;
        if let Some(t) = self.last_telemetry.as_mut() {
            t.game_id = context.meta.game_id.clone();
            t.request_id = context.meta.request_id;
            t.decide_micros = decide_micros;
            t.stats = result.stats.clone();
            t.depth_diagnostics = depth_diagnostics;
        } else {
            self.last_telemetry = Some(PerDecisionTelemetry {
                game_id: context.meta.game_id.clone(),
                request_id: context.meta.request_id,
                decide_micros,
                stats: result.stats.clone(),
                depth_diagnostics,
            });
        }
        let search_actions = result
            .action_aggregates
            .iter()
            .map(|aggregate| aggregate.action)
            .collect::<Vec<_>>();
        if canonical_order(context.legal_actions) != search_actions {
            return Err(DeterminizationAgentError::LegalActionSetMismatch);
        }

        Ok(result.action)
    }
}

/// M44A research policy backed by masked StaticEvaluatorAttributionV1.
#[derive(Debug, Clone)]
pub struct DeterminizationAgentAttributionPolicyV1 {
    ruleset: Ruleset,
    config: RootDeterminizationConfigV1,
    profile: AttributionProfile,
}

impl DeterminizationAgentAttributionPolicyV1 {
    pub fn new(
        config: RootDeterminizationConfigV1,
        profile: AttributionProfile,
    ) -> Result<Self, DeterminizationAgentError> {
        config.validate()?;
        Ok(Self {
            ruleset: Ruleset::base_v1(),
            config,
            profile,
        })
    }

    pub fn profile(&self) -> AttributionProfile {
        self.profile
    }

    pub fn config(&self) -> RootDeterminizationConfigV1 {
        self.config
    }
}

impl AgentPolicy for DeterminizationAgentAttributionPolicyV1 {
    type Error = DeterminizationAgentError;

    fn choose_action(&mut self, context: DecisionContext<'_>) -> Result<Action, Self::Error> {
        if context.meta.recipient_seat != context.observation.viewer {
            return Err(DeterminizationAgentError::RecipientViewerMismatch);
        }

        let analysis = analyze_player_view_attribution_v1(
            self.ruleset,
            &context.observation,
            context.visible_history,
            self.config,
            self.profile,
        )?;
        let result = analysis.result();
        let search_actions = result
            .action_aggregates
            .iter()
            .map(|aggregate| aggregate.action)
            .collect::<Vec<_>>();
        if canonical_order(context.legal_actions) != search_actions {
            return Err(DeterminizationAgentError::LegalActionSetMismatch);
        }

        Ok(result.action)
    }
}

/// Run the M44A attribution research policy over the standard NDJSON Agent SDK runtime.
pub fn run_determinization_agent_attribution_v1<R, W, E>(
    input: R,
    output: W,
    mut diagnostics: E,
    config: RootDeterminizationConfigV1,
    profile: AttributionProfile,
    identity: AgentIdentity<'_>,
) -> Result<(), AgentError>
where
    R: std::io::BufRead,
    W: std::io::Write,
    E: std::io::Write,
{
    let policy = match DeterminizationAgentAttributionPolicyV1::new(config, profile) {
        Ok(policy) => policy,
        Err(error) => {
            let agent_error = AgentError::Policy(error.to_string());
            let _ = writeln!(diagnostics, "error: {agent_error}");
            let _ = diagnostics.flush();
            return Err(agent_error);
        }
    };
    run_agent(input, output, diagnostics, identity, 0, policy)
}

/// Run the v1 policy over the standard NDJSON Agent SDK runtime with custom identity.
pub fn run_determinization_agent_with_identity_v1<R, W, E>(
    input: R,
    output: W,
    mut diagnostics: E,
    config: RootDeterminizationConfigV1,
    identity: AgentIdentity<'_>,
) -> Result<(), AgentError>
where
    R: std::io::BufRead,
    W: std::io::Write,
    E: std::io::Write,
{
    let policy = match DeterminizationAgentPolicyV1::new(config) {
        Ok(policy) => policy,
        Err(error) => {
            let agent_error = AgentError::Policy(error.to_string());
            let _ = writeln!(diagnostics, "error: {agent_error}");
            let _ = diagnostics.flush();
            return Err(agent_error);
        }
    };
    run_agent(input, output, diagnostics, identity, 0, policy)
}

/// Run the v1 policy over the standard NDJSON Agent SDK runtime with default identity.
pub fn run_determinization_agent_v1<R, W, E>(
    input: R,
    output: W,
    diagnostics: E,
    config: RootDeterminizationConfigV1,
) -> Result<(), AgentError>
where
    R: std::io::BufRead,
    W: std::io::Write,
    E: std::io::Write,
{
    run_determinization_agent_with_identity_v1(
        input,
        output,
        diagnostics,
        config,
        AgentIdentity {
            name: DETERMINIZATION_AGENT_NAME,
            version: DETERMINIZATION_AGENT_VERSION,
        },
    )
}

/// S0 per-decision telemetry: one JSON line per successful decision,
/// emitted to the diagnostics (stderr) sink.
///
/// Frozen boundary (S0 DESIGN_V2): this reuses counters the search already
/// computes (`RootDeterminizationStatsV1`) plus a wall-clock duration. It adds
/// NO new search-side statistics, no completed-depth, no stop-reason, and no
/// budget-exhaustion instrumentation, and it never alters the chosen action.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "snake_case", deny_unknown_fields)]
pub struct PerDecisionStatsV1 {
    /// Game id from the request metadata (public correlation only).
    pub game_id: String,
    /// Server sequence number of the action request.
    pub request_id: u64,
    /// Wall-clock duration of this decision in microseconds.
    pub decide_micros: u64,
    /// Aggregated search counters for this decision (already computed by
    /// the search; this layer only reports them).
    pub stats: splendor_imperfect_search::RootDeterminizationStatsV1,
    /// Present only with the S1 `--emit-depth-histogram` mode: per-
    /// continuation completed-depth and stop-reason histograms.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub depth_diagnostics: Option<ContinuationDepthDiagnosticsV1>,
}

impl From<&PerDecisionTelemetry> for PerDecisionStatsV1 {
    fn from(t: &PerDecisionTelemetry) -> Self {
        PerDecisionStatsV1 {
            game_id: t.game_id.clone(),
            request_id: t.request_id,
            decide_micros: t.decide_micros,
            stats: t.stats.clone(),
            depth_diagnostics: t.depth_diagnostics.clone(),
        }
    }
}

/// Wrapper that appends one `PerDecisionStatsV1` JSON line per successful
/// decision of a [`DeterminizationAgentPolicyV1`] to a dedicated stats file.
///
/// Decision behavior is bit-identical to the wrapped policy: the wrapper
/// delegates `choose_action` unchanged and only observes timing plus the
/// result's already-computed aggregate stats. Telemetry writes are
/// best-effort — an I/O failure never fails or alters a decision.
pub struct StatsEmittingPolicy<E> {
    inner: DeterminizationAgentPolicyV1,
    sink: E,
}

impl<E> StatsEmittingPolicy<E> {
    pub fn new(inner: DeterminizationAgentPolicyV1, sink: E) -> Self {
        Self { inner, sink }
    }
}

impl<E> AgentPolicy for StatsEmittingPolicy<E>
where
    E: std::io::Write,
{
    type Error = DeterminizationAgentError;

    fn choose_action(&mut self, context: DecisionContext<'_>) -> Result<Action, Self::Error> {
        let result = self.inner.choose_action(context);
        if let (Ok(_), Some(t)) = (&result, self.inner.last_telemetry()) {
            let line = serde_json::to_string(&PerDecisionStatsV1::from(t))
                .unwrap_or_else(|_| "{}".to_owned());
            let _ = writeln!(self.sink, "{line}");
            let _ = self.sink.flush();
        }
        result
    }
}

/// Run the S0 telemetry-wrapped v1 policy over the standard NDJSON Agent SDK
/// runtime: identical decisions to [`run_determinization_agent_with_identity_v1`],
/// plus one `PerDecisionStatsV1` JSON line per successful decision appended
/// to `stats_out` (created if missing).
///
/// The stats file is agent-owned sidecar telemetry (S0 frozen boundary);
/// the arena's bounded stderr tail stays untouched.
pub fn run_determinization_agent_with_stats_v1<R, W, E>(
    input: R,
    output: W,
    mut diagnostics: E,
    config: RootDeterminizationConfigV1,
    identity: AgentIdentity<'_>,
    stats_out: std::path::PathBuf,
    emit_depth_histogram: bool,
) -> Result<(), AgentError>
where
    R: std::io::BufRead,
    W: std::io::Write,
    E: std::io::Write,
{
    let stats_file = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&stats_out)
        .map_err(|error| {
            let agent_error = AgentError::Policy(format!(
                "cannot open stats file {}: {error}",
                stats_out.display()
            ));
            agent_error
        })?;
    let stats_file = std::io::BufWriter::new(stats_file);
    let policy = match DeterminizationAgentPolicyV1::new(config) {
        Ok(policy) => policy,
        Err(error) => {
            let agent_error = AgentError::Policy(error.to_string());
            let _ = writeln!(diagnostics, "error: {agent_error}");
            let _ = diagnostics.flush();
            return Err(agent_error);
        }
    };
    let policy = if emit_depth_histogram {
        policy.with_depth_diagnostics()
    } else {
        policy
    };
    let policy = StatsEmittingPolicy::new(policy, stats_file);
    run_agent(input, output, diagnostics, identity, 0, policy)
}

#[cfg(test)]
mod tests {
    use super::*;
    use splendor_agent::{PublicRequestMeta, StableRng};
    use splendor_core::{
        observation_hash, visible_events, Audience, FullState, GameConfig, PlayerId,
    };
    use splendor_search::SearchConfigV1;

    #[test]
    fn stats_emitting_policy_keeps_decisions_identical_and_records_telemetry() {
        use splendor_agent::DecisionContext;

        // Build a real decision context from a fresh game state (same
        // conventions as the existing live-policy test).
        let (state, setup) = FullState::new(GameConfig {
            player_count: 2,
            seed: 20260908,
            ..Default::default()
        })
        .unwrap();
        let viewer = PlayerId(0);
        let obs_owned: splendor_core::Observation = state.observation(viewer);
        let actions: Vec<splendor_core::Action> = state.legal_actions();
        let history: Vec<splendor_core::VisibleEvent> =
            visible_events(&setup.events, Audience::Player(viewer));
        let obs_hash = observation_hash(&obs_owned).clone();
        let history_ref: &'static [splendor_core::VisibleEvent] =
            Box::leak(history.into_boxed_slice());

        let mut rng_a = StableRng::new(7);
        let mut rng_b = StableRng::new(7);
        let cfg = RootDeterminizationConfigV1 {
            sample_seed: 20260703,
            sample_count: 4,
            continuation_search: SearchConfigV1 {
                max_depth_turns: 1,
                max_nodes: 2000,
            },
        };
        cfg.validate().unwrap();

        let mut plain = DeterminizationAgentPolicyV1::new(cfg).unwrap();
        let mut sink: Vec<u8> = Vec::new();
        let mut wrapped = StatsEmittingPolicy::new(
            DeterminizationAgentPolicyV1::new(cfg).unwrap(),
            &mut sink,
        );

        let meta = |game_id: &str, request_id: u64| PublicRequestMeta {
            game_id: game_id.to_owned(),
            recipient_seat: PlayerId(0),
            request_id,
            observation_hash: obs_hash.clone(),
        };

        // Same decision from both policies.
        let action_plain = plain
            .choose_action(DecisionContext {
                observation: obs_owned.clone(),
                visible_history: history_ref,
                legal_actions: &actions,
                meta: meta("s0-test", 1),
                rng: &mut rng_a,
            })
            .unwrap();
        let action_wrapped = wrapped
            .choose_action(DecisionContext {
                observation: obs_owned,
                visible_history: history_ref,
                legal_actions: &actions,
                meta: meta("s0-test", 1),
                rng: &mut rng_b,
            })
            .unwrap();
        assert_eq!(action_plain, action_wrapped);

        // Exactly one telemetry line with the frozen fields.
        let text = String::from_utf8(sink).unwrap();
        let lines: Vec<&str> = text.lines().collect();
        assert_eq!(lines.len(), 1, "one line per decision: {text}");
        let v: serde_json::Value = serde_json::from_str(lines[0]).unwrap();
        assert_eq!(v["game_id"], "s0-test");
        assert_eq!(v["request_id"], 1);
        assert!(v["decide_micros"].as_u64().unwrap() > 0);
        let stats = &v["stats"];
        assert_eq!(stats["samples"], 4);
        assert!(stats["root_actions"].as_u64().unwrap() > 0);
        assert!(stats["continuation_searches"].as_u64().unwrap() > 0);
        // Frozen boundary: no completed-depth / stop-reason fields exist.
        assert!(v.get("completed_depth_turns").is_none());
        assert!(v.get("stop_reason").is_none());
    }

    #[test]
    fn depth_diagnostics_variant_keeps_decisions_identical_and_consistent() {
        use splendor_agent::DecisionContext;

        let (state, setup) = FullState::new(GameConfig {
            player_count: 2,
            seed: 20260908,
            ..Default::default()
        })
        .unwrap();
        let viewer = PlayerId(0);
        let observation = state.observation(viewer);
        let actions: Vec<splendor_core::Action> = state.legal_actions();
        let history: Vec<splendor_core::VisibleEvent> =
            visible_events(&setup.events, Audience::Player(viewer));
        let history_ref: &'static [splendor_core::VisibleEvent] =
            Box::leak(history.into_boxed_slice());
        let obs_hash = observation_hash(&observation).clone();

        let cfg = RootDeterminizationConfigV1 {
            sample_seed: 20260703,
            sample_count: 4,
            continuation_search: SearchConfigV1 {
                max_depth_turns: 2,
                max_nodes: 2000,
            },
        };
        cfg.validate().unwrap();

        let mut plain = DeterminizationAgentPolicyV1::new(cfg).unwrap();
        let mut diag = DeterminizationAgentPolicyV1::new(cfg).unwrap().with_depth_diagnostics();

        let mut rng_a = StableRng::new(11);
        let mut rng_b = StableRng::new(11);
        let meta = |game_id: &str, request_id: u64| PublicRequestMeta {
            game_id: game_id.to_owned(),
            recipient_seat: PlayerId(0),
            request_id,
            observation_hash: obs_hash.clone(),
        };

        let action_plain = plain
            .choose_action(DecisionContext {
                observation: observation.clone(),
                visible_history: history_ref,
                legal_actions: &actions,
                meta: meta("s1-test", 1),
                rng: &mut rng_a,
            })
            .unwrap();
        let action_diag = diag
            .choose_action(DecisionContext {
                observation,
                visible_history: history_ref,
                legal_actions: &actions,
                meta: meta("s1-test", 1),
                rng: &mut rng_b,
            })
            .unwrap();
        assert_eq!(action_plain, action_diag, "diagnostics must not change the action");

        let t = diag.last_telemetry().expect("telemetry recorded");
        assert!(t.depth_diagnostics.is_some(), "diagnostics present when enabled");
        assert!(plain.last_telemetry().unwrap().depth_diagnostics.is_none());
        let d = t.depth_diagnostics.as_ref().unwrap();
        // Consistency: histogram sums == stop sums == non-terminal continuations.
        let hist_total: u64 = d.depth_histogram.iter().sum();
        assert_eq!(
            hist_total,
            d.stop_depth_limit_reached + d.stop_node_budget_reached,
            "histogram and stop-reason totals must agree"
        );
        assert_eq!(hist_total, t.stats.continuation_searches);
        // Hard completion definition consistency: depth==2 <=> DepthLimitReached
        // only binds the TOP depth bin; here we assert the structural invariant
        // that budget-stopped continuations never carry the top depth.
        if d.depth_histogram.len() == 3 {
            assert_eq!(
                d.depth_histogram[2], d.stop_depth_limit_reached,
                "top-depth bin must equal DepthLimitReached count"
            );
        }
        // Serialized sidecar keeps the field optional (absent when None).
        let s0 = serde_json::to_string(
            &PerDecisionStatsV1::from(plain.last_telemetry().unwrap()),
        )
        .unwrap();
        assert!(!s0.contains("depth_diagnostics"), "absent when disabled: {s0}");
        let s1 = serde_json::to_string(&PerDecisionStatsV1::from(t)).unwrap();
        assert!(s1.contains("depth_diagnostics"), "present when enabled: {s1}");
    }

    fn config() -> RootDeterminizationConfigV1 {
        RootDeterminizationConfigV1 {
            sample_seed: 17,
            sample_count: 1,
            continuation_search: SearchConfigV1 {
                max_depth_turns: 1,
                max_nodes: 100,
            },
        }
    }

    #[test]
    fn live_policy_matches_replay_neutral_player_view_analysis() {
        let (state, setup) = FullState::new(GameConfig {
            player_count: 2,
            seed: 42,
            ..Default::default()
        })
        .unwrap();
        let viewer = PlayerId(0);
        let observation = state.observation(viewer);
        let history = visible_events(&setup.events, Audience::Player(viewer));
        let legal = state.legal_actions();
        let expected = analyze_player_view_v1(Ruleset::base_v1(), &observation, &history, config())
            .unwrap()
            .result()
            .action;
        let mut rng = StableRng::new(999);
        let context = DecisionContext {
            observation: observation.clone(),
            visible_history: &history,
            legal_actions: &legal,
            meta: PublicRequestMeta {
                game_id: "live-policy-test".to_string(),
                recipient_seat: viewer,
                request_id: 1,
                observation_hash: observation_hash(&observation),
            },
            rng: &mut rng,
        };

        let actual = DeterminizationAgentPolicyV1::new(config())
            .unwrap()
            .choose_action(context)
            .unwrap();
        assert_eq!(actual, expected);
    }

    #[test]
    fn mismatched_server_legal_actions_fail_closed() {
        let (state, setup) = FullState::new(GameConfig::default()).unwrap();
        let viewer = PlayerId(0);
        let observation = state.observation(viewer);
        let history = visible_events(&setup.events, Audience::Player(viewer));
        let legal = [Action::Pass];
        let mut rng = StableRng::new(0);
        let context = DecisionContext {
            observation: observation.clone(),
            visible_history: &history,
            legal_actions: &legal,
            meta: PublicRequestMeta {
                game_id: "bad-legal-set".to_string(),
                recipient_seat: viewer,
                request_id: 1,
                observation_hash: observation_hash(&observation),
            },
            rng: &mut rng,
        };

        let error = DeterminizationAgentPolicyV1::new(config())
            .unwrap()
            .choose_action(context)
            .unwrap_err();
        assert!(matches!(
            error,
            DeterminizationAgentError::LegalActionSetMismatch
        ));
    }
}
