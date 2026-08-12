# M18A Neural-ISMCTS Self-Play v1

Terminology: the game-held-out `validation` metrics below measure fit to search
visit distributions and terminal outcomes. They are diagnostic checkpoint
selection metrics, not move correctness, Elo, or promotion evidence. Playing
strength is measured only by the prospective Arena screen/league.

M18A implements the project's first own-model reinforcement-learning loop. It
is AlphaZero-like, but because Splendor contains hidden information it uses the
accepted information-set search boundary rather than pretending the game is
perfect-information chess or Go.

The loop is:

1. a persistent PyTorch evaluator loads the M17 Entity Mixer on CUDA;
2. Rust builds each actor's `Observation + VisibleEvent` information set;
3. canonical neural ISMCTS produces root priors, visits and per-seat values;
4. early actions are sampled from visits and later actions use the visit winner;
5. terminal ranks are attached after the game;
6. CUDA fine-tuning uses root visit distributions as soft policy targets and
   terminal outcomes as viewer-relative value targets.

The Python evaluator never receives `FullState`, deck order, replay seed or an
opponent's hidden reserve. Rust owns rules, hidden-world sampling and PUCT. The
Python service only receives `Observation` and the canonical legal-action list.
Its viewer-relative value output is translated back to absolute seat order
before search backup.

## Commands

```powershell
cargo run -p splendor-cli -- collect-gpu-self-play `
  --config benchmarks/m18a-neural-self-play-smoke-v1.config.json `
  --out local-artifacts/m18a-neural-self-play-smoke-v1/dataset.json

$env:PYTHONPATH = "training/m17_gpu"
python -m splendor_gpu.self_play_train `
  --self-play local-artifacts/m18a-neural-self-play-smoke-v1/dataset.json `
  --config benchmarks/m18a-neural-self-play-smoke-v1.training.json `
  --catalog apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json `
  --out-dir local-artifacts/m18a-neural-self-play-smoke-v1/trained
```

`agent-gpu-neural-ismcts` exposes the exact checkpoint-bound runtime to Arena
and M16 rating. It starts one persistent inference subprocess per agent rather
than reloading the GPU checkpoint per model evaluation.

## First frozen smoke result

The frozen two-game collector completed 2/2 games and produced 122 decision
examples. The self-play content hash is
`495d5a9d708abfe5dd3078ce4b8f6c4d837d4011b2b0b47012c942d3f4237c6b`.
CUDA fine-tuning produced checkpoint
`4e504da4a9018d52d0e18d1bb69cebafe46803a559074b676c5c711b706182ca`.

The checkpoint learned the small search corpus (73.2% validation visit-top1),
but the prospective M16 screen was only 2-6 against heuristic, Official Elo
1405, with 8/8 completed and zero aborts. Therefore the first M18A candidate is
**rejected**, not promoted. The implementation and experiment remain useful:
the complete self-play route is now executable, deterministic and measurable;
larger iterations can be evaluated without changing the evidence contract.

Generated datasets, checkpoints, reports and replays stay under ignored
`local-artifacts/` and are not pushed to GitHub. The compact result identity is
`benchmarks/m18a-neural-self-play-smoke-v1.result.json`.
