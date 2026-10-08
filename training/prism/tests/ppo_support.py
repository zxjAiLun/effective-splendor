"""Synthetic mathematical fixtures ONLY: these are not generated game replays."""
import copy

import numpy as np

from training.prism.ppo.contract import PPOConfig

CATALOG = "prism-test-catalog-only"


def config(**changes):
    settings = dict(lr=1e-4, weight_decay=0.0, clip_epsilon=0.2, value_weight=0.5,
                    style_value_weight=0.0, entropy_weight=0.01, gae_lambda=0.95,
                    style_beta=0.0, passes=2, minibatch_size=2, max_grad_norm=1.0,
                    target_kl=1.0, logp_tolerance=1e-6, value_tolerance=1e-6,
                    normalize_advantage=True)
    settings.update(changes)
    return PPOConfig(**settings)


def encoded(index=0, actions=3):
    rng = np.random.default_rng(index)
    return {"entities": rng.normal(0, 0.1, (2, 96)).astype(np.float32).tolist(),
            "actions": rng.normal(0, 0.1, (actions, 80)).astype(np.float32).tolist(),
            "targets": [-1] * actions}


def request(behavior, *, job="synthetic-job", actor=0, index=0, ply=None, actions=3):
    return {"format": "prism-ppo-request-v1", "behavior_id": behavior.identity,
            "job_id": job, "game_id": "synthetic-context", "actor": actor,
            "request_id": 2 * index + 1 if ply is None else ply + 1, "decision_index": index,
            "catalog_fingerprint": behavior.catalog, "input": encoded(index, actions)}


def game(behavior, *, job="synthetic-job", actor=0, count=3, ranks=None, actions=3):
    rows = []
    for i in range(count):
        req = request(behavior, job=job, actor=actor, index=i, actions=actions)
        response = behavior.sample(req)
        legal = [{"type": "synthetic_action", "index": n} for n in range(actions)]
        rows.append({"format": "prism-ppo-decision-v1", "request": req, "response": response,
                     "observation": {"viewer": actor, "synthetic": True}, "visible_history": [],
                     "legal_actions": legal, "chosen_action": legal[response["chosen_index"]]})
    ranks = [0, 1] if ranks is None else ranks
    return {"format": "prism-ppo-audit-v1", "behavior_id": behavior.identity, "job_id": job,
            "actor": actor, "game_id": "synthetic-context", "catalog_fingerprint": behavior.catalog,
            "replay_sha256": "1" * 64, "sidecar_sha256": "2" * 64, "terminal": True,
            "result": {"scores": [15, 14], "ranks": ranks,
                       "winners": [i for i, rank in enumerate(ranks) if rank == 0], "reason": "prestige_threshold"},
            "decisions": rows}


def run_config(parent_hash):
    return {"format": "prism-ppo-run-v1", "run_id": "synthetic-engineering-only", "catalog_fingerprint": CATALOG,
            "parent_sha256": parent_hash, "auditor_sha256": "0" * 64,
            "device": "cpu", "cpu_threads": 2, "seed": 123,
            "ppo": config().to_dict(), "opponents": {"synthetic-opponent": "3" * 64},
            "budget": {"max_cycles": 2, "max_optimizer_steps": 30, "max_update_attempts": 40,
                       "max_jobs": 4, "max_attempts": 6, "max_decisions": 100,
                       "max_job_decisions": 10, "max_run_seconds": 600.0, "max_storage_bytes": 1024**3}}


def schedule(job="synthetic-job"):
    return [{"job_id": job, "actor": 0, "opponent_id": "synthetic-opponent", "environment_seed": 0}]
