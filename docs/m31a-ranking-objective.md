# M31A — Objective-v2: Weighted Pairwise Logistic Ranking Auxiliary Loss

```ini
MILESTONE = M31A
STATUS = ACCEPTED / CLOSED / STOP_WEIGHTED_PAIRWISE_LOGISTIC_RANKING_ROUTE / NO_ARENA / NO_FURTHER_MODEL_TRAINING
BASE_COMMIT = 489592ef65306ea64e320f86915222955feebda7
SCOPE = Evaluate composite policy loss objective L = L_canonical_CE + 0.5 * L_weighted_pairwise_logistic on top of canonical D2 architecture (h192/b4, 59-dim exact action deltas, 953,476 parameters, 128 epochs) to test whether explicit pairwise teacher ranking margin breaks the student fit ceiling without sacrificing soft-target cross-entropy calibration.
DATASET = Canonical M25 dataset (256 games, 16,282 examples: 12,216 train / 4,066 val), 100,000 micros uniform floor.
TRAINING = COMPLETED (128 epochs in 110.3s, lr=3e-4 cosine, wd=1e-4, best epoch 13 selected strictly by validation canonical policy CE = 2.8375, excess CE = +0.3646, val Top-1 = 35.91%, impr = 798 bps).
OFFLINE_GATES = G1 Primary Gate FAIL (Val Top-1 35.91% < 45.00%, Val CE impr 798 bps < 1000 bps); Objective Signal Gate FAIL (Relative to Exp D2 baseline: Top-1 delta -2.51 pp < +3.0 pp, CE delta +0.0197 nats > +0.005 nats degradation ceiling).
FIT_ATTRIBUTION = Adding the weighted pairwise logistic ranking objective on top of canonical soft CE yielded strictly inferior results compared to the pure soft-CE D2 baseline: Val CE degraded by +0.0197 nats (2.8177 -> 2.8375) and Val Top-1 dropped by -2.51 pp (38.42% -> 35.91%). The model peaked early (best epoch 13) and showed continuous validation CE degradation in later epochs under this formulation.
DECISION = STOP_WEIGHTED_PAIRWISE_LOGISTIC_RANKING_ROUTE
ARENA = NOT_AUTHORIZED
MODEL_TRAINING = NO_FURTHER_MODEL_TRAINING
PROMOTION = NONE
CHAMPION = M07
```

## Problem and evidence

Across the M25 recovery and downstream probes:
1. **Experiment D2** proved that injecting 23-dim exact post-action state transition deltas into action embeddings yielded a major fit improvement (Val CE 2.8879 $\to$ 2.8177, Top-1 31.87% $\to$ 38.42%).
2. **Experiment B & E** ruled out model width scaling (0.95M $\to$ 2.61M parameters yielded $\le 0.0020\text{ nats}$ CE reduction).
3. **M29A-v1/v2** ruled out dynamic action-to-entity cross-attention pooling (gain $\le 0.0043\text{ nats}$).
4. **M30A** proved that 4-sample teacher search targets already have 76.56% repeat agreement (median JSD 0.0019 nats), and 4-to-16 sample scaling increased agreement by only +3.12 pp, ruling out teacher sampling variance as the dominant ceiling cause.
