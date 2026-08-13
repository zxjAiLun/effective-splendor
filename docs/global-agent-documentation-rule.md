# Global Project Documentation Rule

Use this rule for all non-trivial work in a software, research, data, model,
game, tooling, or product repository. Its purpose is to preserve project
continuity across agents and sessions without turning documentation into an
unstructured activity log.

Project-specific instructions always take precedence over this global default.
Adapt to an existing repository convention instead of creating a competing
documentation system.

## 1. Core documentation model

Maintain two complementary documentation layers:

```text
Project handoff/status document
    = compact current truth, milestone index, durable constraints, evidence
      pointers, known limitations, and next authorized work

Milestone/round documents under docs/
    = one living design-to-result record for each coherent major development
      round, including initial design, iterations, evidence, and final decision
```

Machine-verifiable truth remains in code, tests, schemas, configuration, result
manifests, and artifacts. Documentation explains meaning, history, and project
decisions; it must not replace executable evidence.

## 2. Repository discovery before work

Before planning or changing a repository, inspect:

1. applicable system/developer/user instructions;
2. root and nested `AGENTS.md` files or equivalent repository rules;
3. an existing `handoff.md`, `PROJECT_STATUS.md`, `docs/project-status.md`,
   roadmap, changelog, ADRs, and active milestone documents;
4. the current branch, `HEAD`, remote relationship, worktree status, and recent
   commits;
5. relevant code, tests, configs, tracked result identities, and local
   artifacts.

Do not treat a document or previous agent delivery report as proof of current
code or external state. Verify drift-prone facts when verification is cheap.

Do not overwrite or duplicate a repository's established documentation model.
Map this rule onto the existing names and structure.

## 3. Default structure when a repository has none

If the repository has no equivalent documentation system and the current task
is a major round, establish:

```text
handoff.md
docs/
  m01-<short-purpose>.md
```

Default policy:

- `handoff.md` is tracked so that other clones and agents share project state.
- `docs/mNN-*.md` milestone documents are tracked with implementation changes.
- large/generated/sensitive artifacts are not committed unless the repository
  explicitly authorizes them; record their location and identity instead.

If project instructions require the handoff to remain local-only, preserve that
policy, add an explicit ignore rule, and verify it before every commit. Never
silently change a handoff from tracked to local-only or vice versa.

If the repository uses `R07`, `phase-03`, dated release names, ADRs, or another
stable sequence instead of `MNN`, retain its established naming system.

## 4. When documentation maintenance is required

Apply the full workflow to non-trivial work that changes one or more of:

- architecture, subsystem ownership, or a durable interface;
- product behavior or an important user workflow;
- security, privacy, information, compatibility, or publication boundaries;
- data schemas, model/training contracts, migrations, or provenance;
- a milestone implementation, formal evaluation, release, or promotion gate;
- an independently reviewed defect or repair series;
- the project's current status, known limitations, or next-step order;
- a material experiment, including a valid negative result.

Do not create a milestone document for:

- a trivial typo or formatting fix;
- a one-line mechanical change with no durable design implication;
- a read-only question or explanation;
- a routine dependency refresh that does not change behavior or policy.

For such small tasks, update an existing active milestone or changelog only if
the change materially affects project status.

## 5. Project handoff contract

The handoff is the project's current orientation page. It should be concise
enough to read at the beginning of every substantial task.

It must normally contain:

```markdown
# Project Handoff

## Current snapshot
- Last updated date/time and timezone
- Primary branch and verified HEAD
- Remote/worktree state when relevant
- Current project phase
- Latest accepted/frozen/released baseline
- Active milestone, candidate, or experiment
- Single next authorized milestone

## Documentation and publication policy
- Handoff path and tracked/local-only policy
- Milestone document naming convention
- Generated artifact policy
- Required update triggers

## Project objective and durable boundaries
- Product/research goal
- Security and information boundaries
- Compatibility and determinism requirements
- Frozen interfaces, baselines, or non-negotiable constraints

## Milestone status
| Milestone | Status | Strongest evidence | Remaining gate |

## Active round
- Problem and evidence
- Authorized scope
- Current implementation/evaluation state
- Open findings and decisions

## Formal artifact/evidence index
| Artifact | Status | Inputs/version | Location | Hash/result |

## Known limitations and explicit non-claims

## Next execution order

## Changelog
| Date | Commit/artifact | Change | Status impact |

## Maintenance checklist
```

Handoff maintenance rules:

1. Keep the current snapshot accurate; stale top-level status is a defect.
2. Keep one durable row per milestone, including rejected or superseded work.
3. Link to detailed milestone documents instead of copying all details.
4. Record exact commits, tags, config/result paths, hashes, and artifact paths
   when those facts exist.
5. Distinguish observed current state from proposed future work.
6. Update the next-step order when evidence invalidates the previous plan.
7. Append corrections or supersession notes; do not erase a historical result
   merely because the project later changed direction.
