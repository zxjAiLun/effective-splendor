from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import prism_m79_archive as archive
from scripts import prism_m79_profile as profile


ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = ROOT / "benchmarks/m79-prism-mainline.execution-plan.json"
STYLE_POLICY_PATH = ROOT / "benchmarks/prism-style-bands-v020.policy.json"
STYLE_SHA = "e2914425cac49f0f2272c44379e46a43525d97ced2eaac206e8600ebf73e79c4"
PARENT_SHA = "a" * 64
CANDIDATE_BYTES = b"synthetic M79 c20 weights"
CANDIDATE_SHA = hashlib.sha256(CANDIDATE_BYTES).hexdigest()
ENGINE_SHA = "e" * 64
ANCHOR_COMPLETE_SHA = "1" * 64
ANCHOR_INCOMPLETE_SHA = "2" * 64


def _main_score_fixture(main_count: int = 24) -> tuple[dict, dict]:
    scores = [0, 0]
    counts = [0, 0]
    steps = []
    decisions = [[], []]

    def observation(actor: int, phase: str = "main") -> dict:
        return {
            "viewer": actor,
            "public": {
                "current_player": actor,
                "phase": phase,
                "players": [
                    {"id": 0, "prestige": scores[0]},
                    {"id": 1, "prestige": scores[1]},
                ],
            },
        }

    for _ in range(main_count):
        for actor in (0, 1):
            action = {"type": "take_tokens"}
            row = {"ply": len(steps), "actor": actor, "action": action}
            steps.append(row)
            decisions[actor].append({
                "ply": row["ply"], "chosen_action": action,
                "observation": observation(actor),
            })
            counts[actor] += 1
            scores[actor] += 1 if actor == 0 else 2
            if actor == 0 and counts[actor] == 12:
                noble = {"type": "choose_noble", "noble": 0}
                noble_row = {"ply": len(steps), "actor": actor, "action": noble}
                steps.append(noble_row)
                decisions[actor].append({
                    "ply": noble_row["ply"], "chosen_action": noble,
                    "observation": observation(actor, "choose_noble"),
                })
                scores[actor] += 3

    replay = {"steps": steps, "result": {"scores": scores}}
    projection = {"players": [
        {"actor": actor, "decisions": decisions[actor]} for actor in (0, 1)
    ]}
    return replay, projection


def _profile_row(
    *, game_key: str, model: str, opponent: str, model_sha: str | None,
    opponent_sha: str | None, seat: int, round_opponent: str,
    main_actions: int = 24, replay_sha: str | None = None,
    candidate_seat: int | None = None,
    seed: int = 1,
) -> dict:
    replay_sha = replay_sha or hashlib.sha256(game_key.encode("utf-8")).hexdigest()
    candidate_seat = seat if candidate_seat is None else candidate_seat
    observed_12 = main_actions >= 12
    observed_24 = main_actions >= 24
    return {
        "format": profile.PROFILE_FORMAT,
        "game_key": game_key,
        "replay_sha256": replay_sha,
        "model": model,
        "model_sha256": model_sha,
        "opponent": opponent,
        "opponent_sha256": opponent_sha,
        "seat": seat,
        "candidate_seat": candidate_seat,
        "candidate_role": "candidate" if seat == candidate_seat else "opponent",
        "round_opponent_id": round_opponent,
        "seed": seed,
        "main_actions": main_actions,
        "first_big_main": 4,
        "first_big_main_sum": 4,
        "first_big_games": 1,
        "first_big_coverage_games": 1,
        "first_big_coverage_denominator": 1,
        "first_big_purchase_events": [{
            "own_main": 4, "printed_vp": 3, "action_type": "buy_market",
        }],
        "early_low_cards": 0,
        "early_low_main_observed": min(main_actions, 12),
        "early_low_window_complete_games": int(main_actions >= 12),
        "early_low_window_games": 1,
        "early_discount_redemptions": 0,
        "early_discount_redemptions_before_game_cap": 0,
        "early_discount_observed_applications": 0,
        "early_discount_investments": 0,
        "early_discount_redeemed_investments": 0,
        "early_discount_censored_investments": 0,
        "early_discount_horizon_complete_games": int(main_actions >= 24),
        "early_discount_horizon_observed_mains": min(main_actions, 24),
        "early_discount_horizon_censored_games": int(main_actions < 24),
        "discount_semantics": "fixture using inherited observed-purchase semantics",
        "own_main_12_vp": 12 if observed_12 else None,
        "own_main_12_observed": int(observed_12),
        "own_main_12_survived": int(observed_12),
        "own_main_12_survival_denominator": 1,
        "own_main_24_vp": 25 if observed_24 else None,
        "own_main_24_observed": int(observed_24),
        "own_main_24_survived": int(observed_24),
        "own_main_24_survival_denominator": 1,
        "nobles_selected": 0,
        "terminal_vp": 25,
    }


