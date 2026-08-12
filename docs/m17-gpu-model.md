# M17 Own GPU Policy-Value v1

M17 begins the project's own GPU model route. It intentionally comes before
self-play RL: first establish a trainable player-view representation, internal
supervised warm start, strict checkpoint identity, live Arena inference, and an
M16 rating entry. M18A/M18B may reuse the model code but must produce new
checkpoint identities and new evaluation evidence.

## Architecture choice

M17 does **not** require a Transformer.

| Model | Purpose | Structure |
| --- | --- | --- |
| Flat ResMLP | control | 31 fixed entity slots flattened with global features, four residual MLP blocks |
| Entity Mixer | candidate | shared entity encoder, masked gated pooling, global encoder, four residual mixing blocks |

Both models score the server-certified variable legal action list with a shared
action encoder and state/action interaction head. Neither enumerates moves or
receives `FullState`. Entity Mixer keeps cards, market slots, nobles, players,
public reserves, and the viewer's own private reserves as objects without the
cost and complexity of self-attention.

The v1 Value vector is `[self, opponent]`, explicitly viewer-relative and 1v1.
This avoids mixing relative input entities with absolute seat outputs. A future
search bridge must map it to absolute Arena seats at the boundary.

## Provenance and training

The frozen config is `benchmarks/m17-gpu-supervised-warmstart-v1.config.json`.
It binds the same M15B internal M07-teacher dataset used by later CPU controls:

```text
dataset hash = 3f8adcd4...f69b75
split        = seed_index % 4 == 0 validation
examples     = 2,942 train / 978 validation
device       = CUDA (fail closed; no silent CPU fallback)
optimizer    = AdamW
epochs       = 32
```

Every epoch is independently evaluated. The published local checkpoint is the
minimum of `validation Policy NLL + value_loss_weight * Value MSE`, not simply
the last epoch. This closes the overfitting behavior seen in the Flat control.

The semantic checkpoint hash covers canonical metadata and all named tensor
dtype/shape/bytes under a domain separator. The ordinary `.pt` SHA-256 remains
in the report as a transport-integrity field. The catalog has its own semantic
hash, and the Arena process rejects mismatches before hello.

## What M17 can claim

M17 completion requires:

- PyTorch/CUDA training on the user's GPU;
- both Flat and Entity Mixer under identical data/config;
- source-held-out Policy and Value comparisons against frozen baselines;
- strict checkpoint and catalog binding;
- a real completed Arena smoke with the model reading only player view;
- an M16-compatible registry fragment.

It does not promote a model based on offline metrics or a one-game smoke. A
prospective M16 screen is evidence for the exact frozen M17 checkpoint. Formal
championship/promotion stays in M19.
