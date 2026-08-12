# M19 Internal Championship v1

M19 places every implemented 1v1 route on the same M16 rating scale:
heuristic, M07 determinization, M10 ISMCTS, M13 neural ISMCTS, M17 Entity
Mixer, M18A self-play neural ISMCTS and M18B Rainbow.

The first frozen championship used one game seed per pair and both seat
rotations: 21 pairs, 42 matches. All 42 completed, none aborted, and all 42
replays passed strict verification. The complete plan/report/replay tree stays
under ignored `local-artifacts/m19-internal-championship-v1/`.

| Rank | Agent | W-L | Official Elo |
| ---: | --- | ---: | ---: |
| 1 | Heuristic baseline | 11-1 | 1908 |
| 2 | M07 determinization champion | 8-4 | 1637 |
| 3 | M10 ISMCTS | 7-5 | 1567 |
| 4 | M17 Entity Mixer | 7-5 | 1567 |
| 5 | M18A self-play neural ISMCTS | 5-7 | 1429 |
| 6 | M13 neural ISMCTS | 2-10 | 1196 |
| 7 | M18B Rainbow | 2-10 | 1196 |

Every entry remains provisional because each pair has only two games. The
table is a development diagnostic, not a new promotion claim. Heuristic is a
baseline rather than a trainable/search promotion candidate, and neither new
RL checkpoint beat the frozen internal field. M07 therefore remains the
champion identity.

The tracked result binds plan hash
`4e6799c6c9af1f699d26dd17ef9b30e171388e3713fc4ef31d5411c005ba5949`
and rating report file SHA-256
`b0f591e442f8df2de96037681917e43fb9de203dc82296becd23b7b3006ca00c`.
