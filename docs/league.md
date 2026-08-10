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

## Verified dataset build

The replay-list input is:

```json
{
  "format": "effective-splendor-dataset-replay-list",
  "version": 1,
  "dataset_id": "example-v1",
  "replays": [
    {
      "source_id": "game-000001",
      "path": "game-000001.replay.json",
      "report": "game-000001.report.json"
    }
  ]
}
```

Relative paths are resolved from the replay-list file. Build with:

```text
splendor build-dataset \
  --manifest league.json \
  --replays replay-list.json \
  --out dataset.json
```

Before emitting any example, the builder:

1. strictly re-executes the complete replay once, including every before/after
   state hash and the terminal result;
2. recomputes the Arena seed commitment from game id, replay seed, player
   count, and ruleset fingerprint;
3. binds report/replay engine, ruleset, fingerprint, player count, completed
   plies, final hash, and outcome;
4. maps every reported seat's runtime identity to exactly one manifest agent;
5. rejects aborted reports, missing identities, duplicate seats, mismatched
   policy versions, tampered replays, or any partial binding.

The output contains one replay provenance record plus one decision example per
ply. Every example contains only the acting player's `Observation`, canonical
legal actions, chosen action, observation / visible-history / information-set
hashes, and final score/rank targets. Referee `FullState`, full-state hashes,
deck order, replay seed, and opponent blind identities are not serialized into
training examples.

The replay document hash is the content-addressed link back to the referee
artifact that retains the seed and full audit chain. Dataset consumers must
archive the referenced report/replay artifacts; the player-view dataset alone
is intentionally not a referee replay.

`training_dataset_hash_v1` and `league_manifest_hash_v1` use separate SHA-256
domains over strict canonical struct serialization. Outputs are atomically
created and never overwritten. Any failed input leaves no dataset artifact.

## Learning boundary

M11 produces traceable supervised policy choices and multi-player final
score/rank targets. It does not yet define policy indices, tensors,
checkpoints, training code, inference, or neural-guided search; those remain
M12/M13 work.
