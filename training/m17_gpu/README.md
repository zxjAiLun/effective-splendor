# M17 GPU Policy-Value v1

This package is the first native GPU learning route in Effective Splendor. It
is supervised warm start, not RL and not an external-teacher distillation
contract. It consumes the existing provenance-bound player-view dataset and
learns from the frozen internal M07 teacher trajectories.

Two models share the exact same inputs, targets, split, optimizer, and legal
action scorer:

- `flat_resmlp`: fixed entity slots are flattened into a residual MLP control;
- `entity_mixer`: shared entity encoders, masked gated pooling, and residual
  mixing preserve object structure without using Transformer self-attention.

The v1 Value head is explicitly 1v1 and viewer-relative: `[self, opponent]`.
Search adapters must map that vector back to absolute Arena seats at the call
boundary; the checkpoint cannot be mistaken for the older 2–4 seat M12 vector.

Training uses CUDA when the frozen config says `cuda`; it fails rather than
silently falling back to CPU. Large datasets, reports, and checkpoints are
written under ignored `local-artifacts/`.

```powershell
python -m splendor_gpu.train `
  --dataset ../../local-artifacts/m15b-teacher-data-v2/dataset.json `
  --config ../../benchmarks/m17-gpu-supervised-warmstart-v1.config.json `
  --out-dir ../../local-artifacts/m17-gpu-supervised-warmstart-v1
```

An emitted registry fragment can be merged into a later M19 registry. The
runtime program is a normal Arena NDJSON agent:

```powershell
python training/m17_gpu/agent_entry.py `
  --checkpoint checkpoint.pt `
  --checkpoint-hash <file-sha256> `
  --device cpu
```

CPU inference is the default formal Arena choice because each Arena match
starts a fresh process; using CUDA for short single-match inference would pay
driver/context startup repeatedly without changing model semantics.

`checkpoint_hash` is a domain-separated semantic SHA-256 over canonical
metadata plus every named tensor's dtype, shape, and bytes. The training report
also records the ordinary `.pt` file SHA-256, but the M16 registry uses the
semantic hash so PyTorch zip container metadata is not part of model identity.
