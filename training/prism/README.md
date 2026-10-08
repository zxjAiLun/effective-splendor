# Prism v0.1 Python interface

Independent implementation of `docs/m51-prism-implementation-contract.md`.
Dependencies: Python 3.10+, NumPy, PyTorch 2.6+; pytest for tests. No other model
line is imported. Run commands from the repository root.

## Training and resume

```powershell
python -m training.prism.train --config benchmarks/m51-prism-v01.config.json
python -m training.prism.train --config benchmarks/m51-prism-v01.config.json --resume
python -m pytest -q training/prism/tests
```

The first two commands are formal execution entrypoints, not unit tests. Tests
create synthetic datasets/checkpoints only in pytest temporary directories and
exercise all 20 epochs with the frozen batch64/accumulation2 settings on CPU.
`--device cpu` is an explicit engineering-test override; use the same override
when resuming that test. Never change the formal config to recover a run.

Training uses all states (including losses/ties), CE + 0.5 outcome BCE, shared
value gradients, constant AdamW lr3e-4/wd1e-4, clipping1, float32, no AMP/TF32,
and two CPU threads. Batch accumulation is weighted by the actual number of
states, including incomplete final groups. Validation includes every state;
selection is the smallest full validation objective in epochs1..20, earliest
exact tie. Initialization cannot win selection.

`run_training(config_path, resume=False, device=None, stop_after_epoch=None)` is
the importable entrypoint in `training.prism.train`. `stop_after_epoch` creates
a deliberate epoch-boundary interruption without changing the config. Resume
requires identical config bytes, verified dataset hashes, initialization, and
runtime identity (device/override, PyTorch/NumPy/Python versions). It restores
model, optimizer, Python/NumPy/Torch/CUDA RNG, history and best tensors. Shuffle
is a separate deterministic NumPy permutation seeded by `seed + epoch`.
Exact reproducibility is for the same implementation/hardware/runtime, not
cross-version or cross-device runs. Interruptions before the first completed
epoch do not yet have a resumable last checkpoint.

Artifacts in `training.out_dir`:

- `init.pt`: epoch0 tensors, RNG, config/data identities.
- `checkpoint-last.pt`: atomic epoch commit containing `state_dict`, optimizer,
  RNG, full history, best tensors/epoch/loss and identity hashes. This is the
  authoritative resume source even if writing derived files was interrupted.
- `best_model.pt`: selected tensors under `state_dict` plus epoch/identities.
- `weights.json`, `weights.manifest.json`: strict Rust format and exact float32
  tensor/file hashes; export reloads and checks every tensor for exact equality.
- `history.json`, `training-summary.json`: full per-epoch train/validation metrics
  and completion status, selected epoch, init/best/last tensor identities.
- `config.json`, `run-manifest.json`: frozen config snapshot, effective settings,
  runtime and dataset split hashes (`splits[*].hashes[name]`). `config_sha256`
  always hashes the original input config bytes, not the formatted snapshot.
- `artifact-manifest.json`: artifact hashes including `training-summary.json`.

A fresh run refuses nonempty output. Best/export/summary artifacts are published
at completion or an intentional boundary stop; best tensors are preserved every
epoch inside the last checkpoint. A hard crash can leave older derived files;
resume rebuilds them. `.pt` loading uses pickle: load only trusted local files.

## Model, data, and parity APIs

```python
from training.prism import PrismModel, PrismDataset, collate, predict
from training.prism import export_weights, load_weights
from training.prism.export import load_checkpoint_model

model = PrismModel()  # exact named layers; no architecture options
batch = collate([encoded_state])
logits, value_logits = model.forward_batch(batch)
result = predict(model, encoded_state)  # {"logits": [...], "value": sigmoid(...)}

export_weights(model, "weights.json", catalog_fingerprint)
model = load_weights("weights.json", expected_catalog_fingerprint=catalog_fingerprint)
model, checkpoint = load_checkpoint_model(
    "best_model.pt", expected_catalog_fingerprint=catalog_fingerprint)
```

`EncodedState` contains exactly `entities[E,96]`, `actions[A,80]`, `targets[A]`.
Targets are local entity indices or -1. The batched forward signature is
`model(entities, actions, targets, entity_mask=None, action_mask=None)`; tensors
are float32 features, int64 targets, and bool masks with True meaning valid.
It returns policy logits `[B,A]` (padding = -inf) and **value logits** `[B]`.
Do not apply sigmoid before BCEWithLogits. `predict` accepts a single unpadded
state, rejects extra fields, and returns the Rust Prediction JSON shape.

`PrismDataset(data_dir, split="train", expected_catalog_fingerprint=None,
verify_hashes=True)` opens the seven little-endian raw arrays as read-only
memmaps. It validates schemas, source/split counts, hashes, byte sizes, monotonic
bounded offsets, target/chosen indices, finite features and outcomes0/0.5/1.
Keep the dataset open while using its state views; use a `with` block or `close()`.
Validation scans bounded chunks and training copies only a padded minibatch;
the only dataset-sized allocation is the integer shuffle permutation.
`rows.jsonl` is hashed/counted, never parsed into model input. Each dataset item
adds `chosen` and `outcome`; collate separates those into `chosen`/`outcomes`
labels, which `forward_batch` never passes to the network.

For external Rust/Python comparison, stream raw EncodedStates or dataset parity
wrappers `{input, seed, ply, actor}` into a new output file:

```powershell
python -m training.prism.parity --weights <weights.json> --input <parity.jsonl> --output <python-predictions.jsonl> --catalog-fingerprint <fingerprint>
python -m training.prism.export --checkpoint <best_model.pt> --output <weights.json> --catalog-fingerprint <fingerprint>
```

The fingerprint must be the expected Rust catalog identity, not an arbitrary
fallback. Compare all logits and the sigmoid value at atol1e-4/rtol1e-4.
The Python tests include an independent NumPy operator reference, but do not
substitute for real-state Rust parity, formal GPU training or competitive games.