def _small_plan() -> dict:
    return {
        "round": "M79",
        "parent_label": "M75 c20 (unpublished)",
        "assets": {
            "parent": {"sha256": PARENT_SHA},
            "style-reference": {"sha256": STYLE_SHA},
            "anchor-complete": {"sha256": ANCHOR_COMPLETE_SHA},
            "anchor-incomplete": {"sha256": ANCHOR_INCOMPLETE_SHA},
        },
        "training": {
            "initialization": "fresh optimizer warm-start",
            "training_seed_count": 1,
            "candidate": "fixed final cycle20 after all 5120 logical attempts accounted for",
        },
        "evaluation": {
            "mode": "both-greedy",
            "action_seed": 79020001,
            "shard_seed_blocks": 32,
            "ply_cap": 512,
            "seats": [0, 1],
            "common_actors": ["a", "base", "style-reference"],
            "common_opponents": ["anchor-complete", "anchor-incomplete"],
            "common_seed_by_opponent": {
                "anchor-complete": [10, 10],
                "anchor-incomplete": [20, 20],
            },
            "coverage_seed_by_opponent": {},
            "coverage_actors": ["a", "base"],
            "direct": {"candidate": "a", "opponent": "parent", "seed_range": [30, 30]},
        },
        "style": {
            "reference_asset": "style-reference",
            "level_ceiling": "DESCRIPTIVE; mixed/undetermined permitted; no confirmed style or version assignment",
            "policy_path": "benchmarks/prism-style-bands-v020.policy.json",
            "policy_sha256": hashlib.sha256(STYLE_POLICY_PATH.read_bytes()).hexdigest(),
        },
    }


