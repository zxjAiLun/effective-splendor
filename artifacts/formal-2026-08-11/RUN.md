# Formal M09/M10 Evaluation Run — 2026-08-11

## Execution identity

- Repository commit: `176526f794ebf7768bbad884f2fa31b79529fd9f`
- Branch: `main`
- Build: `cargo build --locked --release -p splendor-cli`
- Rust: `rustc 1.94.1 (e408947bf 2026-03-25)`
- Cargo: `cargo 1.94.1 (29ea6fb6a 2026-03-24)`
- Host: `x86_64-pc-windows-msvc`
- OS: Windows 11 64-bit, version `10.0.26200`
- `Cargo.lock` SHA-256: `1d6968c120c39c837c2df88bf08d7a6595e04403336203c532d36f26c71bb22e`
- Release `splendor.exe` SHA-256: `4be8bb62fe243bbcfd1a5a648781681f673bea9bc290cd8b45324ff63e489bd2`

The absolute `target\release` directory was prepended to `PATH` during both
evaluations so every literal `program: "splendor"` command in the frozen plan
resolved to the release binary identified above.

## M09 formal calibration

Command:

```powershell
target\release\splendor.exe eval `
  --plan benchmarks\m09-competitive-eval-v1.plan.json `
  --out-dir artifacts\formal-2026-08-11\m09-calibration

target\release\splendor.exe promotion-gate `
  --plan benchmarks\m09-competitive-eval-v1.plan.json `
  --eval-report artifacts\formal-2026-08-11\m09-calibration\eval-report.json `
  --gate benchmarks\m09-competitive-eval-v1.gate.json `
  --out artifacts\formal-2026-08-11\m09-calibration\promotion-report.json
```

Execution result:

- Evaluation exit: `0`
- Promotion gate exit: `2` (valid policy rejection, not a fatal error)
- Elapsed evaluation time: approximately 47 seconds
- Reports/replays: 64/64 reports, 64/64 replays
- Completed seed blocks: 32/32
- Aborted matches: 0
- Candidate faults: 0
- Candidate: `determinization-s4-d1-n2000-v1`
- Champion: `heuristic-v1`
- Candidate wins/ties/losses: 15/0/49
- Candidate score: 2343 bps (23.43%)
- 95% one-sided confidence lower bound: 177 bps (1.77%)
- Decision: `reject`
- Failed check: `pairwise_lower_bound_meets_threshold`

Bindings:

- Semantic evaluation plan hash: `95b3c89c56f6411b6ce697ae7e15980ef3089045d33df826780d5c44590a26f5`
- Semantic promotion gate hash: `8224cfc0e3022f20334b40483e458854c5bccfcb3ca0c48200cc35586c86efdb`
- Frozen input plan file SHA-256: `9b149d5009125f39af42d86dce056afab5ed6997b58cf42aaa068fc08eae722e`
- Frozen input gate file SHA-256: `42de3d5f22bbeeaad0bfb498e6f6a4a5bab320564b9aa95444249d4c5c144fba`
- Executed `plan.json` SHA-256: `d26e325799c9cee5559f36d05587a30065dfc5e75fea778a097fec64822a45ec`
- `eval-report.json` SHA-256: `700fa938a1d581a92c489c8999f89c8b191b6ae51f3d9a01887afbf5562d2fec`
- `promotion-report.json` SHA-256: `2f1a445a59ddefd316cc6cc32922f55ec63b883f2438c6805cc7e6534e9994e3`

Interpretation: the run completed cleanly, but the frozen determinization
candidate did not pass the calibrated strength gate against the heuristic
baseline. This is a strength rejection, not an infrastructure failure.

## M10 formal promotion

Commands:

```powershell
target\release\splendor.exe league-plan `
  --manifest benchmarks\m10-ismcts-v1.league.json `
  --out artifacts\formal-2026-08-11\m10-plan.json

target\release\splendor.exe eval `
  --plan artifacts\formal-2026-08-11\m10-plan.json `
  --out-dir artifacts\formal-2026-08-11\m10-evaluation

target\release\splendor.exe promotion-gate `
  --plan artifacts\formal-2026-08-11\m10-plan.json `
  --eval-report artifacts\formal-2026-08-11\m10-evaluation\eval-report.json `
  --gate benchmarks\m10-ismcts-v1.gate.json `
  --out artifacts\formal-2026-08-11\m10-evaluation\promotion-report.json
```

