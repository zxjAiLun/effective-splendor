"""v028 runner/audit regression tests; no Arena process or game is launched."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import s4_heuristic_v028_pilot as pilot
import s4_heuristic_v028_audit as audit


def synthetic_rows():
    return [{"game_id": f"{opponent}-{seed}-{seat}", "opponent": opponent,
             "seed": seed, "rotation": seat, "candidate_seat": seat,
             "score_bps": 10000 if seat == 0 else 0,
             "completed_plies": 60, "match_wall_seconds": 1.0}
            for opponent in audit.OPPONENTS for seed in range(9258000, 9258128)
            for seat in (0, 1)]


class V028ContractTests(unittest.TestCase):
    def test_actual_config_matches_frozen_contract(self):
        pilot.check_contract(pilot.read_json(pilot.ROOT / pilot.DEFAULT_CONFIG))

    def test_nested_config_mutations_fail_closed(self):
        changes = [
            lambda c: c.update(seed_count=32), lambda c: c.update(seed_start=9257000),
            lambda c: c.update(smoke_seed=9258000), lambda c: c.update(rotations=[0]),
            lambda c: c["candidate"].update(agent_version="0.2.7"),
            lambda c: c["candidate"]["args"].__setitem__(2, "123"),
            lambda c: c["opponents"][0].update(agent_name="spoofed"),
            lambda c: c["opponents"][1].update(program="other.exe"),
            lambda c: c["opponents"][2].update(agent_version="2"),
            lambda c: c.update(reference_sha256="0" * 64),
            lambda c: c.update(reference_program="target/release/splendor.exe"),
            lambda c: c["bootstrap"].update(resamples=100),
            lambda c: c.update(move_timeout_ms=1),
            lambda c: c.update(artifacts="../outside"),
            lambda c: c.update(unknown="extra"),
        ]
        for change in changes:
            config = copy.deepcopy(pilot.EXPECTED_CONFIG)
            change(config)
            with self.subTest(config=config), self.assertRaises(RuntimeError):
                pilot.check_contract(config)

    def test_optimized_python_cannot_disable_require(self):
        code = (f"import sys;sys.path.insert(0,{str(SCRIPTS)!r});"
                "import copy,s4_heuristic_v028_pilot as p;"
                "c=copy.deepcopy(p.EXPECTED_CONFIG);c['seed_count']=32;p.check_contract(c)")
        result = subprocess.run([sys.executable, "-O", "-c", code], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("contract mismatch", result.stderr)

    def test_registry_requires_exact_entry_and_disjoint_neighbors(self):
        pilot.check_registry([pilot.REGISTRY_ENTRY, (1, 50, "old")])
        for entries in [[], [pilot.REGISTRY_ENTRY] * 2,
                        [pilot.REGISTRY_ENTRY, (9258001, 9258010, "other")],
                        [pilot.REGISTRY_ENTRY, (1, 50, "a"), (30, 60, "b")]]:
            with self.subTest(entries=entries), self.assertRaises(RuntimeError):
                pilot.check_registry(entries)

    def test_create_only_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "manifest.json"
            pilot.write_new(path, {"one": 1})
            before = path.read_bytes()
            with self.assertRaises(FileExistsError):
                pilot.write_new(path, {"one": 2})
            self.assertEqual(path.read_bytes(), before)
            self.assertNotIn(b"\r\n", before)

    def test_freeze_detects_binary_source_or_config_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            out = root / "artifacts"
            out.mkdir()
            candidate = out / "splendor-candidate.exe"
            candidate.write_bytes(b"candidate")
            reference = root / "reference.exe"
            reference.write_bytes(b"reference")
            source = root / "source.rs"
            source.write_text("source", encoding="utf-8")
            config_path = root / "config.json"
            config_path.write_text("config", encoding="utf-8")
            frozen = {"config_sha256": pilot.sha256(config_path),
                      "candidate_binary_sha256": pilot.sha256(candidate),
                      "reference_binary_sha256": pilot.sha256(reference),
                      "sources": {"source.rs": pilot.sha256(source)}}
            pilot.write_new(out / "freeze.json", frozen)
            config = {"reference_program": "reference.exe"}
            with patch.object(pilot, "ROOT", root), patch.object(pilot, "REFERENCE_SHA", pilot.sha256(reference)), patch.object(pilot, "FROZEN_SOURCES", ("source.rs",)):
                self.assertEqual(pilot.verify_freeze(config_path, config, out), frozen)
                for path in (candidate, reference, source, config_path):
                    old = path.read_bytes()
                    path.write_bytes(old + b"drift")
                    with self.subTest(path=path), self.assertRaises(RuntimeError):
                        pilot.verify_freeze(config_path, config, out)
                    path.write_bytes(old)

    def test_manifest_and_independent_audit_pair_schedules(self):
        rows = synthetic_rows()
        audit.validate_schedule(rows)
        for malformed in (rows[:-1], rows + [rows[0]], rows[1:] + [rows[1]]):
            with self.assertRaises(RuntimeError):
                audit.validate_schedule(malformed)
        for opponent in audit.OPPONENTS:
            primary = pilot.summarize(rows, opponent, pilot.EXPECTED_CONFIG)
            separate = audit.paired_summary(rows, opponent)
            self.assertEqual(primary, separate)
            self.assertEqual(primary["ci_95_bps"], [5000.0, 5000.0])
            self.assertEqual(primary["exploratory_verdict"], "UNRESOLVED")
        rows[0]["seed"] = 9257999
        with self.assertRaises(RuntimeError):
            pilot.summarize(rows, rows[0]["opponent"], pilot.EXPECTED_CONFIG)

    def test_statistics_win_tie_mapping_and_strict_ci_boundary(self):
        for winners, seat, expected in [([0], 0, 10000), ([0], 1, 0), ([1], 1, 10000), ([0, 1], 1, 5000)]:
            self.assertEqual(pilot.validate_winners(winners, seat), expected)
            self.assertEqual(audit.score(winners, seat), expected)
        for bad in [[], [2], [0, 0], [1, 0], [0, 1, 2]]:
            with self.assertRaises(RuntimeError):
                pilot.validate_winners(bad, 0)
            with self.assertRaises(RuntimeError):
                audit.score(bad, 0)
        rows = synthetic_rows()
        for row in rows:
            row["score_bps"] = 10000
        summary = pilot.summarize(rows, audit.OPPONENTS[0], pilot.EXPECTED_CONFIG)
        self.assertEqual(summary["ci_95_bps"], [10000.0, 10000.0])
        self.assertEqual(summary["exploratory_verdict"], "EXPLORATORY_STRONGER")

    def test_artifacts_reject_wrong_identity_result_seed_plies_or_abort(self):
        specs = [pilot.EXPECTED_CONFIG["candidate"], pilot.EXPECTED_CONFIG["opponents"][0]]
        report = {"game_id": "g", "player_count": 2,
                  "agents": [{"seat": i, "agent_name": s["agent_name"], "agent_version": s["agent_version"]} for i, s in enumerate(specs)],
                  "outcome": {"status": "completed", "completed_plies": 1,
                              "replay_final_hash": "a" * 64, "result": {"winners": [0]}}}
        replay = {"player_count": 2, "seed": 9258000, "steps": [1],
                  "final_state_hash": "a" * 64, "result": {"winners": [0]}}
        pilot.validate_artifacts(report, replay, "g", 9258000, specs)
        cases = [lambda r, p: r["agents"][0].update(agent_version="0.2.7"),
                 lambda r, p: r["outcome"].update(status="aborted"),
                 lambda r, p: r["outcome"].update(completed_plies=2),
                 lambda r, p: r["outcome"].update(replay_final_hash="b" * 64),
                 lambda r, p: p.update(seed=1),
                 lambda r, p: p["result"].update(winners=[1])]
        for mutate in cases:
            r, p = copy.deepcopy(report), copy.deepcopy(replay)
            mutate(r, p)
            with self.assertRaises(RuntimeError):
                pilot.validate_artifacts(r, p, "g", 9258000, specs)

    def test_two_smoke_rows_are_exact_not_just_both_rotations(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            cfg = out / "config.json"
            cfg.write_bytes(b"cfg")
            (out / "freeze.json").write_bytes(b"freeze")
            frozen = {"candidate_binary_sha256": "f" * 64}
            smoke = {"config_sha256": pilot.sha256(cfg), "binary_sha256": "f" * 64,
                     "freeze_sha256": pilot.sha256(out / "freeze.json"), "rows": []}
            for seat in (0, 1):
                row = {"opponent": "heuristic-v025", "seed": 9257999, "rotation": seat}
                path = out / "smoke" / "heuristic-v025" / "seed-9257999" / f"r{seat}"
                path.mkdir(parents=True)
                for filename, key in [("match-config.json", "config_sha256"), ("arena-report.json", "report_sha256"), ("match-replay.json", "replay_sha256")]:
                    (path / filename).write_bytes(b"data")
                    row[key] = pilot.sha256(path / filename)
                smoke["rows"].append(row)
            pilot.check_smoke(smoke, cfg, frozen, out)
            smoke["rows"].append(smoke["rows"][0])
            with self.assertRaises(RuntimeError):
                pilot.check_smoke(smoke, cfg, frozen, out)


if __name__ == "__main__":
    unittest.main()
