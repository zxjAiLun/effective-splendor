# M11 league and player-view dataset v1

M11 adds the traceability layer required before policy/value training. It does
not train a model and it does not alter Arena, replay, rules, or M10 search
semantics.

## League manifest to evaluation plan

`LeagueManifestV1` records a lineup, exactly one champion, candidate /
historical / exploiter roles, policy and optional model versions, runtime
identities, fixed game seeds, and Arena deadlines. Generate the canonical M05
seat-rotated plan with:

```text
splendor league-plan --manifest league.json --out evaluation-plan.json
```

The manifest and generated plan are strictly parsed, versioned, deterministic,
and never overwrite an existing artifact. Each runtime `name@version` must be
unique within the lineup so a completed Arena seat can map to exactly one
league policy/model identity.

## Executed evaluation to verified dataset

Dataset construction consumes the output directory of the existing `eval`
driver, not free-standing report/replay paths:

```text
LeagueManifestV1
  -> deterministic EvaluationPlanV1
  -> eval execution / canonical EvaluationReportV1
  -> canonical match_index
  -> ArenaReportV1 + ReplayV1
  -> TrainingDatasetV1
```

The replay-list input is:

```json
{
  "format": "effective-splendor-dataset-replay-list",
  "version": 1,
  "dataset_id": "example-v1",
  "replays": [
    {
      "source_id": "game-000001",
      "match_index": 0
    }
  ]
}
```

Run the evaluation and build with:

```text
splendor eval --plan evaluation-plan.json --out-dir eval-output

splendor build-dataset \
  --manifest league.json \
  --evaluation-dir eval-output \
  --replays replay-list.json \
  --out dataset.json
```

`--evaluation-dir` must contain the evaluator's `plan.json`,
`eval-report.json`, and `matches/match-NNNNNN.{report,replay}.json` layout.
Match artifact paths are derived solely from `match_index`; the replay list
cannot substitute arbitrary report/replay paths.

Before emitting any example, the builder:

1. derives the expected evaluation plan from the league manifest and requires
   its hash to equal the executed `plan.json` hash; this binds literal program,
   argv, seeds, and deadlines;
2. recomputes `aggregate(plan, eval-report.records)` and requires byte-model
   equality with `eval-report.json`, rejecting a non-canonical or mismatched
   execution attestation;
3. expands the canonical schedule and binds each source `match_index` to its
   exact game id, seed index, rotation, seat-to-agent mapping, and scheduled
   commands;
4. requires the Arena outcome to equal that evaluation record, then strictly
   re-executes the complete replay once, including every before/after
   state hash and the terminal result;
5. recomputes the Arena seed commitment from game id, replay seed, player
   count, and ruleset fingerprint;
6. binds report/replay engine, ruleset, fingerprint, player count, completed
   plies, final hash, and outcome;
7. checks every seat's runtime identity against the agent scheduled at that
   seat, rather than using runtime identity alone to infer a policy config;
8. rejects aborted reports, missing identities, duplicate match indices,
   command/config mismatches, tampered replays, or any partial binding.

Consequently a manifest declaring ISMCTS `simulations=64/depth=2` cannot label
an evaluation executed with `16/1`, even though both processes declare the
same runtime `name@version`: their evaluation-plan hashes differ.

The output contains one replay provenance record plus one decision example per
ply. Every example contains only the acting player's `Observation`, canonical
legal actions, chosen action, observation / visible-history / information-set
hashes, and final score/rank targets. Referee `FullState`, full-state hashes,
deck order, replay seed, and opponent blind identities are not serialized into
training examples.

The dataset records the league-manifest, evaluation-plan, evaluation-report,
per-match Arena-report, and replay-document hashes. These are the
content-addressed links back to artifacts that retain the executed command
schedule, seed, and full audit chain. Dataset consumers must archive those
artifacts; the player-view dataset alone is intentionally not a referee replay.

The manifest, dataset, evaluation-report document, and Arena-report document
hash helpers use separate SHA-256 domains over strict canonical struct
serialization. Outputs are atomically created and never overwritten. Any
failed input leaves no dataset artifact.
The hashes provide integrity/binding, not external authorship: signing and
remote artifact-store authenticity remain outside the v1 contract.

## Learning boundary

M11 produces traceable supervised policy choices and multi-player final
score/rank targets. It does not yet define policy indices, tensors,
checkpoints, training code, inference, or neural-guided search; those remain
M12/M13 work.
