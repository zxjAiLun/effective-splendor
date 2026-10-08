"""M61 r1 regression gates using copied, authentic first training game.

Always use the archived remote M61 engine, never mutable current local sources.
M61_REAUDIT_ARTIFACT_ROOT selects the r1 directory when testing on cloud1.
"""
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[3]
ART = Path(os.environ.get("M61_REAUDIT_ARTIFACT_ROOT",
           str(REPO / "local-artifacts/prism/balance-ab-m61/reaudit-r1")))
FROZEN = ART / "frozen-source"
# These paths precede mutable project engine and helpers.
sys.path.insert(0, str(FROZEN / "scripts"))
sys.path.insert(0, str(FROZEN))
REVISION = ART / "prism_balance_ab_reaudit_m61.py"
if not REVISION.exists():
    REVISION = REPO / "scripts/prism_balance_ab_reaudit_m61.py"
spec = importlib.util.spec_from_file_location("m61_reaudit_r1_under_test", REVISION)
r1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r1)


class M61ReauditRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = ART / "regression/alpha-001"
        cls.completion = json.loads((cls.root / "completion.json").read_text())
        cls.report = json.loads((cls.root / "report.json").read_text())
        cls.replay = json.loads((cls.root / "replay.json").read_text())
        cls.sidecar = [json.loads(line) for line in (cls.root / "sidecar.jsonl").read_text().splitlines()]
        cls.before = {p.name: r1.audit.sha(p) for p in cls.root.iterdir() if p.is_file()}
        # Fail if the copied authentic bytes do not agree with original completion.
        for name in ("report", "replay", "sidecar"):
            suffix = ".jsonl" if name == "sidecar" else ".json"
            assert r1.audit.sha(cls.root / (name + suffix)) == cls.completion["files"][name]["sha256"]
        for name, digest in r1.FROZEN.items():
            assert r1.audit.sha(FROZEN / name) == digest
        assert "game_id" not in cls.replay

    def game(self, *, report=None, sidecar=None, replay=None):
        c = self.completion
        return r1.verified_game(c["contract"], c["job"], c,
                                self.replay if replay is None else replay,
                                self.report if report is None else report,
                                self.sidecar if sidecar is None else sidecar,
                                self.root / "replay.json", self.root / "sidecar.jsonl")

    def test_authentic_replay_missing_game_id_uses_verified_report(self):
        shard, score = self.game()
        self.assertEqual(shard["game_id"], self.report["game_id"])
        self.assertEqual(score, 1.0)
        self.assertEqual(len(shard["decisions"]), len(self.sidecar))
        self.assertNotIn("game_id", self.replay)
        self.assertEqual(self.before, {p.name: r1.audit.sha(p) for p in self.root.iterdir() if p.is_file()})

    def test_internally_consistent_sidecar_wrong_game_id_fails(self):
        rows = copy.deepcopy(self.sidecar)
        for row in rows:
            row["request"]["game_id"] = row["response"]["game_id"] = "different-but-consistent"
        with self.assertRaisesRegex(ValueError, "trajectory game_id mismatch"):
            self.game(sidecar=rows)

    def test_verified_report_identity_seed_and_final_hash_fail_closed(self):
        changes = [("game_id", "wrong-job"), ("seed_commitment", "0" * 64),
                   ("ruleset_fingerprint", "0" * 64)]
        for key, value in changes:
            with self.subTest(key=key):
                report = copy.deepcopy(self.report)
                report[key] = value
                with self.assertRaises(ValueError):
                    self.game(report=report)
        report = copy.deepcopy(self.report)
        report["outcome"]["replay_final_hash"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "report/replay result/hash mismatch"):
            self.game(report=report)

    def test_missing_report_id_has_no_fallback(self):
        report = copy.deepcopy(self.report)
        del report["game_id"]
        with self.assertRaisesRegex(ValueError, "report: unknown/missing fields"):
            self.game(report=report)

    def test_sidecar_actor_and_response_disagreement_fail(self):
        for key, value in (("actor", 1), ("game_id", "wrong-response")):
            rows = copy.deepcopy(self.sidecar)
            rows[0]["response"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.game(sidecar=rows)

    def test_report_and_replay_result_disagreement_fails(self):
        replay = copy.deepcopy(self.replay)
        replay["result"]["scores"][0] += 1
        with self.assertRaisesRegex(ValueError, "report/replay result/hash mismatch"):
            self.game(replay=replay)

    def test_native_audit_authentic_replay_and_tampered_player_projection(self):
        engine = Path(self.completion["contract"]["arena"]["program"])
        if not engine.exists():
            self.skipTest("pinned native ARM binary available only on cloud1")
        shard, _ = self.game()
        with tempfile.TemporaryDirectory(dir=ART) as directory:
            root = Path(directory)
            evidence = r1.native_game(self.completion["contract"], self.completion["job"], self.completion,
                                      shard, self.root / "replay.json", self.root / "sidecar.jsonl", root / "audit.json")
            self.assertEqual(evidence["exit_code"], 0)
            from training.prism_portable.engine.ppo.audit import audit_game
            rows = copy.deepcopy(self.sidecar)
            rows[0]["request"]["input"]["entities"][0][0] += 1.0
            sidecar = root / "tampered-sidecar.jsonl"
            sidecar.write_text("".join(json.dumps(row) + "\n" for row in rows))
            with self.assertRaisesRegex(ValueError, "Rust PPO audit failed"):
                audit_game(engine, self.completion["contract"]["arena"]["sha256"], self.root / "replay.json",
                           sidecar, root / "tampered-audit.json", behavior_id=self.completion["behavior_id"],
                           job_id=self.completion["job"]["job_id"], actor=self.completion["job"]["actor"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
