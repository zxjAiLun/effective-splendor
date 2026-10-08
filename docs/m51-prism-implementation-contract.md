# Prism v0.1 implementation interface (M51)

This is the P1/P2 implementation contract under the approved goal. No Aran code is modified.

## Rust encoded interface

`crates/splendor-prism/src/encoding.rs` exports:
- `pub const ENTITY_DIM: usize = 96; pub const ACTION_DIM: usize = 80;`
- `pub const OBS_SCHEMA: &str = "prism-observation-v1"; pub const ACTION_SCHEMA: &str = "prism-action-v1";`
- `#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)] #[serde(deny_unknown_fields)] pub struct EncodedState { pub entities: Vec<Vec<f32>>, pub actions: Vec<Vec<f32>>, pub targets: Vec<i32> }`
- `pub fn encode(observation: &Observation, history: &[VisibleEvent], actions: &[Action]) -> Result<EncodedState,String>`
- `pub fn catalog_fingerprint() -> String` uses core `ruleset_fingerprint(&Ruleset::base_v1()).to_string()` (the actual classic ruleset API).
- `impl EncodedState { pub fn validate(&self) -> Result<(),String> }` checks widths/finiteness/nonempty, ≤128 entities, ≤4096 actions, targets -1 or valid entity index, correct target kinds if possible. All no-target actions use -1.

The encoder owns the detailed documented numeric field layout within 96/80 widths. Encode only player-visible information; seven distinct action kinds, full target gather, take and return distinct. Retain visible purchased identities as entities with static attributes and one stable catalog identity numeric channel if otherwise ambiguous. Preserve known/unknown/empty semantics, phase/endgame/turn order, color relations, actual deterministic visible delta incl ownership changes. Use player-visible history only for accurate Main count / public reserve tier knowledge, not raw event serialization, IDs, seeds or hashes. Core mechanics remain authoritative. Entity order may be canonical but model must be permutation equivariant with remapped targets. Entity type features should make global/player/card/noble/bank/unknown distinguishable. Maximum counts fit128; no fixed market flatten consumed by model.

## Exact model numerical contract

All linear layers are ordinary `y = x @ W.T + bias`. Export weight matrices row-major [out,in], float32. Hidden H=128; no dropout; ReLU; LayerNorm eps1e-5 population variance. No learning of game rules. Entity input already includes typed/player-to-card/noble/color relations.

1. `h = relu(encoder(entities))`, encoder 96→128.
2. Two blocks i=0,1: `g = masked_mean(h)`; `u = relu(blocks.i.local(h) + blocks.i.context(g))`; `h = blocks.i.norm(h + u)`. Both linears128→128, LayerNorm128. Padding excluded from means and attention.
3. Final `g = masked_mean(h)`. `t_a = h[targets[a]]` if >=0 else all zeros.
4. `q = relu(action(actions) + target(t_a) + global_action(g))`. action80→128; target/global_action128→128. Bias is applied even to zero no-target input, consistently.
5. `k = key(h)`, `v = entity_value(h)`, both128→128.
6. `p_a = softmax(q_a @ k.T / sqrt(128))` over valid entities only; `r_a = p_a @ v`.
7. `logits = policy_out(relu(policy_hidden(concat(q,r,g))))`, hidden384→128, out128→1.
8. `value_logit = value_out(relu(value_hidden(g)))`, hidden128→128, out128→1. Report value sigmoid(value_logit); training uses BCEWithLogits.

State dict exact keys: `encoder.{weight,bias}`, `blocks.{0,1}.{local,context,norm}.{weight,bias}`, `action`, `target`, `global_action`, `key`, `entity_value`, `policy_hidden`, `policy_out`, `value_hidden`, `value_out` each with `.weight/.bias`.

Weights JSON: `{ "format":"prism-weights-v1", "observation_schema":"prism-observation-v1", "action_schema":"prism-action-v1", "catalog_fingerprint":STRING, "hidden_dim":128, "num_blocks":2, "entity_dim":96, "action_dim":80, "state_dict": {KEY:{"shape":[...],"data":[float,...]}} }`. No other mandatory fields. Tensor identity/metadata kept in companion manifest. Loader denies unknown fields, wrong keys/shapes/nonfinite values and wrong catalog/schema. Never silently substitutes model.

Rust inference `inference.rs`: `pub struct PrismWeights`; `pub struct Prediction { pub logits:Vec<f32>, pub value:f32 }` serde output; `PrismWeights::load(path:&Path)->Result<Self,String>`, `::from_json(text:&str)->Result<Self,String>`, `::predict(&self, input:&EncodedState)->Result<Prediction,String>`. Use efficient row-major loops; bounded dimensions. No dependence on learning/Aran. Numerical parity atol1e-4 rtol1e-4 against PyTorch float32.

## Dataset format

Root manifest `format=prism-dataset-v1`, schemas, catalog_fingerprint, entity_dim96, action_dim80, source records (seed,path,sha256,split,steps), and splits train/val with `games`, `states`, `entities`, `actions`, file hashes.
Each split stores contiguous little-endian raw arrays:
- `entities.f32`: [total_entities,96]
- `entity_offsets.u64`: [states+1]
- `actions.f32`: [total_actions,80]
- `action_offsets.u64`: [states+1]
- `targets.i32`: [total_actions], local-to-state entity target indices, -1 absent
- `chosen.u32`: [states], local action index
- `outcomes.f32`: [states], 1/0.5/0 real result
- `rows.jsonl`: per-state seed, ply, actor, observation hash and chosen semantic action, strictly provenance (not model input)
`parity.jsonl` at dataset root holds deterministic 32 real validation states: each line `{input:EncodedState, seed,ply,actor}`. Additional boundary fixtures exported separately by CLI tests/probe.

## Training

`python -m training.prism.train --config benchmarks/m51-prism-v01.config.json` (optional `--device` for engineering tiny tests only). Training config keys under `training`: data_dir, out_dir, epochs20, batch_size64, accumulation_steps2, lr0.0003, weight_decay0.0001, seed51000001, value_weight0.5. One AdamW run, constant lr (no scheduler), gradient clip1.0, float32 no AMP/TF32, CPU threads2, all teacher actions CE+0.5 outcome BCE. Save init.pt, checkpoint-last.pt with optimizer/RNG for exact same-config resume, best_model.pt, weights.json, history.json and training-summary.json. Epoch1..20 min validation mean CE+0.5BCE earliest ties. Mask padded actions, no filtering winners. Saved manifest binds dataset+config hashes. Best vs init must differ. Dry test runs only temp tiny datasets, never formal output. Validate schema, counts, offsets and labels; no .jsonl provenance field used as input. Deterministic shuffle by seed+epoch supports resumed epoch boundary. Expose importable model, collate and prediction/export for parity tests.

No delegate launches formal training or matches. Parent handles config/seed reservation/data extraction/build/integration, formal execution and docs. Ownership: encoder delegate encoding.rs only (+ dedicated encoder tests file); inference delegate inference.rs only; Python delegate training/prism/** only. Parent owns Cargo/lib/CLI/scripts/config/docs. Do not edit others' paths.
