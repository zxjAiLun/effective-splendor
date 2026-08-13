# Agent Documentation Contract

This repository uses a two-layer project record. Every agent that performs a
non-trivial design, implementation, evaluation, release, or review task must
maintain both layers when applicable.

## 1. Read before acting

Before planning or changing the project:

1. Read this file.
2. Read the root `handoff.md` when it exists.
3. Read the active milestone document under `docs/` and the architecture or
   contract documents it links to.
4. Verify the current branch, `HEAD`, worktree state, and relevant artifacts.

Do not treat documentation as proof of current code or external state. Verify
cheap, drift-prone facts directly.

## 2. The two documentation layers

### `handoff.md`: current project truth and navigation

`handoff.md` is the compact, continuously maintained project index. It answers:

- Where is the project now?
- What is implemented, verified, accepted, rejected, frozen, or blocked?
- What evidence anchors each milestone?
- What constraints and known limitations still apply?
- What is the next authorized step?

Update it after a milestone implementation, independent review, acceptance or
freeze, formal evaluation, important contract change, material failure, or
change to the next-step order. Keep historical evidence; append corrections
instead of silently rewriting an old result.

Repository-specific publication rule: the root `handoff.md` is local-only and
ignored. Never stage, commit, or push it. Verify this with
`git check-ignore -v handoff.md` before staging a completed round.

### `docs/mNN-*.md`: one living record per major round

Create or maintain one tracked document for each major milestone or coherent
development round. Use a stable name such as `docs/m24-gpu-review.md`.

The milestone document records the full reasoning arc:

1. original problem and observed evidence;
2. initial design, scope, non-goals, and acceptance gates;
3. implementation contract and information/security boundaries;
4. material iterations, failed attempts, deviations, and why they changed;
5. final implementation and exact validation evidence;
6. result, limitations, decision, and next authorized gate.

Do not create a new milestone document for every trivial commit. Small changes
belong in the active round's iteration log and the handoff changelog. Create a
standalone daily/incident document only when the work is independently useful
and cannot be understood as part of the active milestone.

## 3. Status vocabulary is evidence-bound

Use these states precisely:

- `PROPOSED` / `DESIGNED`: written plan only.
- `AUTHORIZED`: scope approved; implementation may start.
- `IMPLEMENTED`: code exists; this does not imply verification or acceptance.
- `VERIFIED` / `PASS`: named checks were actually run and passed.
- `REVIEWED`: an explicit review occurred; list findings and reviewer scope.
- `ACCEPTED` / `FROZEN`: the milestone's declared acceptance gate passed.
- `REJECTED` / `NOT PROMOTED`: a valid experiment completed but failed its gate.
- `DEFERRED`: intentionally postponed with a reopen condition.
- `BLOCKED`: cannot proceed without named external input or authority.

Never infer `PASS`, `ACCEPTED`, `PROMOTED`, or `COMPLETE` from code existence,
offline metrics, a smoke test, or an agent's delivery summary. Preserve valid
negative results; do not change seeds, gates, or labels after seeing outcomes.

## 4. Evidence and provenance rules

Documentation claims must point to the strongest available evidence:

- exact commit/tag when it exists;
- exact commands and exit status for validation;
- tracked config/result paths and content hashes for formal experiments;
- local artifact paths for generated datasets, checkpoints, logs, and replays;
- explicit distinction between implementation smoke, offline diagnostics,
  competitive measurement, independent review, and promotion/acceptance.

Never invent a future commit hash or record a command as run when it was not.
Machine-verifiable contracts belong in code/JSON/tests; docs explain their
meaning and decision history rather than replacing them.

## 5. Milestone lifecycle

At round start:

1. Create/update the milestone document with baseline commit, problem,
   evidence, scope, non-goals, invariants, plan, and frozen gates.
2. Update `handoff.md` only enough to mark the round authorized/in progress.

During development:

1. Record material decisions and deviations in an append-only iteration log.
2. Preserve failed experiments and explain what they ruled out.
3. Keep generated or sensitive artifacts within the repository's publication
   policy; do not publish them merely because their summary is tracked.

At round completion:

1. Reconcile the milestone document against actual code and artifacts.
2. Record validation commands/results, evidence hashes, findings, limitations,
   and the precise verdict.
3. Update the handoff snapshot, milestone table, next step, artifact index, and
   changelog.
4. Check links, status consistency, `git diff --check`, and publication rules.
5. Commit tracked milestone docs with the implementation. Keep local-only
   handoff and generated artifacts out of Git.

## 6. Required milestone document outline

Every new major-round document should normally contain:

```text
# MNN Title
Status / baseline / owner-date block
## Problem and evidence
## Initial design
## Scope and non-goals
## Contracts and invariants
## Implementation plan
## Iteration log
## Final implementation
## Validation and evidence
## Result and decision
## Known limitations
## Next authorized gate
```

See `docs/project-documentation-system.md` for reusable templates and examples.
