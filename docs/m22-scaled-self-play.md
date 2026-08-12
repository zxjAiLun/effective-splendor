# M22 scaled 1v1 self-play result

M22 is the first scale-up after the two-game M18A route smoke. It stays on the
project's own 1v1 AlphaZero-like information-set path: Neural ISMCTS produces
soft visit targets, terminal ranks train the Value head, and PyTorch runs on
the RTX 4060 GPU. No external teacher label is used.

The frozen collector expanded from 2 to 32 games and from 8 to 16 root
simulations. It completed all 32 games and produced 1,992 decision examples
(16.3 times the M18A smoke corpus). CUDA training selected epoch 16 and created
checkpoint `dc611f3d575f87e2b24221d633f8af55c98055357b05ccb822ef46ec0cb98c04`.
Its held-out visit top-1 was 88.59%; this is offline fit only.

## Prospective multi-seed strength result

The real strength test used four entirely new game seeds per pair, both seat
rotations, and four agents: heuristic, M07, old M18A, and new M22. All 48/48
matches completed with zero aborts and verified artifacts.

```text
rank  agent                       W-L    Official Elo
1     heuristic                  21-3       1778
2     M07 champion               15-9       1580
3     old M18A                    6-18      1321
4     new M22                     6-18      1321

M22 vs old M18A                   4-4
M22 vs heuristic                  1-7
M22 vs M07                        1-7
```

Therefore the larger corpus and stronger root search did not produce measured
improvement over M18A in this run. M22 is retained as a reproducible negative
result and is **not promoted**; M07 remains champion. This verdict comes from
Arena games, not from the improved offline metrics.

The large self-play JSON, checkpoint, training report, rating report, and all
48 match report/replay pairs remain local under
`local-artifacts/m22-scaled-self-play-v1/` and are ignored by Git. Only frozen
configs and the compact result identity are checked in.
