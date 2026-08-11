# M13 Neural-Guided ISMCTS v1

M13 connects the accepted M12 Policy/Value checkpoint to a new live search
candidate. It does not modify the frozen M10 ISMCTS implementation, replace the
determinization champion, or claim promotion from an implementation smoke.

## Frozen candidate

The checked-in candidate inputs are:

- `benchmarks/m13-neural-ismcts-v1.league.json`
- `benchmarks/m13-neural-ismcts-v1.gate.json`
- M12 semantic checkpoint hash
  `108d32fa2d0d2499ead38e99b23e42cd905644358a76d5adb7392ad43401b462`
- 64 simulations, depth 2, PUCT exploration constant 1.500
- 32 new game seeds with both seat rotations, for 64 scheduled matches

The checkpoint file and all generated Arena/evaluation artifacts stay under
ignored `local-artifacts/`; only their semantic identities and frozen
evaluation inputs/results belong in Git.

## Search contract

Each simulation samples an M07-valid determinization of the root information
set. Nodes are shared by acting-player `Observation` plus that player's visible
simulated history, never by `FullState` identity.

On node expansion the M12 model receives only the acting player's Observation
and the canonical legal-action list. Its outputs are used as follows:

1. legal-action Policy probabilities become fixed-point priors;
2. the 2–4 player Value vector bootstraps an unvisited edge or depth leaf;
3. exact terminal dense ranks replace model values at terminal states;
4. each edge backs up one value sum per player;
5. the acting player's component drives deterministic integer PUCT-like
   selection; the root action is chosen by visits, mean value, then prior.

The model checkpoint semantic hash is validated before any hidden-state sample.
The live agent also requires the canonical search-root actions to exactly match
the server-certified legal actions and fails closed on disagreement.

## Determinism and limits

There are no wall-clock reads, threads, or search-time floating-point
comparisons. Model probabilities and values are quantized to millionths before
tree selection and backup. Exact reproducibility is scoped to the same build,
checkpoint, configuration, information set, and supported platform semantics.

The first M12 checkpoint was trained only on the formal two-player M10 corpus.
The representation and search shapes support 2–4 players, but M13 v1's formal
competitive gate is intentionally two-player. No 3/4-player strength claim is
made.

## Promotion boundary

A completed local Arena smoke proves only that the checkpoint-bound process can
handshake, choose certified legal actions, and finish a game. Promotion still
requires the entire frozen 64-match evaluation, zero aborts, zero candidate
faults, and the unchanged one-sided 95% lower-bound gate. Until that evidence is
complete, M13 remains a candidate and the determinization champion remains in
place.

## Formal 64-match result

The frozen evaluation was executed once on 2026-08-11 from implementation
commit `ddb02aaa88776a4e6ba0157a94cfed7d7dec22bb`, using the accepted M12
checkpoint and the checked-in manifest/gate without modification.

```text
completed matches:             64 / 64
completed seed blocks:         32 / 32
candidate wins / ties / losses: 12 / 0 / 52
candidate score:               1875 bps
one-sided 95% lower bound:        0 bps
one-sided 95% upper bound:     4041 bps
aborted matches:                  0
candidate faults:                 0
decision:                    reject
```

Every Arena report/replay pair was present, every replay independently
verified, match indices were exactly `0..63`, and no temporary artifact
remained. The only failed gate check was
`pairwise_lower_bound_meets_threshold`; all reliability and deadline checks
passed.

The local evidence is bound by:

```text
league manifest semantic SHA-256 d43a15ce20bde451b8bb41b389a71eb136d1b4c07e7908e543c52bcf90841190
gate semantic SHA-256            039d3ce342d6f1bdcc462b3e6c3cfde98f289391372a48be76b31edda6f97f2c
evaluation plan semantic SHA-256 d6193b40d5c4c95475c0c206bd074f1b79e72f73a87dc35a58a362dc00fcf207
evaluation plan file SHA-256     c183d0c8ddd03fbc8c2bb4953e41de4eacbfc0fb8567e9bf0197ff5199dc655a
evaluation report file SHA-256   207b911ec1249ff98fce6dd51eab06cec5882c3d2564e222199edc71629dc141
promotion report file SHA-256    e144143f07211d1062febf05912751c6ffb2d0e9dd65f716817477f2a3d95da5
```

Generated evidence remains under ignored
`local-artifacts/m13-formal-2026-08-11/` and is not committed. This `reject` is
the final result for the frozen M13 v1 candidate; it must not trigger a seed,
checkpoint, budget, PUCT constant, timeout, or gate change followed by a
result-oriented rerun. The determinization champion remains in place.