def _verified_fixture() -> tuple[dict, dict, dict, dict]:
    plan = _small_plan()
    expected = archive.expected_grid(plan)
    attempts = []
    profiles_by_game = {}
    replay_receipts = []
    model_shas = {"a": CANDIDATE_SHA, "base": PARENT_SHA, "style-reference": STYLE_SHA}

    for key in sorted(expected):
        model, opponent, seed, candidate_seat = key
        game_key = f"{model}/{opponent}/seed-{seed}/seat-{candidate_seat}"
        if key == ("a", "parent", 30, 1):
            continue
        state = "RETAINED_FAILURE" if key == ("a", "anchor-incomplete", 20, 1) else "COMPLETED"
        attempts.append({"model": model, "opponent": opponent, "seed": seed,
                         "seat": candidate_seat, "state": state})
        if state != "COMPLETED":
            continue
        replay_sha = hashlib.sha256(game_key.encode("utf-8")).hexdigest()
        replay_receipts.append({"game_key": game_key, "replay_sha256": replay_sha,
                                "seed": seed, "candidate_seat": candidate_seat,
                                "rust_verified_terminal": True})
        actors = []
        for seat in (0, 1):
            is_candidate = seat == candidate_seat
            actor_model = model if is_candidate else opponent
            actor_opponent = opponent if is_candidate else model
            actor_sha = model_shas.get(actor_model)
            other_sha = model_shas.get(actor_opponent)
            actors.append(_profile_row(
                game_key=game_key, model=actor_model, opponent=actor_opponent,
                model_sha=actor_sha, opponent_sha=other_sha, seat=seat,
                round_opponent=opponent, replay_sha=replay_sha,
                candidate_seat=candidate_seat, seed=seed,
            ))
        profiles_by_game[game_key] = actors

    pairs = []
    pairs_needed = {(model, opponent) for model, opponent, _, _ in expected}
    for candidate, opponent in sorted(pairs_needed):
        pairs.append({"candidate": candidate, "opponent": opponent,
                      "candidate_metrics": {"games": 2},
                      "opponent_metrics": {"games": 2}, "seats": []})
    result = {
        "execution_status": "INCOMPLETE",
        "candidate_sha256": {"a": CANDIDATE_SHA},
        "pairs": pairs,
        "statistics": {"overall_status": "INCOMPLETE"},
    }
    profile_receipt = {
        "format": profile.RECEIPT_FORMAT,
        "status": "PASS",
        "new_games": 0,
        "games_verified": len(replay_receipts),
        "actor_profiles": 2 * len(replay_receipts),
        "replays": replay_receipts,
    }
    observed_keys = [archive._attempt_key(row) for row in attempts]
    receipt = {
        "format": archive.IDENTITY_RECEIPT_FORMAT,
        "status": "PASS",
        "plan_sha256": "p" * 64,
        "result_sha256": "r" * 64,
        "evaluation_plan_sha256": "e" * 64,
        "transfer_manifest_sha256": "t" * 64,
        "evaluation_integrity_status": "PASS",
        "transfer_integrity_status": "PASS",
        "expected_grid_sha256": archive.canonical_grid(sorted(expected)),
        "observed_grid_sha256": archive.canonical_grid(observed_keys),
        "model_sha256": model_shas,
        "rules_sha256": "d" * 64,
        "mode": "both-greedy",
        "candidate_sha256": CANDIDATE_SHA,
        "profile_receipt_sha256": hashlib.sha256(archive.canonical(profile_receipt)).hexdigest(),
    }
    verified = {
        "format": archive.INPUT_FORMAT,
        "identity_receipt": receipt,
        "attempts": attempts,
        "profiles_by_game": profiles_by_game,
        "profile_receipt": profile_receipt,
    }
    return plan, result, verified, json.loads(STYLE_POLICY_PATH.read_text(encoding="utf-8"))


