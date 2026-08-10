# M10 observation-history ISMCTS v1

M10 adds a deterministic, live player-view information-set tree-search
candidate without changing or deleting the frozen M07 root-determinization
baseline. The command is:

```text
splendor agent-ismcts \
  --sample-seed 20260810 \
  --simulations 64 \
  --max-depth-turns 2 \
  --exploration-bias 100000000
```

All four budgets are required and bounded. The policy receives only the Agent
SDK's `Observation`, cumulative player-visible `VisibleEvent` history,
server-certified legal actions, and public request metadata. It never accepts a
replay, raw game seed, `FullState`, full-state hash, or opponent blind-reserved
identity.

## Search contract

For simulation index `0..simulations`, M10:

1. samples one M07 determinization from the root `InformationSetV1`;
2. traverses a tree shared across all sampled worlds;
3. selects the action maximizing the acting player's MaxN utility component
   plus an integer confidence bonus;
4. expands the first unvisited edge and applies the deterministic M06 static
   evaluator at the leaf;
5. backs the complete utility vector up through every traversed edge.

There are no floating-point calculations, wall-clock reads, threads, or
unordered-map iteration decisions. Canonical legal-action order resolves all
remaining ties, so the same information set and config produce the same exact
result.

## Information-node identity

A tree node is keyed by only player-visible material:

```text
acting player's current Observation
+ that player's projected VisibleEvent history generated after the root
```

It is never keyed by `FullState` or a sampled-state hash. Therefore sampled
worlds that remain indistinguishable to the player share one edge policy,
while a visible reveal or a player's own blind reserve can split the node.
This directly removes the M07 behavior where every sampled world receives an
independent perfect-information continuation plan.

The v1 boundary is deliberate: the M07 sampler reconstructs a root world but
cannot reconstruct every opponent's private transcript before the root. M10 v1
therefore treats pre-root opponent history as an abstraction and preserves
perfect recall only for simulated events after the root. This is a
single-observer-style, observation-history ISMCTS candidate; it is not full
MO-ISMCTS, POMCP, a learned belief model, or a claim of optimal play.

## Frozen competitive input

`benchmarks/m10-ismcts-v1.league.json` schedules
`ismcts-s64-d2-x100000000-v1` against the M07
`determinization-s4-d1-n2000-v1` champion over 32 fixed seeds and both cyclic
seat rotations. `benchmarks/m10-ismcts-v1.gate.json` applies the unchanged M09
one-sided 95% promotion rule.

These files freeze an experiment, not its result. M10 is not promoted until
the evaluation is actually run and the resulting report passes the gate.