Execution result:

- Evaluation exit: `0`
- Promotion gate exit: `2` (valid policy rejection, not a fatal error)
- Elapsed evaluation time: approximately 95 seconds
- Reports/replays: 64/64 reports, 64/64 replays
- Completed seed blocks: 32/32
- Aborted matches: 0
- Candidate faults: 0
- Candidate: `ismcts-s64-d2-x100000000-v1`
- Champion: `determinization-s4-d1-n2000-v1`
- Candidate wins/ties/losses: 29/0/35
- Candidate score: 4531 bps (45.31%)
- 95% one-sided confidence lower bound: 2365 bps (23.65%)
- Decision: `reject`
- Failed check: `pairwise_lower_bound_meets_threshold`

Bindings:

- Semantic evaluation plan hash: `1975ff93701b04a3187cc86839b3d9d7dfd34960790a54919dfcae70922c3aeb`
- Semantic promotion gate hash: `3b270e7290b07f882bea8d6a75d6c8127234004ef63e05d92ee2c21637a0198b`
- Frozen league file SHA-256: `d4b983ec6ebf26f3924789c0dad4c4cb32192031a1f396e8e51af7709b53aad3`
- Frozen gate file SHA-256: `3f203f1442a50a77f1f5adfcbde4c8b0790f0152f6e330c6517d4f0b15335bf4`
- Generated and executed plan file SHA-256: `5539bd5b1bac857a8681a08593aac39366f58c72a218f9205818383a61cc0f84`
- `eval-report.json` SHA-256: `8a403ee799573809db236243551d54bd24d75a4c3a39e81b3581e17c8093dae3`
- `promotion-report.json` SHA-256: `cd9cfd34e9f4e90c0d0e5f190543301fd88a35421e8b8b03660c24883058e096`

Interpretation: the run completed cleanly, but ISMCTS did not meet the frozen
promotion threshold against root determinization. It remains a candidate and
must not replace the champion on the basis of this run.

## Integrity checks performed

- Both evaluations contain canonical match indices `000000..000063`.
- Every match has one Arena report and one replay.
- Both `eval-report.json` files contain 64 records.
- Each `plan-hash.txt` equals the evaluation plan hash bound by its promotion report.
- No temporary publish files remain.
- Evaluation stdout and stderr logs are empty for both runs.
- Artifact root at verification time: 269 files, 3,815,314 bytes.

The evaluation commands themselves did not generate a training dataset. After
the formal M10 evaluation had been archived unchanged, its complete 64-match
corpus was used to derive the first formal M11 dataset.

## M11 first formal dataset

- Dataset id: `formal-m10-evaluation-2026-08-11-v1`
- Source: all M10 canonical match indices `0..63`; no outcome filtering
- Replay sources: 64 completed, 0 aborted
- Examples: 3,956 total
- `root-determinization-v1`: 1,978 examples
- `observation-history-ismcts-v1`: 1,978 examples
- League manifest hash: `3a8d3d779f0dc56d9284546af5a4552c2b3b15e3cdcd7a2e4908f3d006714ca6`
- Evaluation plan hash: `1975ff93701b04a3187cc86839b3d9d7dfd34960790a54919dfcae70922c3aeb`
- Evaluation report hash: `bfe37aa341207f4e020a18bfb4abeaced9c7ef64b69e65cb3cf7960b70a172f8`
- Dataset file SHA-256: `2adfb8cb827fa0f2ac1be94d375e5449d3b89ed5ce4e679b9d438fd93af8fc03`
- Dataset semantic hash v1: `d60d2ddb6054bf32cd0c915f75d85bacdb62158414370e8e73efcfd65c7a7720`
- Independent validation: `PASS`

The M10 promotion report remains archived as the valid `reject` conclusion but
is not an input to the M11 dataset provenance chain. Full validation evidence
and the rerunnable verifier are in `m11-dataset/VALIDATION.md` and
`m11-dataset/verify-formal-dataset.mjs`.
