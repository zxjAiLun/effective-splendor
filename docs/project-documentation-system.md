# Project Documentation System

This playbook defines a reusable documentation workflow for long-running,
agent-assisted software and research projects. It deliberately separates the
project's current truth from the detailed history of each development round.

The system was extracted from the workflow used by Effective Splendor:

```text
handoff.md             current project truth + milestone index + next step
docs/mNN-*.md          design-to-result record for one coherent round
code / tests / JSON    machine-verifiable implementation and evidence
local artifacts        large, generated, sensitive, or reproducible outputs
```

The documents support the evidence; they do not replace it.

## Why two layers

A single large progress document eventually becomes hard to navigate, while a
folder of isolated design notes cannot answer "what is true now?". The two
layers solve different problems:

| Layer | Optimized for | Must answer |
| --- | --- | --- |
| Project handoff | fast orientation and continuity | current status, evidence anchors, constraints, next authorized work |
| Milestone document | reasoning and auditability | why the round existed, how it changed, what was built, what evidence decided it |

The handoff links outward to details. Each milestone document links back to
the project state or subsequent gate it affected.

## Layer A: project handoff

Use `handoff.md`, `PROJECT_STATUS.md`, or `docs/project-status.md`. Decide and
record whether it is tracked or local-only. Never leave the publication policy
implicit.

Recommended outline:

```markdown
# Project Handoff

## Current snapshot
- Last updated:
- Branch / HEAD / remote state:
- Current phase:
- Latest accepted or frozen baseline:
- Active candidate/experiment:
- Next authorized milestone:

## Maintenance contract
- Events that require an update
- Publication and sensitive-data rules
- Status vocabulary

## Project goal and durable boundaries
- Product/research objective
- Security and information boundaries
- Compatibility and determinism constraints
- Frozen interfaces or baselines

## Milestone status
| Milestone | Status | Evidence | Remaining gate |

## Active round
- Problem
- Authorized scope
- Current evidence
- Open decisions

## Formal artifact index
| Artifact | Status | Inputs | Location | Hash/result |

## Known limitations and non-claims

## Next execution order

## Changelog
| Date | Commit/artifact | Change | Status impact |

## Update checklist
```

### Handoff writing rules

1. Keep the top snapshot short and current.
2. Keep one row per milestone even after it is superseded or rejected.
3. Link to evidence instead of copying every implementation detail.
4. Record negative results as durable project knowledge.
5. Separate current state from intended future work.
6. Update the next-step order whenever a result invalidates the old plan.
7. Append corrections and supersession notes; do not erase the historical
   decision that was valid at the time.

## Layer B: milestone/round document

Use one document for one coherent question, not one document per commit. A
milestone may span several days and several repair commits while remaining the
same round.

Recommended file name:

```text
docs/mNN-short-purpose.md
```

If the project does not use milestone numbers, substitute a stable series such
as `R07`, `phase-03`, or `2026-08-auth-redesign`.

### Reusable milestone template

````markdown
# MNN — Title

```ini
MILESTONE = MNN
STATUS = DESIGNED | AUTHORIZED | IMPLEMENTED | VERIFIED | ACCEPTED | REJECTED
BASE_COMMIT = <verified commit>
FINAL_COMMIT = <fill only after it exists>
SCOPE = <one sentence>
```

## Problem and evidence

- What observable problem triggered this round?
- Which logs, replays, metrics, user reports, or prior results demonstrate it?
- What is known, and what is still only a hypothesis?

## Initial design

- Intended architecture or product flow
- Why this approach was selected
- Alternatives considered
- Expected risks and tradeoffs

Preserve this section as the original design record. Later changes go into the
iteration log instead of silently rewriting the initial reasoning.

## Scope and non-goals

### In scope
- ...

### Not in scope / not authorized
- ...

## Contracts and invariants

- Security/information boundary
- Compatibility boundary
- Determinism/provenance contract
- Publication/artifact policy
- Interfaces that must remain unchanged

## Acceptance and rejection gates

Define these before seeing the result:

| Gate | Evidence | Pass condition | Meaning |
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
- Decision for next iteration:

### Repair/review iteration
- Finding severity and exact scope
- Fix-forward change
- Regression evidence

## Final implementation

- Components/files changed
- Runtime/data flow
- User-visible behavior
- Compatibility and migration notes

## Validation and evidence

```text
command: ...
result: PASS/FAIL, exit code, counts
```

- Commit/tag:
- Config/result files:
- Artifact paths:
- Content/semantic hashes:
- Independent review findings:

Distinguish explicitly:

