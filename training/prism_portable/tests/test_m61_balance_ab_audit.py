"""M61 failure gates; synthetic optimizer slots, no games or training updates."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import torch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
import prism_balance_ab_audit_m61 as audit
import prism_balance_ab_training_report_m61 as report
from training.prism_portable.engine.ppo.model import new_model


class M61AuditTests(unittest.TestCase):
    def slots(self, enabled):
        model = new_model(style_enabled=enabled)
        optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad])
        saved = optimizer.state_dict()
        params = [p for p in model.parameters() if p.requires_grad]
        saved["state"] = {i: {"step": torch.tensor(7.), "exp_avg": torch.zeros_like(p),
                              "exp_avg_sq": torch.zeros_like(p)} for i, p in enumerate(params)}
        return model, optimizer, saved

    def test_real_parameter_counts_and_disabled_forward(self):
        model, optimizer, saved = self.slots(False)
        result = audit.optimizer_evidence(model, optimizer, saved, "balance", 7)
        self.assertEqual(result["optimizer_slots"], 32)
        self.assertFalse(result["style_enabled"])
        self.assertTrue(all(not p.requires_grad and p.grad is None for p in model.style_head.parameters()))
        from training.prism_portable.engine.data import collate_states
        fixture = json.loads((ROOT / "local-artifacts/prism/portable-m57/inputs/boundary-fixtures.jsonl").read_text().splitlines()[0])
        _, value, style = model.forward_batch(collate_states([fixture.get("input", fixture)]))
        self.assertTrue(value.requires_grad)
        self.assertFalse(style.requires_grad)
        self.assertTrue(torch.equal(style, torch.zeros_like(style)))
        model, optimizer, saved = self.slots(True)
        self.assertEqual(audit.optimizer_evidence(model, optimizer, saved, "alpha", 7)["optimizer_slots"], 36)

    def test_balance_cannot_pass_from_disabled_label_only(self):
        model, optimizer, saved = self.slots(True)
        model.style_enabled = False  # A declaration alone cannot hide trainable head.
        with self.assertRaises(ValueError):
            audit.optimizer_evidence(model, optimizer, saved, "balance", 7)
        model, optimizer, saved = self.slots(False)
        next(model.style_head.parameters()).grad = torch.zeros_like(next(model.style_head.parameters()))
        with self.assertRaisesRegex(ValueError, "grads"):
            audit.optimizer_evidence(model, optimizer, saved, "balance", 7)

    def test_optimizer_order_extra_slot_shape_and_step_fail(self):
        for mutation in ("order", "extra", "shape", "step"):
            with self.subTest(mutation=mutation):
                model, optimizer, saved = self.slots(False)
                if mutation == "order":
                    optimizer.param_groups[0]["params"].reverse()
                elif mutation == "extra":
                    saved["state"][99] = saved["state"][0]
                elif mutation == "shape":
                    saved["state"][0]["exp_avg"] = torch.zeros(1)
                else:
                    saved["state"][0]["step"] = torch.tensor(6.)
                with self.assertRaises(ValueError):
                    audit.optimizer_evidence(model, optimizer, saved, "balance", 7)

    def test_failed_incomplete_or_alive_supervisor_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "control").mkdir()
            for status, alive in (("FAILED", False), ("RUNNING", True), ("STOPPED_BOUNDARY", False),
                                  ("STOPPED_COMMITTED", True)):
                (root / "control/status.json").write_text(json.dumps({"status": status, "alive": alive,
                                                                     "resources": {"returncode": 0, "stop_reason": None}}))
                with self.assertRaises(ValueError):
                    audit.stopped(root)
            row = {"status": "STOPPED_COMMITTED", "pid": 12, "launch_token": "owned",
                   "resources": {"returncode": 0, "stop_reason": None}}
            (root / "control/status.json").write_text(json.dumps(row))
            with patch("training.prism_portable.control.owned_alive", return_value=True):
                with self.assertRaisesRegex(ValueError, "still alive"):
                    audit.stopped(root)

    def test_progress_uses_real_ledger_not_216(self):
        state = {"phase": "COMMITTED", "cycle": 4, "attempts": 1024, "all_jobs": list(range(1024)),
                 "consumed": list("abcd"), "decisions": 40, "global_step": 4, "update_attempts": 4, "metrics": []}
        summaries = []
        for cycle in range(1, 5):
            step = {"event": "optimizer_step", "cycle": cycle, "global_step": cycle, "optimizer_applied": True}
            state["metrics"].extend([{"event": "sealed", "cycle": cycle, "batch_id": "abcd"[cycle-1], "decisions": 10},
                                     {"event": "optimizer_attempt", "cycle": cycle, "attempt": cycle}, step,
                                     {"event": "passes_complete", "cycle": cycle, "batch_id": "abcd"[cycle-1]}])
            summaries.append({"cycle": cycle, "stop_reason": "passes_complete", "updates": [step],
                              "optimizer_steps": 1, "update_attempts": 1, "groups": {"all": {"games": 256, "decisions": 10}}})
        config = {"budget": {"max_optimizer_steps": 10, "max_update_attempts": 10, "max_decisions": 100}}
        self.assertEqual(audit.progress_evidence(state, config, summaries)["global_step"], 4)
        for key, value in (("global_step", 216), ("phase", "FAILED"), ("attempts", 1023), ("cycle", 3)):
            altered = dict(state, **{key: value})
            with self.assertRaises(ValueError):
                audit.progress_evidence(altered, config, summaries)

    def test_schedule_rng_mismatch_and_parity_drift_rejected(self):
        bp = {"weight_hashes": {"parent": "same"}, "template": {"run": {"run_id": "alpha", "seed": 1,
              "ppo": {"style_beta": .3, "style_value_weight": .5}}, "cycles": [[{"job_id": "a", "actor": 0}]]}}
        other = copy.deepcopy(bp)
        other["template"]["run"].update(run_id="balance")
        other["template"]["run"]["ppo"].update(style_beta=0, style_value_weight=0)
        other["template"]["cycles"][0][0]["job_id"] = "b"
        audit.matched_blueprints(bp, other)
        other["template"]["run"]["seed"] = 2
        with self.assertRaises(ValueError):
            audit.matched_blueprints(bp, other)
        for left, right in ((.2, .3), (float("nan"), float("nan")), ({"x": 1}, {"y": 1}), ([1], [1, 2])):
            with self.assertRaises(ValueError):
                audit.compare_values(left, right, [])

    def test_pinned_helper_and_single_arm_never_publish_global_pass(self):
        self.assertEqual(audit.sha(ROOT / "scripts/prism_portable_report.py"), audit.LEGACY_HASHES["prism_portable_report.py"])
        self.assertIn("Heuristic v0.3.1", report.helper().LABELS["heuristic-v031"])
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(report.publish_binding(Path(directory)))
            self.assertFalse((Path(directory) / "training-artifact-audit.json").exists())


if __name__ == "__main__":
    unittest.main()
