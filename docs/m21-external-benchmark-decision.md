# M21 External Benchmark Decision v1

M21 is complete as a decision gate. The external benchmark is **deferred**, not
cancelled and not silently authorized.

The decision was made only after both owned GPU/RL routes and the internal
championship completed:

- M17 Entity Mixer warm start: 1–7 versus heuristic, rejected.
- M18A neural-ISMCTS self-play: 2–6 versus heuristic, rejected.
- M18B distributional Double-DQN: 1–7 versus heuristic, rejected.
- M19 seven-agent round robin: 42/42 complete, zero abort, but only one seed
  per pair; M07 remains the frozen champion.
- M20 can now run a human against any registered internal checkpoint and hand
  the verified match directly to Replay Studio.

These results prove that the internal model, RL, rating and interaction routes
exist end to end. They do not yet provide a mature internally trained candidate
for a useful external comparison. Running an outside model now would mostly
measure the deliberately small first training corpora rather than decide which
internal architecture scales best.

The content-bound decision artifact is
`benchmarks/m21-external-benchmark-decision-v1.json`. It binds the tracked M17,
M18A, M18B and M19 result files by SHA-256 and records that no external model
was downloaded and no external match was run.

## Reopen gate

External benchmarking may be proposed again only after all of these hold:

1. A new internally trained checkpoint completes a frozen, multi-seed 1v1
   league with zero candidate faults.
2. That checkpoint is not rejected by the frozen internal promotion gate
   against the current champion.
3. The external runtime is translated into the existing player-view NDJSON
   protocol and receives no `FullState` or hidden information.
4. External weights/source revision, adapter argv, seeds and deadlines are
   content-bound before the first match.

Even after the gate reopens, the first authorization is benchmark-only.
External teacher labels, cross-entropy training or fine-tuning remain a
separate product decision.
