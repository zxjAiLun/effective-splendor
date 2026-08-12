# M18B Distributional Double-DQN v1

M18B is the independent value-based branch of the 1v1 roadmap. It does not
reuse M18A's search-visit policy loss. The implementation uses:

- C51 categorical action-value distributions on 51 atoms in `[-1, 1]`;
- online-network action selection with target-network evaluation (Double-DQN);
- deterministic proportional prioritized replay;
- a frozen target network copied every 80 gradient steps;
- M17 Entity Mixer representation weights as initialization;
- viewer-relative, same-actor transitions with terminal rewards `+1/-1`.

For a player decision at ply `t`, the successor is that same player's next
decision, not the opponent's intervening observation. This keeps Q targets in
one viewer/action space. Non-terminal rewards are zero; the terminal result is
attached to the actor's final transition.

The frozen smoke config is
`benchmarks/m18b-rainbow-smoke-v1.training.json`. It trained on the deterministic
M18A two-game corpus (66 train and 56 validation transitions), using CUDA for
800 gradient steps. Checkpoint semantic hash:
`e7d1bd75d6270de3f54fbd4c1477d9df34fe7b8817bae4552adca670061d9ad6`.

The reported held-out cross-entropy and TD error measure offline fit to the
training target construction only. They select/debug a checkpoint; they are
not a strength gate. Win/loss/Elo evidence begins at the Arena screen below.

The strict Arena agent chooses the legal action with maximum expected value
under the learned distribution. Its prospective M16 screen completed 8/8 with
zero aborts but lost 1-7 to heuristic (Official Elo 1332). The first M18B
candidate is therefore **rejected**. This is a successful route validation,
not evidence that 122 decisions are enough for value-based RL strength.

Large checkpoints, rating reports and replays remain under ignored
`local-artifacts/`. The tracked identity is
`benchmarks/m18b-rainbow-smoke-v1.result.json`.