```text
implementation smoke != formal evaluation
offline metric        != production/competitive strength
reviewed code         != accepted milestone
valid rejection       != execution failure
```

## Result and decision

- What did the evidence establish?
- What hypothesis was rejected or retained?
- Exact final status
- Whether any baseline/champion/release changed

## Known limitations and non-claims

- What this round does not prove
- Remaining operational, statistical, or architectural limits

## Next authorized gate

- The single next decision or milestone
- Preconditions
- Work that remains explicitly unauthorized
````

## Lifecycle workflow

### 1. Start the round

Read the handoff, active docs, code, and artifacts. Verify branch/HEAD rather
than trusting an old note. Create the milestone document before or alongside
the first material implementation, with:

- verified baseline;
- observed evidence;
- hypotheses;
- scope and non-goals;
- frozen acceptance/rejection gates;
- expected artifact policy.

The initial design is a timestamped reasoning record, not a prediction that
must later be made to look correct.

### 2. Develop and iterate

Update the same milestone document when a material decision changes. Record:

- failed approaches that affect future decisions;
- defects found during review;
- changes to architecture or scope and who authorized them;
- why a result requires a new iteration rather than retroactive gate changes.

Routine refactors and mechanical fixes do not need diary entries unless they
alter the contract or explain a later result.

### 3. Close the round

Re-read the document against the actual repository. Replace future-tense
claims with verified implementation facts, but keep the original design and
iteration history visible. Add exact test/evaluation evidence, artifact hashes,
known limitations, and the final decision.

Then update the handoff:

```text
current snapshot
milestone status row
active/next round
artifact index
known limitations
append-only changelog
```

Tracked code and milestone docs should normally land in the same commit or
review series. A local-only handoff must remain untracked.

## Status model

Use a small controlled vocabulary across all projects:

| Status | Required evidence | Does not mean |
| --- | --- | --- |
| `PROPOSED` | written idea | authorized work |
| `DESIGNED` | concrete contract and gates | implemented |
| `AUTHORIZED` | explicit approval | working code |
| `IMPLEMENTED` | code/artifact exists | tests passed |
| `VERIFIED` / `PASS` | named checks actually passed | independently accepted |
| `REVIEWED` | explicit review and finding list | zero findings unless stated |
| `ACCEPTED` / `FROZEN` | declared acceptance gate passed | future perfection |
| `REJECTED` / `NOT PROMOTED` | valid run failed its gate | broken infrastructure |
| `DEFERRED` | reopen conditions recorded | cancelled |
| `BLOCKED` | named external dependency/authority missing | merely difficult |

This vocabulary prevents a common agent failure: compressing design,
implementation, testing, review, and release into a single word, "done".

## Evidence hierarchy

Prefer claims in this order:

1. machine-verifiable tracked contract plus verified artifacts;
2. exact command output from the current workspace;
3. independent review against actual code;
4. implementation author's delivery report;
5. plan or intention.

When evidence conflicts, record the conflict and repair the contract; do not
select the most convenient narrative.

## Daily notes versus milestone documents

Do not generate documentation noise merely because another day began.

Create/update the active milestone document when the day materially changes:

- the design;
- a contract or invariant;
- a failed hypothesis;
- an acceptance result;
- a new risk or next-step decision.

Create a separate daily/incident note only for independently meaningful events,
such as a production incident, long-running formal experiment, migration, or
release operation. Link that note from the milestone document and summarize
its status impact in the handoff.

## Anti-patterns

Avoid these documentation failures:

- **Delivery-report mirroring:** copying an agent summary without checking code.
- **Status inflation:** writing `ACCEPTED` when only a smoke test passed.
- **History laundering:** deleting a rejection after a later model succeeds.
- **Gate shopping:** changing seeds or thresholds after seeing a result.
- **Artifact dumping:** committing large datasets/checkpoints because the docs
  mention them.
- **Future hashes:** recording a commit/hash before it exists.
- **Parallel truths:** handoff says one status while the milestone doc says
  another.
- **Diary overload:** one document per commit with no coherent question.
- **Orphan design:** a design doc never updated with the actual result.

## Portable `AGENTS.md` rule

Copy the root `AGENTS.md` from this repository into another project and change
only the repository-specific subsection:

```text
HANDOFF_PATH = handoff.md | PROJECT_STATUS.md | docs/project-status.md
HANDOFF_PUBLICATION = tracked | local-only
MILESTONE_PATTERN = docs/mNN-*.md
GENERATED_ARTIFACT_POLICY = tracked | ignored local-artifacts | external store
STATUS_VOCABULARY = project default
```

After adapting those values, the lifecycle, templates, evidence hierarchy, and
status rules can remain unchanged across repositories.