8. Do not record a future commit hash before the commit exists.

## 6. Milestone/round document contract

Create one living document for one coherent major question or development
round. A milestone may span multiple days, implementation commits, reviews,
repairs, and experiments while remaining one document.

Recommended naming:

```text
docs/mNN-short-purpose.md
```

Required outline:

````markdown
# MNN — Title

```ini
MILESTONE = MNN
STATUS = PROPOSED | DESIGNED | AUTHORIZED | IMPLEMENTED | VERIFIED | ACCEPTED | REJECTED | DEFERRED | BLOCKED
BASE_COMMIT = <verified existing commit>
FINAL_COMMIT = <fill only after it exists>
DATE_STARTED = YYYY-MM-DD
DATE_CLOSED = <fill when closed>
SCOPE = <one-sentence boundary>
```

## Problem and observed evidence

- What triggered this round?
- Which user reports, logs, replays, metrics, incidents, or prior results prove
  the problem exists?
- Which statements are facts and which are hypotheses?

## Initial design

- Intended architecture or product workflow
- Why this approach was selected
- Alternatives considered
- Expected tradeoffs and risks

Preserve the initial design as historical reasoning. Do not silently rewrite
it after implementation. Record later changes in the iteration log.

## Scope and non-goals

### In scope
- ...

### Out of scope / not authorized
- ...

## Contracts and invariants

- Security/privacy/information boundary
- Compatibility and migration boundary
- Determinism and provenance requirements
- Publication and artifact policy
- Interfaces or baselines that must remain unchanged

## Acceptance and rejection gates

Define gates before seeing formal results.

| Gate | Evidence source | Pass/reject condition | Meaning |
| --- | --- | --- | --- |

## Implementation plan

1. ...
2. ...

## Iteration log

### Iteration 1 — YYYY-MM-DD
- Change:
- Reason:
- Evidence:
- Outcome:
- Decision for the next iteration:

### Review/repair iteration — YYYY-MM-DD
- Finding and severity:
- Root cause:
- Fix-forward change:
- Regression evidence:

## Final implementation

- Components and files changed
- Runtime/data flow
- User-visible behavior
- Compatibility and migration impact

## Validation and evidence

```text
command: <exact command>
result: PASS/FAIL, exit code, counts, relevant output
```

- Commit/tag:
- Tracked configs/results:
- Local or external artifact paths:
- Content/semantic hashes:
- Independent review scope and findings:

## Result and decision

- What did the evidence establish?
- Which hypotheses were retained or rejected?
- Exact final status
- Whether a release, baseline, champion, or production state changed

## Known limitations and explicit non-claims

- What this round does not prove
- Remaining operational, statistical, product, or architectural limitations

## Next authorized gate

- Single next decision or milestone
- Preconditions
- Work that remains explicitly unauthorized
````

## 7. Milestone lifecycle

### At round start

1. Verify the actual repository baseline and evidence.
2. Create or update the milestone document.
3. Record the initial problem, design, hypotheses, scope, non-goals, contracts,
   artifact policy, and acceptance/rejection gates.
4. Update the handoff to mark the round `AUTHORIZED` or `IN PROGRESS`, but do
   not claim implementation or success.

### During development

1. Maintain the same milestone document rather than creating a diary file for
   every commit.
2. Append material design changes, failed approaches, review findings, scope
   changes, and evidence-driven decisions to the iteration log.
3. Preserve negative results and explain what they ruled out.
4. Do not modify frozen gates, seeds, thresholds, or labels after observing a
   formal result unless a new separately authorized experiment is created.
5. Keep generated artifacts within the repository's publication policy.

### At round completion

1. Reconcile documentation against actual code, tests, configs, and artifacts.
2. Record exact validation/evaluation commands and outcomes.
3. Record the final status, evidence anchors, known limitations, and next gate.
4. Update the handoff snapshot, milestone table, active/next work, artifact
   index, known limitations, and changelog.
5. Check links, status consistency, formatting, ignore/publication rules, and
   the Git diff.
6. Commit tracked milestone documentation with the implementation or repair.
7. Keep local-only handoff and non-publishable artifacts out of Git.

## 8. Controlled status vocabulary

Use status words only with the required evidence:

| Status | Required evidence | Must not be interpreted as |
| --- | --- | --- |
| `PROPOSED` | an idea was written down | authorization |
| `DESIGNED` | concrete design, scope, and gates exist | implementation |
| `AUTHORIZED` | explicit approval to perform the work | working code |
| `IN PROGRESS` | active work has begun | usable completion |
| `IMPLEMENTED` | code or artifact exists | verification or acceptance |
| `VERIFIED` / `PASS` | named checks were actually run and passed | independent acceptance |
| `REVIEWED` | explicit review occurred and findings are listed | zero findings unless stated |
| `ACCEPTED` / `FROZEN` | the declared acceptance gate passed | absence of future limitations |
| `REJECTED` / `NOT PROMOTED` | a valid experiment completed but failed its gate | infrastructure failure |
| `DEFERRED` | postponement and reopen conditions are recorded | cancellation |
| `BLOCKED` | named external input, authority, or state is required | merely difficult work |
| `SUPERSEDED` | a newer accepted contract replaced it | historical deletion |

