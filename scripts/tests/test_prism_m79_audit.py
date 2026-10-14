"""Synthetic ledger and batch-binding checks; no games or campaign writes."""

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import prism_m79_audit as audit  # noqa: E402
from scripts.prism_m79_prepare import make_blueprint  # noqa: E402
from training.prism_portable.common import read  # noqa: E402


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class SyntheticStore:
    def __init__(self, objects, commit_key, commit_bytes, identity):
        self.objects = objects
        self.commit_key = commit_key
        self.commit_bytes = commit_bytes
        self.identity = identity
        self.object_reads = []

    def _get(self, folder, key, suffix):
        if folder != "commits" or key != self.commit_key or suffix != ".json":
            raise AssertionError((folder, key, suffix))
        return self.commit_bytes

    def get_json(self, key):
        self.object_reads.append(key)
        return self.objects[key]


class SyntheticRun:
    def __init__(self, store, commit_key):
        self.store = store
        self.parent = commit_key
        self.identity = store.identity
        self.ppo = object()


class PrismM79AuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        plan = read(ROOT / "benchmarks/m79-prism-mainline.execution-plan.json")
        cls.plan = plan
        cls.spec = make_blueprint(plan)["template"]
        cls.cycles = cls.spec["cycles"]
        cls.jobs = [job for cycle in cls.cycles for job in cycle]
        cls.job_ids = [job["job_id"] for job in cls.jobs]

    def make_ledger(self, *, caps=(), infra_counts=None, infra_after=()):
        caps = set(caps)
        infra_counts = dict(infra_counts or {})
        infra_after = set(infra_after)
        attempts = {}
        valid_attempts = {}
        number = 0
        for job in self.jobs:
            job_id = job["job_id"]
            infra_count = infra_counts.get(job_id, 0)
            before_count = 0 if job_id in infra_after else infra_count
            for _ in range(before_count):
                number += 1
                attempts[str(number)] = {
                    "job": job,
                    "status": "INFRA_ABORT",
                    "reason": "interrupted_unpublished",
                    "charged_decisions": 256,
                    "retry_charged": True,
                }
            number += 1
            status = "TRUNCATED" if job_id in caps else "COMPLETE"
            row = {
                "job": job,
                "status": status,
                "charged_decisions": 2,
                "retry_charged": False,
            }
            if status == "TRUNCATED":
                row["outcome"] = {"status": "truncated"}
            attempts[str(number)] = row
            valid_attempts[job_id] = (number, row)
            after_count = infra_count if job_id in infra_after else 0
            for _ in range(after_count):
                number += 1
                attempts[str(number)] = {
                    "job": job,
                    "status": "INFRA_ABORT",
                    "reason": "interrupted_unpublished",
                    "charged_decisions": 256,
                    "retry_charged": True,
                }

        infra_total = sum(row["status"] == "INFRA_ABORT" for row in attempts.values())
        ledger = {
            "format": "prism-ppo-launch-ledger-v1",
            "attempts": attempts,
            "physical_decisions": sum(row["charged_decisions"] for row in attempts.values()),
            "retries": infra_total,
            "failed": False,
        }
        state = {
            "phase": "COMMITTED",
            "cycle": 20,
            "attempts": len(attempts),
            "consumed": [sha(f"batch-{cycle}") for cycle in range(1, 21)],
            "all_jobs": self.job_ids.copy(),
            "jobs": {
                job["job_id"]: {
                    "status": valid_attempts[job["job_id"]][1]["status"],
                    "attempt": valid_attempts[job["job_id"]][0],
                }
                for job in self.cycles[-1]
            },
        }
        return ledger, state

    def test_complete_ledger_resolves_5120_logical_jobs(self):
        ledger, state = self.make_ledger()
        result = audit.validate_ledger(ledger, state, self.spec)
        self.assertEqual(result["logical_attempts"], 5120)
        self.assertEqual(result["resolved_logical_jobs"], 5120)
        self.assertEqual(result["physical_attempts"], 5120)
        self.assertEqual(result["terminal_games"], 5120)
        self.assertEqual(result["truncated_games"], 0)
        self.assertEqual(result["infra_abort_attempts"], 0)

    def test_campaign_schedule_matches_exact_frozen_m79_order(self):
        audit._verify_training_plan(self.plan, self.spec)
        changed = copy.deepcopy(self.spec)
        changed["cycles"][0][0]["job_id"] += "-refill"
        with self.assertRaisesRegex(ValueError, "schedule differs from frozen plan"):
            audit._verify_training_plan(self.plan, changed)

    def test_scientific_caps_resolve_jobs_without_terminal_games_or_refills(self):
        cap_ids = self.job_ids[:8]
        ledger, state = self.make_ledger(caps=cap_ids)
        result = audit.validate_ledger(ledger, state, self.spec)
        self.assertEqual(result["logical_attempts"], 5120)
        self.assertEqual(result["physical_attempts"], 5120)
        self.assertEqual(result["resolved_logical_jobs"], 5120)
        self.assertEqual(result["terminal_games"], 5112)
        self.assertEqual(result["truncated_games"], 8)
        self.assertEqual(len(ledger["attempts"]), 5120)

    def test_infrastructure_retries_add_only_physical_attempts(self):
        retry_ids = self.job_ids[:2]
        ledger, state = self.make_ledger(infra_counts={job_id: 1 for job_id in retry_ids})
        result = audit.validate_ledger(ledger, state, self.spec)
        self.assertEqual(result["logical_attempts"], 5120)
        self.assertEqual(result["physical_attempts"], 5122)
        self.assertEqual(result["infra_abort_attempts"], 2)
        self.assertEqual(result["terminal_games"], 5120)
        self.assertEqual(result["resolved_logical_jobs"], 5120)
        self.assertEqual(state["all_jobs"], self.job_ids)

    def test_global_infrastructure_budget_accepts_64_and_rejects_65(self):
        accepted, state = self.make_ledger(
            infra_counts={job_id: 1 for job_id in self.job_ids[:64]})
        result = audit.validate_ledger(accepted, state, self.spec)
        self.assertEqual(result["physical_attempts"], 5184)
        self.assertEqual(result["infra_abort_attempts"], 64)
        self.assertEqual(result["logical_attempts"], 5120)

        rejected, state = self.make_ledger(
            infra_counts={job_id: 1 for job_id in self.job_ids[:65]})
        with self.assertRaisesRegex(ValueError, "global M79 infrastructure retry limit"):
            audit.validate_ledger(rejected, state, self.spec)

    def test_per_job_retry_is_single_and_must_precede_resolution(self):
        repeated, state = self.make_ledger(infra_counts={self.job_ids[0]: 2})
        with self.assertRaisesRegex(ValueError, "one infrastructure retry"):
            audit.validate_ledger(repeated, state, self.spec)

        after_resolution, state = self.make_ledger(
            infra_counts={self.job_ids[0]: 1}, infra_after={self.job_ids[0]})
        with self.assertRaisesRegex(ValueError, "after job resolution"):
            audit.validate_ledger(after_resolution, state, self.spec)

    def test_ninth_cap_is_rejected(self):
        ledger, state = self.make_ledger(caps=self.job_ids[:9])
        with self.assertRaisesRegex(ValueError, "scientific truncation limit"):
            audit.validate_ledger(ledger, state, self.spec)

    def test_duplicate_valid_attempt_and_missing_job_cannot_refill_schedule(self):
        ledger, state = self.make_ledger()
        ledger["attempts"]["1"]["job"] = copy.deepcopy(self.jobs[1])
        with self.assertRaisesRegex(ValueError, "resolve exactly once"):
            audit.validate_ledger(ledger, state, self.spec)

    def test_committed_physical_attempt_count_must_match_ledger(self):
        ledger, state = self.make_ledger()
        state["attempts"] -= 1
        with self.assertRaisesRegex(ValueError, "physical attempts disagree"):
            audit.validate_ledger(ledger, state, self.spec)

    def test_cycle_batches_use_object_binding_not_semantic_batch_id(self):
        identity = sha("run identity")
        commit_record = {
            "format": "prism-ppo-commit-v1",
            "identity": identity,
            "sequence": 0,
            "parent": None,
            "payload": sha("state payload"),
        }
        commit_bytes = json.dumps(commit_record, sort_keys=True, separators=(",", ":")).encode()
        commit_key = hashlib.sha256(commit_bytes).hexdigest()
        objects = {}
        bindings = []
        sealed = []
        consumed = []
        for cycle, jobs in enumerate(self.cycles, start=1):
            semantic_id = sha(f"semantic batch {cycle}")
            object_key = sha(f"stored JSON object {cycle}")
            behavior_id = sha(f"behavior {cycle}")
            objects[object_key] = {
                "batch_id": semantic_id,
                "behavior_id": behavior_id,
                "rows": [{"key": [job["job_id"], job["actor"], 0]} for job in jobs],
            }
            bindings.append({
                "cycle": cycle,
                "batch_id": semantic_id,
                "batch_object_sha256": object_key,
                "behavior_id": behavior_id,
                "cursor": 0,
                "run_commit": commit_key,
            })
            sealed.append({"event": "sealed", "cycle": cycle, "batch_id": semantic_id})
            consumed.append(semantic_id)

        store = SyntheticStore(objects, commit_key, commit_bytes, identity)
        run = SyntheticRun(store, commit_key)
        summary = {
            "jobs_by_cycle": self.cycles,
            "attempt_by_job": {
                job["job_id"]: (index, {"status": "COMPLETE"})
                for index, job in enumerate(self.jobs, start=1)
            },
        }
        state = {"metrics": sealed, "consumed": consumed,
                 "batch": bindings[-1]["batch_object_sha256"]}
        with tempfile.TemporaryDirectory() as tmp:
            campaign = Path(tmp)
            for binding in bindings:
                (campaign / f"cycle-{binding['cycle']}-batch-binding.json").write_text(
                    json.dumps(binding), encoding="utf-8")
            with patch("training.prism_portable.engine.ppo.learner.validate_batch"):
                observed = audit._cycle_behavior_map(run, state, self.cycles, summary, campaign)

        self.assertEqual(len(observed), 20)
        self.assertEqual(store.object_reads, [binding["batch_object_sha256"] for binding in bindings])
        self.assertNotEqual(store.object_reads[0], bindings[0]["batch_id"])


if __name__ == "__main__":
    unittest.main()