def _raw_build_fixture(raw_root: Path, plan_path: Path, plan: dict, result: dict,
                       verified: dict) -> None:
    weights = raw_root / "campaigns/a/cycle-20-export/weights.json"
    weights.parent.mkdir(parents=True, exist_ok=True)
    weights.write_bytes(CANDIDATE_BYTES)
    audit_path = raw_root / "audits/a/audit.json"
    archive.write_json(audit_path, {
        "status": "PASS_TRAINING_ARTIFACT_AUDIT", "weights_sha256": CANDIDATE_SHA,
    })
    registry_path = raw_root / "candidate-registry.json"
    archive.write_json(registry_path, {
        "status": "FROZEN_FINAL_C20_BEFORE_EVALUATION",
        "parent_sha256": PARENT_SHA,
        "models": {"a": {"path": str(weights), "sha256": CANDIDATE_SHA,
                          "audit_sha256": archive.digest(audit_path)}},
    })

    actor_shas = {
        "a": CANDIDATE_SHA, "base": PARENT_SHA,
        "style-reference": STYLE_SHA, "parent": PARENT_SHA,
        "anchor-complete": ANCHOR_COMPLETE_SHA,
        "anchor-incomplete": ANCHOR_INCOMPLETE_SHA,
    }
    expected = archive.expected_grid(plan)
    recorded = {archive._attempt_key(row): row for row in verified["attempts"]}
    groups = {}
    for key in expected:
        groups.setdefault(key[:2], set()).add(key)
    shards = []
    for (model, opponent), keys in sorted(groups.items()):
        seed = min(key[2] for key in keys)
        label = f"{model}-{opponent}-{seed}"
        directory = raw_root / "evaluation" / label
        directory.mkdir(parents=True)

        def descriptor(actor: str) -> dict:
            return {
                "program": "/synthetic/bin/splendor", "sha256": ENGINE_SHA,
                "args": ["agent-prism", "--weights", f"inputs/{actor}.json", "--seed", "79020001"],
                "files": [{"path": f"inputs/{actor}.json", "sha256": actor_shas[actor]}],
            }

        config = {
            "format": "prism-ppo-fixed-eval-v1",
            "engine": {"program": "/synthetic/bin/splendor", "sha256": ENGINE_SHA},
            "catalog_fingerprint": "synthetic-catalog", "action_seed": 79020001,
            "seeds": [seed], "candidates": {model: descriptor(model)},
            "opponents": {opponent: descriptor(opponent)},
            "timeouts": {"game_wall_seconds": 90},
        }
        policy = {"format": "prism-bounded-eval-v1", "max_games": len(keys),
                  "max_truncated_games": len(keys), "ply_cap": 512,
                  "automatic_game_retries": 0}
        archive.write_json(directory / "config.json", config)
        archive.write_json(directory / "policy.json", policy)
        manifest = {
            "format": "prism-guarded-eval-v1",
            "config_sha256": hashlib.sha256(archive.canonical(config)).hexdigest(),
            "policy_sha256": hashlib.sha256(archive.canonical(policy)).hexdigest(),
            "source_sha256": {},
        }
        archive.write_json(directory / "manifest.json", manifest)
        entries = {}
        for key in sorted(keys):
            source_attempt = recorded.get(key)
            if source_attempt is None:
                continue
            entry_key = f"{key[0]}/{key[1]}/seed-{key[2]}/seat-{key[3]}"
            if source_attempt["state"] != "COMPLETED":
                entries[entry_key] = {"state": "RETAINED_FAILURE", "kind": "PLY_CAP_TRUNCATED"}
                continue
            game_dir = directory / "games" / key[0] / key[1] / f"seed-{key[2]}-seat-{key[3]}"
            game_dir.mkdir(parents=True)
            replay_result = {"scores": [5, 5], "ranks": [0, 0], "winners": [0, 1], "reason": "fixture"}
            replay = {"format": "effective-splendor-replay", "version": 1,
                      "player_count": 2, "seed": key[2], "result": replay_result, "steps": []}
            report = {"outcome": {"status": "completed", "result": replay_result}}
            row = {"candidate": key[0], "opponent": key[1], "seed": key[2],
                   "candidate_seat": key[3], "candidate_score": 0.5, "record": "draw"}
            archive.write_json(game_dir / "replay.json", replay)
            archive.write_json(game_dir / "report.json", report)
            archive.write_json(game_dir / "game.json", {"state": "COMPLETED", "row": row})
            archive.write_json(game_dir / "match-config.json", {"seed": key[2]})
            evidence = {path.relative_to(game_dir).as_posix(): archive.digest(path)
                        for path in game_dir.rglob("*") if path.is_file()}
            entries[entry_key] = {"state": "COMPLETED", "row": row, "metrics": {},
                                  "evidence_sha256": evidence}
        archive.write_json(directory / "ledger.json", {
            "execution_state": "FINISHED", "entries": entries,
            "consumed_cpu_seconds": 0.0,
            "manifest_sha256": archive.digest(directory / "manifest.json"),
        })
        shards.append({"label": label, "planned_games": len(keys),
                       "manifest_sha256": archive.digest(directory / "manifest.json")})

    archive.write_json(raw_root / "evaluation-plan.json", {
        "format": "prism-m79-bounded-shards-v1", "shards": shards,
        "total_games": len(expected), "plan_sha256": archive.digest(plan_path),
        "candidate_registry_sha256": archive.digest(registry_path),
    })
    manifest = {
        path.relative_to(raw_root).as_posix(): archive.digest(path)
        for path in raw_root.rglob("*") if path.is_file()
    }
    archive.write_json(raw_root / "transfer-manifest.json", manifest)


