import tempfile
import unittest
from unittest import mock
import zipfile
from pathlib import Path

from scripts import prism_m79_dual_dispatch as dual


def fixture_plan():
    common = {
        "heuristic": [17010000, 17010255], "general": [17011000, 17011255],
        "balance": [17012000, 17012255], "alpha": [17013000, 17013255],
        "beta": [17014000, 17014255], "released-alpha": [17015000, 17015255],
    }
    coverage = {"latest-alpha": [17020000, 17020255],
                "latest-balance": [17021000, 17021255]}
    return {"evaluation": {
        "shard_seed_blocks": 32, "seats": [0, 1],
        "common_actors": ["base", "a", "style-reference"],
        "common_opponents": list(common), "common_seed_by_opponent": common,
        "coverage_actors": ["base", "a"], "coverage_seed_by_opponent": coverage,
        "direct": {"candidate": "a", "opponent": "parent", "seed_range": [17030000, 17030511]},
    }}


def _pipeline_fixture():
    journal = []
    category = "evaluation_development"
    spent=sum(r.get('cpu_seconds',0) for r in journal if r['category']==category)
    allspent=sum(r.get('cpu_seconds',0) for r in journal)
    return spent,allspent


class DualDispatchTests(unittest.TestCase):
    def test_exact_frozen_grid_partition_and_nonoverlap(self):
        rows = dual.schedule(fixture_plan())
        aux = dual.aux_labels(fixture_plan(), rows)
        auxiliary, control = dual.partition(rows, aux, set())
        self.assertEqual(len(rows), 192)
        self.assertEqual(sum(r["planned_games"] for r in rows), 12288)
        self.assertEqual(sum(r["planned_games"] for r in auxiliary), 7168)
        self.assertEqual(sum(r["planned_games"] for r in control), 5120)
        self.assertEqual({r["actor"] for r in auxiliary}, {"base", "style-reference"})
        self.assertTrue(all(len(r["seeds"]) == 32 and r["planned_games"] == 64 for r in rows))
        started = {next(iter(aux))}
        auxiliary, control = dual.partition(rows, aux, started)
        self.assertNotIn(next(iter(started)), {r["label"] for r in auxiliary})
        self.assertIn(next(iter(started)), {r["label"] for r in control})
        self.assertEqual(dual.AUX_CPU_SECONDS, 40000)
        self.assertEqual(dual.CONTROL_EVAL_BASE_SECONDS, 80000)
        self.assertEqual(dual.INFRA_EXTRA_LIMIT, 64)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            dual.partition(rows + [rows[0]], aux, set())

    def test_semantic_config_normalizes_node_root_only(self):
        cfg = {"program": "/node-a/bin/splendor", "args": ["--weights", "/node-a/inputs/base.json"],
               "action_seed": 79020001}
        other = {"program": "/node-b/bin/splendor", "args": ["--weights", "/node-b/inputs/base.json"],
                 "action_seed": 79020001}
        self.assertEqual(dual.semantic_sha(cfg, Path("/node-a")),
                         dual.semantic_sha(other, Path("/node-b")))
        other["action_seed"] += 1
        self.assertNotEqual(dual.semantic_sha(cfg, Path("/node-a")),
                            dual.semantic_sha(other, Path("/node-b")))

    def test_bundle_checks_member_sha_and_rejects_unsafe_paths(self):
        for path in ("../outside", "/root/file", "C:/escape", "evaluation\\..\\secret"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                dual.safe_member(path)
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "items.zip"
            receipt = dual.make_bundle(archive, {"evaluation/base-x-1/a.json": b"a",
                                                  "state.json": b"{}"}, {"kind": "test"})
            manifest, payload = dual.verify_bundle(archive, Path(str(archive) + ".receipt.json"),
                                                   {"kind": "test"})
            self.assertEqual(payload["state.json"], b"{}")
            self.assertEqual(len(manifest["members"]), receipt["member_count"])
            payload_bytes = bytearray(archive.read_bytes())
            payload_bytes[-24] ^= 1
            archive.write_bytes(payload_bytes)
            with self.assertRaisesRegex(ValueError, "receipt SHA256"):
                dual.verify_bundle(archive, Path(str(archive) + ".receipt.json"))

            dual.make_bundle(archive, {"evaluation/base-x-1/a.json": b"a",
                                       "state.json": b"{}"}, {"kind": "test"})
            receipt_path = Path(str(archive) + ".receipt.json")
            with zipfile.ZipFile(archive) as z:
                entries = {name: z.read(name) for name in z.namelist()}
            entries["state.json"] = b'{"changed":true}'
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
                for name, data in entries.items():
                    z.writestr(name, data)
            receipt = dual.read_json(receipt_path)
            receipt["sha256"] = dual.sha_file(archive)
            receipt["bytes"] = archive.stat().st_size
            dual.write_json(receipt_path, receipt)
            with self.assertRaisesRegex(ValueError, "member SHA256 mismatch"):
                dual.verify_bundle(archive, receipt_path)

    def test_import_rejects_candidate_material_and_preserves_zero_retry_rule(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "inputs.zip"
            receipt_path = Path(str(archive) + ".receipt.json")
            receipt = dual.make_bundle(archive, {"campaigns/a/weights.json": b"x"},
                                       {"kind": "inputs", "infra_reservation": 0})
            with self.assertRaisesRegex(ValueError, "candidate-training"):
                dual.import_inputs(Path(temp), archive, receipt_path)
        self.assertEqual(dual.AUX_CPU_SECONDS + dual.CONTROL_EVAL_BASE_SECONDS,
                         dual.EVAL_CPU_SECONDS)
        self.assertEqual(0, {"aux_infra_reservation": 0}["aux_infra_reservation"])

    def test_pipeline_budget_patch_reads_source_once_and_patches_both_sites(self):
        with mock.patch.dict(_pipeline_fixture.__globals__, {"ROOT": Path(".")}):
            with mock.patch.object(dual, "_external_eval_cpu", return_value=13):
                patched = dual._patch_pipeline_budget(_pipeline_fixture)
        self.assertEqual(patched(), (13, 13))

    def test_source_manifest_is_supported_at_either_frozen_root_location(self):
        with mock.patch.multiple(dual, FIXED_INPUTS=(), RUNTIME_SOURCES=(),
                                 PLAN_REL="plan.json", STATE_REL="state.json"):
            for manifest_rel in dual.SOURCE_MANIFEST_CANDIDATES:
                with self.subTest(manifest=manifest_rel), tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    required = ("plan.json", "execution.json", "round-budget.json", "state.json",
                                "scripts/prism_m79_dual_dispatch.py", manifest_rel)
                    for rel in required:
                        path = root / rel
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(b"{}")
                    paths = dual._input_paths(root, {})
                    self.assertIn(manifest_rel, paths)


if __name__ == "__main__":
    unittest.main()
