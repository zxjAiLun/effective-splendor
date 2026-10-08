"""M63 training report regression on synthetic report.json/replay fixtures; no games."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
import prism_building_audit_m63 as audit
import prism_building_training_report_m63 as training_report
from training.prism_portable.engine.ppo.building import (
    BASE_CATALOG_FINGERPRINT, default_building_config, extract_building_profile,
)
from training.prism_portable.engine.ppo.building_timed import default_timed_building_config
from training.prism_portable.engine.ppo.style import extract_style_targets

SEVEN_ACTIONS = ("buy_market", "buy_reserved", "take_tokens", "reserve_market",
                 "reserve_deck", "choose_noble", "pass")


def paired_rows():
    rows = []
    for block in range(8):
        seed = 9631000 + block
        first = "win" if block % 2 == 0 else "loss"
        rows.append({"seed": seed, "actor": 0, "record": first, "score": 1.0 if first == "win" else 0.0})
        rows.append({"seed": seed, "actor": 1, "record": "loss" if first == "win" else "win",
                     "score": 0.0 if first == "win" else 1.0})
    return rows


def building_shard(job_id="m63-beta-c1-b0-s0", actor=0):
    """Synthetic own-decision shard for the real building extractor (no replays)."""
    market = [[0, 24, 3, 4], [40, 41, 42, 43], [80, 81, 82, 83]]
    def observation(purchased, bonuses):
        return {"viewer": actor, "ruleset_fingerprint": BASE_CATALOG_FINGERPRINT,
                "public": {"current_player": actor, "phase": "main",
                           "players": [{"id": actor, "bonuses": list(bonuses), "purchased": list(purchased)},
                                       {"id": 1 - actor, "bonuses": [0] * 5, "purchased": []}],
                           "market": market}}
    decisions = [
        {"observation": observation([], [0] * 5), "chosen_action": {"type": "buy_market", "tier": "One", "slot": 0}},
        {"observation": observation([0], [0, 1, 0, 0, 0]),
         "chosen_action": {"type": "buy_market", "tier": "One", "slot": 1}},
    ]
    return {"format": "prism-ppo-game-v1", "job_id": job_id, "actor": actor, "game_id": job_id,
            "catalog_fingerprint": BASE_CATALOG_FINGERPRINT, "replay_sha256": "1" * 64,
            "sidecar_sha256": "2" * 64, "terminal": True, "result": {"scores": [2, 0]},
            "decisions": decisions}


def audit_tree(work, arm="control", *, checkpoint_mutate=None, parity_mutate=None, head=None):
    project = work / "project"
    (project / f"audit-{arm}").mkdir(parents=True)
    (project / "benchmarks").mkdir(parents=True, exist_ok=True)
    (project / "benchmarks" / "m63-prism-beta-timed-building.config.json").write_text("{}", encoding="utf-8")
    root = work / f"campaign-{arm}"
    (root / "run").mkdir(parents=True)
    (root / "cycle-4-export").mkdir(parents=True)
    (root / "blueprint.json").write_text(json.dumps({"synthetic": arm}), encoding="utf-8")
    (root / "contract.json").write_text(json.dumps({"bound": arm}), encoding="utf-8")
    (root / "run/HEAD.json").write_text(json.dumps(head or {"identity": "run-identity", "commit": "commit-1"}),
                                        encoding="utf-8")
    (root / "cycle-4-export/weights.json").write_bytes(b"synthetic-final-weights")
    config_sha = audit.sha(project / "benchmarks" / "m63-prism-beta-timed-building.config.json")
    weights_sha = audit.sha(root / "cycle-4-export/weights.json")
    source_hashes = {"synthetic/a.py": "1" * 64}
    checkpoint = {"format": "m63-checkpoint-validation-v1", "status": "PASS", "arm": arm, "cycle": 4,
                  "config_sha256": config_sha, "blueprint_sha256": audit.sha(root / "blueprint.json"),
                  "bound_contract_sha256": audit.sha(root / "contract.json"),
                  "run_identity": "run-identity", "commit": "commit-1",
                  "final_weights_sha256": weights_sha, "source_hashes": source_hashes,
                  "jobs": 1024, "attempts": 1024, "consumed_batches": 4}
    parity = {"format": "m63-final-parity-v1", "status": "PASS", "arm": arm, "config_sha256": config_sha,
              "run_identity": "run-identity", "commit": "commit-1", "weights_sha256": weights_sha,
              "boundary_inputs": 68, "atol": 1e-4, "rtol": 1e-4}
    if checkpoint_mutate:
        checkpoint = checkpoint_mutate(copy.deepcopy(checkpoint))
    if parity_mutate:
        parity = parity_mutate(copy.deepcopy(parity))
    audit.write(project / f"audit-{arm}/checkpoint-validation.json", checkpoint)
    audit.write(project / f"audit-{arm}/final-parity.json", parity)
    return project, root, {"runtime": {"source_hashes": source_hashes}}


class M63TrainingReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.detail = training_report.helper()

    def test_pinned_report_helper_identity_and_labels(self):
        self.assertEqual(audit.sha(ROOT / "scripts/prism_portable_report.py"),
                         audit.LEGACY_HASHES["prism_portable_report.py"])
        self.assertEqual(self.detail.LABELS["prism-general-v011"], "Prism v0.1.1")
        self.assertIn("Prism Balance v0.1.0", self.detail.LABELS["balance-parent-v010"])
        self.assertIn("Heuristic v0.3.1", self.detail.LABELS["heuristic-v031"])
        self.assertEqual(tuple(self.detail.ACTIONS), SEVEN_ACTIONS)

    def test_training_shard_binds_game_identity_to_report_json_not_replay(self):
        job = {"job_id": "m63-beta-c1-b0-s0", "actor": 0}
        completion = {"behavior_id": "b" * 64}
        spec = {"run": {"catalog_fingerprint": "c" * 64}}
        report_row = {"game_id": "m63-beta-c1-b0-s0", "outcome": "win"}
        sidecar = [{"decision": 1}]
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            replay_path, sidecar_path = work / "replay.json", work / "sidecar.jsonl"
            # Real ReplayV1 carries no game_id; only report.json names the game.
            replay = {"format": "prism-replay-v1", "steps": [], "result": {"scores": [2, 0]}}
            replay_path.write_text(json.dumps(replay), encoding="utf-8")
            sidecar_path.write_text("\n".join(json.dumps(row) for row in sidecar), encoding="utf-8")
            shard = training_report.training_shard(job, completion, report_row, replay, sidecar,
                                                   spec, replay_path, sidecar_path)
            self.assertEqual(shard["game_id"], report_row["game_id"])
            self.assertEqual(shard["job_id"], job["job_id"])
            self.assertEqual(shard["actor"], job["actor"])
            self.assertEqual(shard["behavior_id"], completion["behavior_id"])
            self.assertEqual(shard["catalog_fingerprint"], spec["run"]["catalog_fingerprint"])
            self.assertEqual(shard["replay_sha256"], audit.sha(replay_path))
            self.assertEqual(shard["sidecar_sha256"], audit.sha(sidecar_path))
            self.assertTrue(shard["terminal"])
            self.assertEqual(shard["result"], replay["result"])
            self.assertEqual(shard["decisions"], sidecar)
            self.assertEqual(shard["format"], "prism-ppo-game-v1")
            # Even a stale/foreign game_id inside the replay must not be consumed.
            poisoned = dict(replay, game_id="m61-stale-game")
            shard = training_report.training_shard(job, completion, report_row, poisoned, sidecar,
                                                   spec, replay_path, sidecar_path)
            self.assertEqual(shard["game_id"], report_row["game_id"])
            drifted = dict(report_row, game_id="m63-beta-c1-b1-s1")
            with self.assertRaisesRegex(ValueError, "explicit report game identity drift"):
                training_report.training_shard(job, completion, drifted, replay, sidecar,
                                               spec, replay_path, sidecar_path)
            with self.assertRaises(KeyError):  # a report without game_id cannot pass
                training_report.training_shard(job, completion, {"outcome": "win"}, replay, sidecar,
                                               spec, replay_path, sidecar_path)

    def test_paired_ci_deterministic_and_fail_closed(self):
        rows = paired_rows()
        first, second = training_report.paired_ci(rows), training_report.paired_ci(rows)
        self.assertEqual(first, second)
        self.assertAlmostEqual(first["estimate"], .5)
        self.assertEqual((first["seed_blocks"], first["resamples"], first["bootstrap_seed"]),
                         (8, 20000, 63049999))
        self.assertEqual(len(first["ci95"]), 2)
        self.assertLessEqual(first["ci95"][0], first["ci95"][1])
        self.assertIn("not acceptance", first["scope"])
        pure = training_report.paired_ci(rows, pure=True)
        self.assertAlmostEqual(pure["estimate"], .5)
        self.assertEqual(pure["bootstrap_seed"], 63049999)
        duplicate = rows + [dict(rows[0])]
        with self.assertRaises(ValueError):
            training_report.paired_ci(duplicate)
        with self.assertRaises(ValueError):
            training_report.paired_ci(rows[:-1])  # one seed lost its actor-1 pair

    def test_building_profile_style_fields_present_for_building_format(self):
        shard = building_shard()
        profile = extract_building_profile(shard, default_building_config())
        self.assertEqual(profile["building_use_units"], 1)
        self.assertEqual(profile["building_utility"], 1 / 24)
        self.assertAlmostEqual(profile["early_bonus_auc12"], 23 / 12)
        self.assertEqual((profile["early_lowvp_buys"], profile["redeemed_investments"],
                          profile["unredeemed_investments"]), (2, 1, 1))
        self.assertEqual(profile["investments"][0]["use_main_actions"], [2])
        self.assertTrue(profile["redemption_horizon_censored"])
        self.assertEqual((profile["job_id"], profile["actor"], profile["replay_sha256"], profile["sidecar_sha256"]),
                         (shard["job_id"], 0, "1" * 64, "2" * 64))
        summary = training_report.style_summary([profile])
        self.assertEqual(summary["games"], 1)
        self.assertAlmostEqual(summary["mean_building_utility"], 1 / 24)
        self.assertAlmostEqual(summary["mean_early_bonus_auc12"], 23 / 12)
        self.assertEqual((summary["total_investments"], summary["total_redeemed"],
                          summary["investment_redemption_rate"], summary["censored_games"]), (2, 1, .5, 1))
        self.assertIn("descriptive only", summary["scope"])

    def test_m63_dispatcher_extracts_timed_target_and_preserves_v1_descriptors(self):
        shard = building_shard()
        target_map, summary = extract_style_targets([shard], default_timed_building_config())
        profile = summary["games"][0]
        self.assertEqual(summary["format"], "prism-building-timed-targets-v1")
        self.assertEqual(target_map[(shard["job_id"], shard["actor"])], profile["time_weighted_utility"])
        self.assertEqual(profile["format"], "prism-building-timed-profile-v1")
        self.assertEqual(profile["building_v1_profile"]["format"], "prism-building-profile-v1")
        self.assertEqual(profile["building_utility"], profile["building_v1_profile"]["building_utility"])
        self.assertEqual(profile["early_bonus_auc12"], profile["building_v1_profile"]["early_bonus_auc12"])
        self.assertEqual(profile["investments"], profile["building_v1_profile"]["investments"])
        timed_summary = training_report.style_summary([profile])
        self.assertEqual(timed_summary["mean_time_weighted_utility"], profile["time_weighted_utility"])
        self.assertIn("timed use target is diagnostic only", timed_summary["scope"])

    def test_style_summary_rejects_empty_profiles(self):
        with self.assertRaisesRegex(ValueError, "empty building profiles"):
            training_report.style_summary([])

    def test_verified_receipts_pass_on_well_formed_synthetic_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            project, root, config = audit_tree(Path(directory))
            checkpoint, parity = training_report.verified_receipts(project, "control", root, config)
            self.assertEqual((checkpoint["status"], parity["status"]), ("PASS", "PASS"))
            self.assertEqual((checkpoint["arm"], parity["arm"]), ("control", "control"))

    def test_verified_receipts_fails_closed_on_drift(self):
        cases = {
            "parity_status": dict(parity_mutate=lambda p: dict(p, status="FAIL")),
            "checkpoint_status": dict(checkpoint_mutate=lambda c: dict(c, status="FAIL")),
            "wrong_arm": dict(checkpoint_mutate=lambda c: dict(c, arm="beta")),
            "wrong_cycle": dict(checkpoint_mutate=lambda c: dict(c, cycle=3)),
            "config_hash_drift": dict(checkpoint_mutate=lambda c: dict(c, config_sha256="0" * 64)),
            "parity_config_hash_drift": dict(parity_mutate=lambda p: dict(p, config_sha256="0" * 64)),
            "blueprint_hash_drift": dict(checkpoint_mutate=lambda c: dict(c, blueprint_sha256="0" * 64)),
            "contract_hash_drift": dict(checkpoint_mutate=lambda c: dict(c, bound_contract_sha256="0" * 64)),
            "weights_hash_drift": dict(checkpoint_mutate=lambda c: dict(c, final_weights_sha256="0" * 64)),
            "parity_weights_hash_drift": dict(parity_mutate=lambda p: dict(p, weights_sha256="0" * 64)),
            "head_identity_drift": dict(head={"identity": "other", "commit": "commit-1"}),
            "head_commit_drift": dict(head={"identity": "run-identity", "commit": "other"}),
            "parity_identity_drift": dict(parity_mutate=lambda p: dict(p, run_identity="other")),
            "source_identity_drift": dict(checkpoint_mutate=lambda c: dict(c, source_hashes={})),
            "boundary_inputs": dict(parity_mutate=lambda p: dict(p, boundary_inputs=67)),
            "tolerance": dict(parity_mutate=lambda p: dict(p, rtol=1e-3)),
            "job_count": dict(checkpoint_mutate=lambda c: dict(c, jobs=1023)),
            "attempt_count": dict(checkpoint_mutate=lambda c: dict(c, attempts=1023)),
            "consumed_batches": dict(checkpoint_mutate=lambda c: dict(c, consumed_batches=3)),
        }
        for name, kwargs in cases.items():
            with self.subTest(mutation=name):
                with tempfile.TemporaryDirectory() as directory:
                    project, root, config = audit_tree(Path(directory), **kwargs)
                    with self.assertRaises(ValueError):
                        training_report.verified_receipts(project, "control", root, config)
        with self.subTest(mutation="missing_checkpoint_receipt"):
            with tempfile.TemporaryDirectory() as directory:
                project, root, config = audit_tree(Path(directory))
                (project / "audit-control/checkpoint-validation.json").unlink()
                with self.assertRaises(FileNotFoundError):
                    training_report.verified_receipts(project, "control", root, config)
        with self.subTest(mutation="missing_binding_field"):
            with tempfile.TemporaryDirectory() as directory:
                project, root, config = audit_tree(
                    Path(directory), checkpoint_mutate=lambda c: {k: v for k, v in c.items()
                                                                  if k != "run_identity"})
                with self.assertRaises(KeyError):
                    training_report.verified_receipts(project, "control", root, config)

    def test_publish_binding_requires_both_arms_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(training_report.publish_binding(Path(directory)))
            self.assertFalse((Path(directory) / "training-artifact-audit.json").exists())

    def test_player_macro_and_group_tables_on_synthetic_fixtures(self):
        rows = [
            {"actor": 0, "record": "win", "candidate_vp": 2, "opponent_vp": 0, "seed": 9631000,
             "score": 1.0, "candidate_actions": {"take_tokens": 2, "buy_market": 1},
             "opponent_actions": {"take_tokens": 3}, "plies": 6, "wall_seconds": 1.0},
            {"actor": 1, "record": "win", "candidate_vp": 2, "opponent_vp": 1, "seed": 9631000,
             "score": 1.0, "candidate_actions": {"reserve_market": 1, "buy_reserved": 1},
             "opponent_actions": {"pass": 1, "buy_market": 1}, "plies": 4, "wall_seconds": 2.0},
        ]
        candidate_batch = {
            "mean_prestige": 2.0, "mean_nobles": 0.0, "mean_permanent_bonuses": 1.0,
            "mean_reserves_acquired": .5, "mean_reserves_bought": .5, "mean_reserves_stranded": 0.0,
            "mean_cards_by_vp": {str(v): (1.0 if v == 2 else 0.0) for v in range(6)},
            "mean_bonuses_by_color": {c: (1.0 if c == "Blue" else 0.0) for c in self.detail.COLORS},
            "games_with_nobles": 0,
            "action_distribution": {"take_tokens": 2, "buy_market": 1, "reserve_market": 1,
                                    "buy_reserved": 1}}
        opponent_batch = {
            "mean_prestige": .5, "mean_nobles": 0.0, "mean_permanent_bonuses": .5,
            "mean_reserves_acquired": 0.0, "mean_reserves_bought": 0.0, "mean_reserves_stranded": 0.0,
            "mean_cards_by_vp": {str(v): (.5 if v == 1 else 0.0) for v in range(6)},
            "mean_bonuses_by_color": {c: (.5 if c == "White" else 0.0) for c in self.detail.COLORS},
            "games_with_nobles": 0,
            "action_distribution": {"take_tokens": 3, "pass": 1, "buy_market": 1}}
        candidate = self.detail.player(rows, [(candidate_batch, 2)], True)
        opponent = self.detail.player(rows, [(opponent_batch, 2)], False)
        self.assertEqual(candidate["games"], 2)
        self.assertEqual(candidate["win_rate_percent"], 100.0)
        self.assertEqual(candidate["actions"]["buy_market"]["count"], 1)
        self.assertEqual(sorted(candidate["actions"]), sorted(SEVEN_ACTIONS))
        self.assertEqual(opponent["actions"]["take_tokens"]["count"], 3)
        self.assertEqual(opponent["wins"], 0)
        macro = self.detail.macro(rows)
        self.assertEqual(macro["total_games"], 2)
        self.assertEqual(macro["decision_latency_ms"], "NOT_MEASURED")
        self.assertEqual(macro["inference_latency_ms"], "NOT_MEASURED")
        group = {"cycle": 4, "opponent_id": "prism-general-v011", "label": "synthetic group",
                 "games": rows, "candidate": candidate, "opponent": opponent,
                 "score_ci": training_report.paired_ci(rows), "win_ci": training_report.paired_ci(rows, True),
                 "behavior_id": "b" * 64, "opponent_identity": "o" * 64}
        text = self.detail.group_tables(group)
        for marker in ("未发布训练检查点 c3", "NOT_RUN", "P0（先手）", "P1（后手）", "种子：9631000",
                       "NOT_MEASURED / NOT_MEASURED", "只有一个种子块"):
            self.assertIn(marker, text)
        for action in SEVEN_ACTIONS:
            self.assertIn(action, text)


if __name__ == "__main__":
    unittest.main()
