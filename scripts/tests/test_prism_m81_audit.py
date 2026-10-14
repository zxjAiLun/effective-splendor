from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import torch

from scripts import prism_m81_audit as audit_module


ROOT = Path(__file__).resolve().parents[2]


def _bound_contracts_without_assets(root: Path) -> dict[str, dict]:
    """Bind the real M81 A/B blueprints with plan identities and fake host paths."""
    from scripts import prism_m81_run
    from training.prism_portable import protocol
    from training.prism_portable.common import package_identity
    from training.prism_portable.engine.ppo import coordinator

    plan = audit_module.read_json(root / audit_module.PLAN_PATH)
    plan_assets = plan["assets"]
    host_assets = {
        "engine": {
            "path": str(root / "test-host" / "splendor"),
            "sha256": plan_assets["heuristic"]["engine_sha256"],
        }
    }
    for name, asset in plan_assets.items():
        if name == "heuristic":
            continue
        host_assets[name] = {
            "path": str(root / "test-host" / "inputs" / f"{name}.json"),
            "sha256": asset["sha256"],
        }
    host = {"code_identity": package_identity(), "assets": host_assets}
    path_hash = {item["path"]: item["sha256"] for item in host_assets.values()}

    def expected_digest(path):
        return path_hash[str(path)]

    original_validate_config = coordinator.validate_config

    def allow_resource_mode(config):
        if config["budget"]["max_run_seconds"] is None:
            config = copy.deepcopy(config)
            config["budget"]["max_run_seconds"] = 1
        return original_validate_config(config)

    contracts = {}
    with patch.object(protocol, "digest", side_effect=expected_digest), \
            patch.object(coordinator, "validate_config", side_effect=allow_resource_mode):
        for arm in audit_module.ARMS:
            blueprint = prism_m81_run.blueprint(arm)
            contracts[arm] = protocol.bind(blueprint, host)
    return contracts


class M81AuditTests(unittest.TestCase):
    def test_bound_arm_contracts_match_frozen_grid_without_games(self):
        plan = audit_module.read_json(ROOT / audit_module.PLAN_PATH)
        contracts = _bound_contracts_without_assets(ROOT)

        for arm in audit_module.ARMS:
            with self.subTest(arm=arm):
                cycles = audit_module._validate_campaign_contract(plan, arm, contracts[arm])
                self.assertEqual(len(cycles), 20)
                self.assertEqual(sum(map(len, cycles)), 5120)
                self.assertEqual(cycles[0][0]["environment_seed"], 81001000)
                self.assertEqual(cycles[-1][-1]["environment_seed"], 81003559)
                self.assertEqual(cycles[0][0]["job_id"], f"m81-{arm}-c1-b0-s0")
                self.assertEqual(cycles[-1][-1]["job_id"], f"m81-{arm}-c20-b127-s1")

        bad_id = copy.deepcopy(contracts["B"])
        bad_id["cycles"][0][0]["job_id"] = "m81-B-c1-b0-s1"
        with self.assertRaisesRegex(ValueError, "job ID"):
            audit_module._validate_campaign_contract(plan, "B", bad_id)

        bad_hello = copy.deepcopy(contracts["B"])
        bad_hello["opponents"]["heuristic"]["hello"]["agent_version"] = "0.3.0"
        with self.assertRaisesRegex(ValueError, "heuristic descriptor"):
            audit_module._validate_campaign_contract(plan, "B", bad_hello)

    def test_zero_game_audit_fails_closed_and_writes_both_receipts(self):
        plan_bytes = (ROOT / audit_module.PLAN_PATH).read_bytes()
        plan = json.loads(plan_bytes)
        execution = {"plan_sha256": audit_module.digest(ROOT / audit_module.PLAN_PATH)}
        real_import_module = importlib.import_module
        installed = []

        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            (temp_root / audit_module.PLAN_PATH).parent.mkdir(parents=True)
            (temp_root / audit_module.PLAN_PATH).write_bytes(plan_bytes)
            (temp_root / "execution.json").write_text(json.dumps(execution), encoding="utf-8")
            fake_run = SimpleNamespace(
                ROOT=temp_root,
                verify=lambda: (plan, execution),
                install_resource_mode=lambda: installed.append(True),
                bounds=lambda: {"status": "PASS", "within_bounds": True},
            )

            def import_for_audit(name, *args, **kwargs):
                if name == "scripts.prism_m81_run":
                    return fake_run
                return real_import_module(name, *args, **kwargs)

            with patch.object(audit_module.importlib, "import_module", side_effect=import_for_audit):
                result = audit_module.audit(temp_root)

            self.assertTrue(installed)
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["arms"], {"A": "FAIL", "B": "FAIL"})
            self.assertFalse((temp_root / "campaigns").exists())
            for arm in audit_module.ARMS:
                receipt = audit_module.read_json(temp_root / "audits" / arm / "audit.json")
                self.assertEqual(receipt["status"], "FAIL")
                self.assertFalse(receipt["research_started"])
                self.assertIn("campaign", receipt["error"])

    def test_checkpoint_policy_must_match_exact_32_plus_4_tensor_inventory(self):
        from training.prism_portable.engine.ppo.model import PPOModel

        model = PPOModel(style_enabled=False)
        committed = model.state_dict()
        exported_policy = model.policy.state_dict()
        self.assertEqual(len(exported_policy), 32)
        self.assertEqual(len(audit_module.STYLE_TENSORS), 4)
        self.assertEqual(
            audit_module._validate_committed_tensor_inventory(committed, exported_policy, torch),
            {"policy_tensors": 32, "style_head_tensors": 4},
        )
        self.assertEqual(torch.count_nonzero(committed["style_head.2.weight"]).item(), 0)
        self.assertEqual(torch.count_nonzero(committed["style_head.2.bias"]).item(), 0)

        missing_style = dict(committed)
        missing_style.pop("style_head.0.weight")
        with self.assertRaisesRegex(ValueError, "exactly 32 policy and 4 style-head"):
            audit_module._validate_committed_tensor_inventory(missing_style, exported_policy, torch)

        mismatched_policy = dict(committed)
        key = next(iter(exported_policy))
        mismatched_policy["policy." + key] = exported_policy[key] + 1
        with self.assertRaisesRegex(ValueError, "differs from the committed checkpoint"):
            audit_module._validate_committed_tensor_inventory(mismatched_policy, exported_policy, torch)

    def test_checkpoint_directory_inventory_rejects_unplanned_cycle(self):
        plan = audit_module.read_json(ROOT / audit_module.PLAN_PATH)
        with tempfile.TemporaryDirectory() as temporary:
            campaign = Path(temporary)
            for cycle in [5, 10, 15, 20, 1]:
                (campaign / f"cycle-{cycle}-export").mkdir()
            with self.assertRaisesRegex(ValueError, "exact plan exports"):
                audit_module._checkpoint_inventory(
                    campaign,
                    plan,
                    {},
                    {},
                    {},
                    SimpleNamespace(),
                    {},
                    "0" * 64,
                )


if __name__ == "__main__":
    unittest.main()