class PrismM79ArchiveTests(unittest.TestCase):
    def test_actual_m79_grid_has_declared_three_actor_size(self):
        plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
        grid = archive.expected_grid(plan)
        counts = {model: sum(key[0] == model for key in grid) for model in archive.MODEL_IDS}
        self.assertEqual(len(grid), 12288)
        self.assertEqual(counts, {"a": 5120, "base": 4096, "style-reference": 3072})
        policy = archive._plan_style_policy(plan)
        self.assertEqual(policy["reference_sha256"], STYLE_SHA)

    def test_missing_result_build_writes_identity_bound_not_run_without_candidate_sha(self):
        plan_bytes = PLAN_PATH.read_bytes()
        plan = json.loads(plan_bytes)
        with tempfile.TemporaryDirectory() as temporary:
            temp = Path(temporary)
            plan_path = temp / "m79-plan.json"
            plan_path.write_bytes(plan_bytes)
            raw_root = temp / "bounded-eval"
            raw_root.mkdir()
            sentinel = raw_root / "evaluation-plan.json"
            sentinel.write_text('{"unchanged":true}\n', encoding="utf-8")
            before = sentinel.read_bytes()
            result_path = temp / "missing-result.json"
            prefix = temp / "archive" / "m79"

            card, receipt = archive.build(plan_path, result_path, raw_root, prefix)

            self.assertEqual(card["status"], "UNKNOWN")
            self.assertEqual(card["execution"]["state"], "UNKNOWN")
            self.assertEqual(card["execution"]["observation_state"], "NOT_OBSERVED")
            self.assertEqual(card["execution"]["result_sha256"], None)
            self.assertEqual(card["identity"]["candidate"]["sha256"], None)
            self.assertEqual(card["identity"]["candidate"]["status"], "NOT_RUN")
            self.assertNotIn("c20", card["identity"]["candidate"]["label"].lower())
            self.assertEqual(card["identity"]["plan_sha256"], hashlib.sha256(plan_bytes).hexdigest())
            self.assertEqual(card["identity"]["parent"]["sha256"], plan["assets"]["parent"]["sha256"])
            self.assertEqual(card["identity"]["style_reference"]["sha256"], STYLE_SHA)
            self.assertEqual(card["competitive"]["status"], "NOT_RUN")
            self.assertEqual(card["profile"]["evidence_level"], "NOT_RUN")
            self.assertEqual(card["publication"], {
                "published": False, "default_replaced": False, "deployed": False,
            })
            self.assertEqual(receipt["candidate_sha256"], None)
            self.assertEqual(sentinel.read_bytes(), before)
            self.assertTrue(prefix.with_suffix(".json").is_file())
            self.assertTrue(prefix.with_suffix(".md").is_file())
            self.assertTrue(prefix.with_suffix(".html").is_file())

    def test_missing_result_preserves_recorded_training_progress_and_evaluation_not_run(self):
        plan_bytes = PLAN_PATH.read_bytes()
        plan = json.loads(plan_bytes)
        with tempfile.TemporaryDirectory() as temporary:
            temp = Path(temporary)
            plan_path = temp / "m79-plan.json"
            plan_path.write_bytes(plan_bytes)
            raw_root = temp / "bounded-eval"
            status_path = raw_root / "pipeline/status.json"
            archive.write_json(status_path, {
                "state": "RUNNING", "phase": "TRAIN", "pid": 4312,
                "create_time": 1728000000.0, "node": "dsw2-m79",
                "execution_sha256": "d" * 64, "observed_at": 1728000010.0,
            })
            archive.write_json(raw_root / "campaigns/a/control/live-progress.json", {
                "phase": "COLLECTING", "cycle": 8, "attempts": 2048,
                "global_step": 210, "observed_at": 1728000009.0,
                "execution_sha256": "d" * 64,
            })
            card, _ = archive.build(
                plan_path, temp / "missing-result.json", raw_root, temp / "out/m79")
            self.assertEqual(card["status"], "RUNNING:TRAIN")
            self.assertEqual(card["execution"]["training"]["state"], "IN_PROGRESS_AS_RECORDED")
            self.assertEqual(card["execution"]["independent_evaluation"]["state"], "NOT_RUN")
            self.assertEqual(card["identity"]["candidate"]["status"], "NOT_RUN")
            self.assertEqual(card["execution"]["observation_state"], "STORED_EVIDENCE_ONLY")

    def test_main_12_24_snapshots_include_noble_choice_and_terminal_score(self):
        replay, projection = _main_score_fixture()
        actor0 = profile.snapshot_verified_main_scores(replay, projection, 0, 24)
        actor1 = profile.snapshot_verified_main_scores(replay, projection, 1, 24)
        self.assertEqual(actor0["12"]["vp"], 15)
        self.assertEqual(actor0["12"]["source"], "next_verified_public_observation_after_main_action")
        self.assertEqual(actor0["24"]["vp"], 27)
        self.assertEqual(actor1["24"]["vp"], 48)
        self.assertEqual(actor1["24"]["source"], "verified_terminal_result")

    def test_short_game_is_not_measured_but_stays_in_survival_denominator(self):
        short_replay, short_projection = _main_score_fixture(main_count=8)
        short = profile.snapshot_verified_main_scores(short_replay, short_projection, 0, 8)
        self.assertEqual(short["12"]["status"], "NOT_MEASURED")
        self.assertIsNone(short["12"]["vp"])
        self.assertEqual(short["24"]["status"], "NOT_MEASURED")

        rows = [
            _profile_row(game_key="g-short", model="a", opponent="op", model_sha=CANDIDATE_SHA,
                         opponent_sha=None, seat=0, round_opponent="op", main_actions=8),
            _profile_row(game_key="g-long", model="a", opponent="op", model_sha=CANDIDATE_SHA,
                         opponent_sha=None, seat=0, round_opponent="op", main_actions=12),
        ]
        rows[1]["own_main_12_vp"] = 14
        summary = profile.aggregate_profiles(rows)
        self.assertEqual(summary["own_main_12_snapshot_games"], 1)
        self.assertEqual(summary["own_main_12_survival_coverage_games"], 1)
        self.assertEqual(summary["own_main_12_survival_coverage_denominator"], 2)
        self.assertEqual(summary["own_main_12_survival_coverage"], 0.5)
        self.assertEqual(summary["own_main_24_survival_coverage_denominator"], 2)
        self.assertIsNone(summary["own_main_24_vp_mean"])

    def test_extract_uses_only_three_actor_complete_opponents_and_keeps_dynamic_gaps(self):
        plan, result, verified, policy = _verified_fixture()
        card, receipt = archive.extract(
            plan, result, verified,
            plan_sha256="p" * 64, result_sha256="r" * 64,
            evaluation_plan_sha256="e" * 64, transfer_manifest_sha256="t" * 64,
            policy=policy,
        )
        self.assertEqual(card["profile"]["complete_common_opponents"], ["anchor-complete"])
        self.assertEqual(card["profile"]["evidence_level"], "DESCRIPTIVE")
        self.assertEqual(card["profile"]["route_recommendation"]["route"], "Balance")
        self.assertEqual(card["profile"]["route_recommendation"]["evidence_level"], "DESCRIPTIVE")
        self.assertEqual(card["profile"]["policy_level_ceiling"], "DESCRIPTIVE")
        self.assertEqual(card["profile"]["comparisons"]["candidate_vs_parent"]["first_big_main"], 0)
        self.assertEqual(card["profile"]["comparisons"]["candidate_vs_fixed_style_reference"]["first_big_main"], 0)
        self.assertEqual(card["competitive"]["dynamic_grid"]["planned_logical_attempts"], 14)
        self.assertEqual(card["competitive"]["dynamic_grid"]["recorded_attempts"], 13)
        self.assertEqual(card["competitive"]["dynamic_grid"]["completed_attempts"], 12)
        self.assertEqual(card["competitive"]["dynamic_grid"]["status_counts"].get("RETAINED_FAILURE"), 1)
        self.assertEqual(card["competitive"]["dynamic_grid"]["status_counts"].get("NOT_RECORDED"), 1)
        self.assertEqual(receipt["new_games"], 0)

    def test_extract_rejects_result_without_candidate_artifact_sha(self):
        plan, result, verified, policy = _verified_fixture()
        result["candidate_sha256"] = {}
        verified["identity_receipt"]["candidate_sha256"] = None
        verified["identity_receipt"]["model_sha256"]["a"] = None
        with self.assertRaisesRegex(ValueError, "lacks candidate_sha256.a"):
            archive.extract(
                plan, result, verified,
                plan_sha256="p" * 64, result_sha256="r" * 64,
                evaluation_plan_sha256="e" * 64, transfer_manifest_sha256="t" * 64,
                policy=policy,
            )

    def test_build_generates_binding_cache_from_raw_shards_without_owner_sidecar(self):
        plan, result, verified, _ = _verified_fixture()
        with tempfile.TemporaryDirectory() as temporary:
            temp = Path(temporary)
            plan_path = temp / "plan.json"
            archive.write_json(plan_path, plan)
            result_path = temp / "result.json"
            archive.write_json(result_path, result)
            raw_root = temp / "bounded-eval"
            raw_root.mkdir()
            _raw_build_fixture(raw_root, plan_path, plan, result, verified)
            original_root_files = {
                path.relative_to(raw_root).as_posix(): path.read_bytes()
                for path in raw_root.rglob("*") if path.is_file()
            }
            prefix = temp / "archive" / "m79"
            model_shas = {
                "a": CANDIDATE_SHA, "base": PARENT_SHA, "style-reference": STYLE_SHA,
                "parent": PARENT_SHA, "anchor-complete": ANCHOR_COMPLETE_SHA,
                "anchor-incomplete": ANCHOR_INCOMPLETE_SHA,
            }

            def fake_profile_saved_replays(rows):
                profiles = json.loads(json.dumps(verified["profiles_by_game"]))
                receipts = []
                for source in rows:
                    game_key = source["game_key"]
                    replay_sha = archive.digest(source["replay_path"])
                    receipts.append({"game_key": game_key, "replay_sha256": replay_sha,
                                     "seed": source["seed"],
                                     "candidate_seat": source["candidate_seat"],
                                     "rust_verified_terminal": True})
                    for actor in profiles[game_key]:
                        actor["replay_sha256"] = replay_sha
                        actor["model_sha256"] = model_shas[actor["model"]]
                        actor["opponent_sha256"] = model_shas.get(actor["opponent"])
                receipt = {
                    "format": profile.RECEIPT_FORMAT, "status": "PASS", "new_games": 0,
                    "games_requested": len(rows), "games_verified": len(rows),
                    "actor_profiles": 2 * len(rows), "replays": receipts,
                }
                return {"profiles": profiles, "verify_receipt": receipt}

            with patch.object(archive.m79_profile, "profile_saved_replays", fake_profile_saved_replays), \
                    patch("scripts.prism_m79_statistics.analyze", return_value=result["statistics"]):
                card, archive_receipt = archive.build(plan_path, result_path, raw_root, prefix)

            self.assertEqual(card["identity"]["candidate"]["sha256"], CANDIDATE_SHA)
            self.assertEqual(archive_receipt["status"], "PASS_OFFLINE_ARCHIVE")
            self.assertEqual(card["profile"]["complete_common_opponents"], ["anchor-complete"])
            self.assertEqual({
                path.relative_to(raw_root).as_posix(): path.read_bytes()
                for path in raw_root.rglob("*") if path.is_file()
            }, original_root_files)
            self.assertFalse(result_path.with_name(result_path.name + ".m79-verified-archive-input.json").exists())
            cache = prefix.with_suffix(".verified-input-cache.json")
            self.assertTrue(cache.is_file())
            self.assertEqual(archive_receipt["generated_binding_cache"]["sha256"], archive.digest(cache))

    def test_render_keeps_missing_identity_explicit(self):
        plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
        card, _ = archive.not_run_card(plan, "p" * 64, "capacity unresolved")
        with tempfile.TemporaryDirectory() as temporary:
            md_path, html_path = archive.render(card, Path(temporary) / "m79")
            md = md_path.read_text(encoding="utf-8")
            page = html_path.read_text(encoding="utf-8")
            self.assertIn("NOT_RUN", md)
            self.assertIn("M79 candidate (NOT_RUN)", md)
            self.assertIn("NOT_RUN", page)
            self.assertNotIn("M79 c20", md)
            self.assertNotIn("M79 c20", page)


if __name__ == "__main__":
    unittest.main()
