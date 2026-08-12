# Model evaluation contract

The project uses two different kinds of measurement. They must not be called
the same thing in conclusions, command summaries, or milestone verdicts.

## Offline validation: diagnostic only

An offline validation partition answers whether optimization generalizes to
held-out samples from the same data-generating process. Depending on the route,
the target can be:

- M17: the frozen M07 teacher's chosen action and terminal outcome;
- M18A: Neural ISMCTS visit distribution and terminal outcome;
- M18B: held-out distributional TD targets.

Policy top-1, NLL/cross-entropy, Value MSE, mean TD error, and checkpoint
selection scores are therefore **fit diagnostics**. They can select an epoch or
find broken training, but they do not prove a move is uniquely correct and
cannot promote a checkpoint. Equivalent multi-turn strategies may disagree on
one action while having similar playing strength; conversely, teacher imitation
can reproduce the teacher's mistakes.

Training commands print these metrics under `offline_validation`. Existing v1
JSON report schemas retain their `validation` field for artifact compatibility,
but now carry a mandatory semantic declaration in new runs:

```json
{
  "metric_semantics": {
    "validation_kind": "offline_..._fit",
    "diagnostic_only": true,
    "strength_authority": "arena_rating_or_promotion_gate"
  }
}
```

## Playing strength: prospective games only

Strength claims come from the actual engine and strict Arena process boundary:

```text
frozen checkpoint + exact runtime command
→ predeclared game seeds + both seat rotations
→ completed/aborted match records + verified replays
→ rating report or frozen promotion gate
```

The small eight-game M17/M18 screens are prospective rejection evidence, not
formal promotion evidence. The M19 round robin is a provisional pool ranking
because it used only one seed per pair. A promotion changes the champion only
when the exact candidate clears the separately frozen paired gate; offline
metrics never enter that verdict.

## Required reporting language

- Say `offline fit improved`, not `model became stronger`, for loss/top-1/MSE.
- Say `Arena screen/league result` for wins, losses, Elo, and aborts.
- Say `promoted` only when a frozen promotion report says so.
- A failed offline metric may reject a training candidate before expensive
  games; a passed offline metric only authorizes prospective play, never
  promotion.