Never compress design, implementation, testing, review, evaluation, and release
into the single word "done".

## 9. Evidence hierarchy and claim discipline

Prefer evidence in this order:

1. machine-verifiable tracked contract plus verified artifacts;
2. exact current-workspace command output;
3. independent review against actual code and evidence;
4. implementation author's delivery report;
5. plan, expectation, or intention.

When sources disagree, record the conflict and repair the contract. Do not pick
the most convenient narrative.

Always distinguish:

```text
planned work           != authorized work
implemented code       != verified behavior
smoke test             != formal evaluation
offline metric         != production/competitive quality
code review            != milestone acceptance
valid rejection        != execution failure
relative internal rank != external absolute quality
```

Use the strongest accurate claim and explicitly label weaker evidence.

## 10. Daily notes versus milestone documents

Do not create a new document merely because a new calendar day began.

Update the active milestone's iteration log when the day materially changes:

- design or architecture;
- a contract or invariant;
- a hypothesis or failed approach;
- formal evidence or acceptance status;
- known risks or next-step decisions.

Create a separate dated daily/incident/operation document only when the event
is independently meaningful, such as:

- a production incident and recovery;
- a long-running formal experiment or benchmark execution;
- a migration or release operation;
- a security/provenance repair;
- an investigation that spans multiple milestones.

Link the dated document from the active milestone and summarize its effect in
the handoff.

## 11. Publication and artifact rules

Before staging changes:

1. inspect `git status` and the exact staged diff;
2. verify whether the handoff is tracked or ignored;
3. exclude unrelated user changes;
4. exclude generated datasets, model weights, build outputs, credentials,
   personal paths, logs, and large artifacts unless explicitly authorized;
5. record local/external artifact identities and hashes in tracked compact
   manifests or docs when appropriate;
6. never publish a local-only document merely because it was updated as part
   of the lifecycle.

If artifact authenticity or provenance matters, bind the actual executed
configuration, inputs, seeds, deadlines, versions, and outputs—not just a human
label or runtime name.

## 12. Documentation consistency audit

Before declaring a round complete, verify:

- handoff current snapshot matches the repository and latest evidence;
- milestone status matches its actual gates;
- README/roadmap does not contradict handoff or milestone docs;
- tracked machine-readable results match narrative claims;
- exact commits/hashes exist and point to the stated content;
- rejected/superseded results remain discoverable;
- next authorized work is singular and unambiguous;
- no unverified future tense is presented as current fact;
- publication boundaries are respected.

If a conflict is found, fix the source of truth and add a correction note. Do
not silently rewrite history to make the documents appear consistent.

## 13. Anti-patterns

Avoid:

- copying an agent delivery report without checking the repository;
- writing `ACCEPTED`, `PASS`, or `PROMOTED` from implementation existence;
- deleting a failed milestone after later success;
- changing formal gates after seeing results;
- creating one disconnected doc per commit;
- leaving the initial design doc orphaned after implementation;
- committing large artifacts because a summary document mentions them;
- recording hashes or commits before they exist;
- maintaining contradictory status claims in multiple documents;
- using documentation updates as permission for unrelated code changes.

## 14. Completion report for agents

At the end of a material round, report:

```text
MILESTONE / ROUND
BASE COMMIT
FINAL COMMIT (only if created)
STATUS
TRACKED FILES CHANGED
LOCAL/EXTERNAL ARTIFACTS
VALIDATION COMMANDS AND RESULTS
FORMAL EVIDENCE OR REVIEW FINDINGS
KNOWN LIMITATIONS
NEXT AUTHORIZED GATE
PUBLICATION STATUS
```

The final report must remain consistent with the handoff, milestone document,
Git state, and actual evidence.

## 15. Project-level override block

A repository may add this block to its own `AGENTS.md` to specialize the global
rule:

```text
DOCUMENTATION_SYSTEM = two-layer
HANDOFF_PATH = handoff.md
HANDOFF_PUBLICATION = tracked | local-only
MILESTONE_PATTERN = docs/mNN-*.md
DAILY_OR_INCIDENT_PATTERN = docs/operations/YYYY-MM-DD-*.md
GENERATED_ARTIFACT_POLICY = ignored local directory | tracked | external store
PRIMARY_STATUS_VOCABULARY = default | project-specific extension
FORMAL_EVIDENCE_POLICY = project-specific contract
```

Only these project-specific values should normally change. The lifecycle,
status discipline, evidence hierarchy, history preservation, and consistency
audit remain the global default.
