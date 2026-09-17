# Splendor AI Learning Resources

Read/checked: 2026-09-17. Project baseline: `e081d550e273844daacca9858c8dd9a5e0784778`.

## Knowledge

### Foundations and original work

- [OpenAI Spinning Up: Key Concepts in RL](https://spinningup.openai.com/en/latest/spinningup/rl_intro.html). Full explanatory page retrieved; use for observation/state, policy, trajectories, rewards, return and value. Our Splendor examples specialize the definitions; they are not examples quoted from this page.
- [OpenAI Spinning Up: PPO](https://spinningup.openai.com/en/latest/algorithms/ppo.html). Explanatory page retrieved, including clipped objective and sign-dependent advantage cases. Use for lesson 10 arithmetic and why clipping is not a hard policy-distance guarantee. Its implementation defaults are NOT automatically project defaults.
- [Schulman et al., Proximal Policy Optimization Algorithms (2017)](https://arxiv.org/abs/1707.06347). Original algorithm attribution; abstract/metadata retrieved, not the entire PDF. Use alongside the detailed PPO explanation and project trainer.
- [Silver et al., Mastering Chess and Shogi by Self-Play (2017)](https://arxiv.org/abs/1712.01815). Original AlphaZero reference (abstract retrieved). Use to locate the search → self-play → policy/value learning family. Splendor M18A uses information-set search and is only AlphaZero-like, not a literal perfect-information implementation.
- [van Hasselt et al., Deep Reinforcement Learning with Double Q-learning](https://arxiv.org/abs/1509.06461). Original Double-DQN reference (abstract retrieved). Use for separating action selection from target evaluation; implementation details in M18B/rainbow.py.
- [Hessel et al., Rainbow](https://arxiv.org/abs/1710.02298). Original combination of DQN improvements (abstract retrieved). M18B implements its documented distributional Double-DQN/prioritized replay subset; no claim that every Rainbow feature exists.
- [Zaheer et al., Deep Sets](https://arxiv.org/abs/1703.06114). Original set-function representation reference (abstract retrieved). Use for permutation-invariant pooling intuition; it does not certify the adequacy of this project's particular entity encoder.

### Project primary sources

- [Architecture](docs/architecture.md), [search](docs/search.md), [determinization](docs/determinization.md), [ISMCTS](docs/ismcts.md). Source of the real information boundary, legal-action ownership and search architecture. Older architecture headings are historical; current research-reference status comes from the later S3 records.
- [Learning](docs/learning.md), [neural search](docs/neural-search.md), [M17 GPU](docs/m17-gpu-model.md). Use for representations, policy/value heads, checkpoint inference and runtime/training separation.
- [M18A self-play](docs/m18a-self-play.md), [M18B distributional Double-DQN](docs/m18b-rainbow.md), [M22 scaled self-play](docs/m22-scaled-self-play.md), [M24 training scale](docs/m24-training-scale-foundation.md). Real data routes and negative outcomes; implementation success is not promotion.
- [M39 PPO](docs/m39a-arena-driven-policy-value-rl.md) and [production trainer](training/m17_gpu/splendor_gpu/m39a_train.py). Use for actual behavior-policy evidence, same-viewer trajectories, GAE, clipped loss and the `M39A_NO_IMPROVEMENT` conclusion. The lesson's numerical example is illustrative, not a reported training batch.
- [M42S search gap](docs/m42s-search-gap-diagnostic.md), [M47S residual feasibility](docs/m47s-residual-target-feasibility-diagnostic.md), [M48A residual learnability](docs/m48a-static-prior-residual-learnability-gate.md). Use to distinguish n1 successor evaluation, teacher preference corrections, target availability and learnability.
- [S3 rollout](docs/s3-heuristic-policy-rollout.md), [S3 field calibration](docs/s3-field-calibration.md), [operational profile](docs/s3-operational-profile.md). Use for confirmed, bounded playing-strength evidence, primary development reference and separate product decisions.
- [Evaluation](docs/evaluation.md) and [documentation contract](AGENTS.md). Use for frozen gates and precise evidence-bound status vocabulary.
- [Research map](reference/research-map.html). Annotated links for the intervening M15–M48 and S0–S3 rounds, including representation, teacher targets, critic warm-start, counterfactual probes, ablations and product/replay infrastructure. This map is not a new verdict authority.

## Wisdom (Communities)

- [AI Stack Exchange](https://ai.stackexchange.com/). Optional conceptual Q&A: ask a narrowly scoped question with the Splendor assumptions stated. Community answers are discussion inputs, not evidence of project performance. No participation is required; the user has not expressed a community preference.
- Local learning loop: explain one replay decision or experiment conclusion back to the assistant, then challenge the explanation with a counterexample. Do not upload private replays/checkpoints to a community by default.

## Gaps

- No observed learner skill assessment yet. Answers, not generated pages, will determine pacing and learning records.
- Original-paper links above were checked at abstract level only; use the detailed official explanation and repository implementation for lesson equations/contracts. Full-paper study is a later optional activity.
- First pass groups related studies into conceptual lessons. It does not teach every historical hyperparameter, code path, product round or proof in depth. Request a focused follow-up lesson from the research map.
- Project source links are local files: HTML is directly readable, Markdown/Python/Rust may be shown as plain text or downloaded by the browser. They can always be opened in an editor.
