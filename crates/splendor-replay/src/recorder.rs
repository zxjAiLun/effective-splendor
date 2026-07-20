use splendor_core::{
    full_state_hash, ruleset_fingerprint, Action, FullState, GameConfig, PlayerId, StepResult,
    ENGINE_VERSION,
};

use crate::error::{ReplayError, ReplayResult};
use crate::format::{
    ReplayGameResultV1, ReplayHash, ReplayRulesetV1, ReplayStepV1, ReplayV1, REPLAY_FORMAT,
    REPLAY_VERSION,
};

/// Wraps a `FullState` and records every applied action into a `ReplayV1`.
///
/// The recorder never exposes a mutable handle to its `FullState`, so the
/// recorded document is guaranteed to reflect exactly the actions that drove
/// the engine.
pub struct ReplayRecorder {
    state: FullState,
    initial_state_hash: ReplayHash,
    ruleset: ReplayRulesetV1,
    ruleset_fingerprint: ReplayHash,
    player_count: u8,
    seed: u64,
    steps: Vec<ReplayStepV1>,
    next_ply: u32,
}

fn hash_of(state: &FullState) -> ReplayHash {
    // The engine hash is always 64 lowercase hex; construction cannot fail.
    ReplayHash::from_hash_str(full_state_hash(state).as_str())
        .expect("engine full_state_hash is always valid hex")
}

impl ReplayRecorder {
    pub fn new(config: GameConfig) -> ReplayResult<Self> {
        let seed = config.seed;
        let (state, _) = FullState::new(config)?;
        let ruleset = ReplayRulesetV1::from_ruleset(&state.ruleset);
        let ruleset_fingerprint =
            ReplayHash::from_hash_str(ruleset_fingerprint(&state.ruleset).as_str())
                .expect("ruleset fingerprint is always valid hex");
        let initial_state_hash = hash_of(&state);
        let player_count = state.player_count();
        Ok(Self {
            state,
            initial_state_hash,
            ruleset,
            ruleset_fingerprint,
            player_count,
            seed,
            steps: Vec::new(),
            next_ply: 0,
        })
    }

    pub fn state(&self) -> &FullState {
        &self.state
    }

    pub fn legal_actions(&self) -> Vec<Action> {
        self.state.legal_actions()
    }

    pub fn apply(&mut self, action: Action) -> ReplayResult<StepResult> {
        let ply = self.next_ply;
        let actor = self.state.current_player;
        let before = hash_of(&self.state);

        let step = self.state.apply(action)?;

        let after = hash_of(&self.state);
        self.steps.push(ReplayStepV1 {
            ply,
            actor,
            action,
            state_hash_before: before,
            state_hash_after: after,
        });
        self.next_ply += 1;
        Ok(step)
    }

    /// Finish recording. Only valid once the game is terminal.
    pub fn finish(self) -> ReplayResult<(FullState, ReplayV1)> {
        if !self.state.is_terminal() {
            return Err(ReplayError::ReplayNotTerminal);
        }
        let result = self
            .state
            .result
            .as_ref()
            .ok_or(ReplayError::ReplayNotTerminal)?;

        let final_state_hash = hash_of(&self.state);
        let replay = ReplayV1 {
            format: REPLAY_FORMAT.to_string(),
            version: REPLAY_VERSION,
            engine_version: ENGINE_VERSION.to_string(),
            ruleset: self.ruleset,
            ruleset_fingerprint: self.ruleset_fingerprint,
            player_count: self.player_count,
            seed: self.seed,
            initial_state_hash: self.initial_state_hash,
            steps: self.steps,
            final_state_hash,
            result: ReplayGameResultV1::from_result(result),
        };
        Ok((self.state, replay))
    }
}

impl ReplayRecorder {
    pub fn current_player(&self) -> PlayerId {
        self.state.current_player
    }

    pub fn is_terminal(&self) -> bool {
        self.state.is_terminal()
    }
}

/// Deterministically record a complete random game.
///
/// `seed` drives the engine setup (deck shuffle); `action_seed` drives the
/// pseudo-random legal-action selection. The same inputs always produce a
/// byte-identical replay, which is what the golden fixtures rely on.
pub fn record_random_game(
    player_count: u8,
    seed: u64,
    action_seed: u64,
) -> ReplayResult<(FullState, ReplayV1)> {
    let mut recorder = ReplayRecorder::new(GameConfig {
        player_count,
        seed,
        ..Default::default()
    })?;

    // Small, self-contained xorshift64* PRNG: keeps replay generation free of a
    // direct `rand` dependency and stable regardless of `rand` version changes.
    let mut rng_state = action_seed ^ 0x9E37_79B9_7F4A_7C15;
    let mut next = || {
        let mut x = rng_state;
        x ^= x >> 12;
        x ^= x << 25;
        x ^= x >> 27;
        rng_state = x;
        x.wrapping_mul(0x2545_F491_4F6C_DD1D)
    };

    while !recorder.is_terminal() {
        let actions = recorder.legal_actions();
        debug_assert!(!actions.is_empty(), "non-terminal state must have actions");
        let index = (next() % actions.len() as u64) as usize;
        recorder.apply(actions[index])?;
    }

    recorder.finish()
}
