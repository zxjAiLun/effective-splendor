"""M62 same-parent building draft invariants; pure builders only, no writes or games."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("m62_prepare", ROOT / "scripts/prism_building_prepare_m62.py")
m62 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m62)

from training.prism_portable.engine.ppo.building import default_building_config

PARENT = "225daf49e8746576b1edc3508ca0454715e5454529fea53dc7dfeb9043cf01f1"
ALPHA = "d3a313090bb2ccae678d3b9cf1216f0a60527ec330432c5c2dcdddd85b53b2d9"
LABELS = {"control": "Prism Balance v0.1.1 CANDIDATE", "beta": "Prism Beta v0.1.0 CANDIDATE"}
MIX = {"prism-general-v011": 512, "balance-parent-v010": 256, "prism-v01": 128, "heuristic-v031": 128}
ORDER = ["prism-general-v011", "balance-parent-v010", "prism-general-v011", "prism-v01",
         "prism-general-v011", "balance-parent-v010", "prism-general-v011", "heuristic-v031"]
EXPECTED = {"parent": PARENT, "general": "2" * 64, "initial": "3" * 64}
GATES = {"control/strength_pool": -.05, "control/direct_parent": .45,
         "beta/strength_pool": -.05, "beta/general_anchor": -.075,
         "beta/direct_control": .45, "beta/direct_alpha": .45, "beta/direct_parent": .45,
         "beta/building_utility": .015, "beta/early_bonus_auc12": .25}
REQUIRED_GATES = {"control": ["strength_pool", "direct_parent"],
                  "beta": ["strength_pool", "general_anchor", "direct_control", "direct_alpha",
                           "direct_parent", "building_utility", "early_bonus_auc12"]}
ANCHORS = ["heuristic-v031", "prism-v01", "prism-general-v011"]


def synthetic_assets():
    return {"parent": {"path": "synthetic-parent.json", "sha256": PARENT},
            "general": {"path": "synthetic-general.json", "sha256": "2" * 64},
            "initial": {"path": "synthetic-initial.json", "sha256": "3" * 64},
            "fixtures": {"path": "synthetic-fixtures.jsonl", "sha256": "4" * 64},
            "alpha": {"path": "synthetic-alpha.json", "sha256": ALPHA}}


class M62PrepareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous = m62.read(ROOT / "benchmarks/m61-prism-balance-ab.train.json")
        cls.bps = m62.build_blueprints(cls.previous, EXPECTED)
        cls.previous_config = m62.read(ROOT / "benchmarks/m61-prism-alpha-balance-ab.config.json")

    def draft_config(self):
        return m62.build_draft_config(self.previous_config, self.bps, synthetic_assets())

    def normalize(self, bp):
        x = copy.deepcopy(bp)
        x.pop("model_label")
        x["template"]["run"].pop("run_id")
        for key in ("style_beta", "style_value_weight"):
            x["template"]["run"]["ppo"].pop(key)
        for cycle in x["template"]["cycles"]:
            for job in cycle:
                job.pop("job_id")
        return x

    def test_registered_records_pin_frozen_parent_and_alpha_hashes(self):
        for filename, version, sha in (("m61-prism-balance-v0.1.0.model.json", "0.1.0", PARENT),
                                       ("m61-prism-alpha-v0.1.4.model.json", "0.1.4", ALPHA)):
            row = m62.read(ROOT / "benchmarks" / filename)
            self.assertEqual(row["status"], "REGISTERED_EXPERIMENTAL_MODEL")
            self.assertEqual((row["model_version"], row["weights_sha256"]), (version, sha))

    def test_exactly_two_arms_differing_only_in_identity_and_two_coefficients(self):
        self.assertEqual(set(self.bps), {"control", "beta"})
        m62.validate_blueprints(self.bps)
        self.assertEqual(self.normalize(self.bps["control"]), self.normalize(self.bps["beta"]))
        for arm in ("control", "beta"):
            bp = self.bps[arm]
            run = bp["template"]["run"]
            self.assertEqual(bp["model_label"], LABELS[arm])
            self.assertEqual((run["run_id"], run["seed"]), (f"m62-{arm}-building", 62041001))
            self.assertEqual((run["ppo"]["style_beta"], run["ppo"]["style_value_weight"]),
                             (.3, .5) if arm == "beta" else (0, 0))
        beta, control = self.bps["beta"]["template"]["run"]["ppo"], self.bps["control"]["template"]["run"]["ppo"]
        self.assertEqual({key for key in beta if beta[key] != control[key]},
                         {"style_beta", "style_value_weight"})
        self.assertEqual(control, self.previous["template"]["run"]["ppo"])
        self.assertEqual({arm: self.bps[arm]["weight_hashes"] for arm in ("control", "beta")},
                         {"control": EXPECTED, "beta": EXPECTED})
        self.assertEqual(self.bps["control"]["purpose"], "finite-same-parent-building-control-beta")
        self.assertFalse(self.bps["control"]["cancel_fixture"])

    def test_building_style_contract_replaces_rush_style(self):
        style = default_building_config()
        self.assertEqual(style["format"], "prism-building-style-v1")
        for arm in ("control", "beta"):
            self.assertEqual(self.bps[arm]["template"]["run"]["style"], style)
        self.assertNotEqual(self.bps["control"]["template"]["run"]["style"],
                            self.previous["template"]["run"]["style"])

    def test_opponent_mix_modes_and_action_seeds(self):
        for arm in ("control", "beta"):
            template, run = self.bps[arm]["template"], self.bps[arm]["template"]["run"]
            self.assertEqual(set(template["opponents"]), set(MIX))
            self.assertEqual(set(run["opponents"]), set(MIX))
            self.assertTrue(all(row["mode"] == "greedy" for row in template["opponents"].values()))
            for name, seed in (("prism-general-v011", "62041002"), ("balance-parent-v010", "62041003")):
                self.assertEqual(template["opponents"][name]["args"][-2:], ["--seed", seed])
            self.assertEqual(template["opponents"]["prism-v01"]["args"][-1], "51000001")
            self.assertEqual(template["opponents"]["heuristic-v031"]["args"][-1], "20260926")

    def test_paired_job_schedule_seed_range_and_mix(self):
        for arm in ("control", "beta"):
            jobs = [job for cycle in self.bps[arm]["template"]["cycles"] for job in cycle]
            self.assertEqual(len(jobs), 1024)
            self.assertEqual(len({job["job_id"] for job in jobs}), 1024)
            expected = [[{"job_id": f"m62-{arm}-c{c+1}-b{b}-s{s}", "actor": s,
                          "opponent_id": ORDER[b % 8], "environment_seed": 9631000 + c * 128 + b}
                         for b in range(128) for s in (0, 1)] for c in range(4)]
            self.assertEqual(self.bps[arm]["template"]["cycles"], expected)
            counts = {name: sum(job["opponent_id"] == name for job in jobs) for name in MIX}
            self.assertEqual(counts, MIX)
            seeds = {}
            for job in jobs:
                seeds.setdefault(job["environment_seed"], []).append(job["actor"])
            self.assertEqual(sorted(seeds), list(range(9631000, 9631512)))
            self.assertTrue(all(sorted(actors) == [0, 1] for actors in seeds.values()))

    def test_bounded_budget_and_resource_ceilings(self):
        for arm in ("control", "beta"):
            run, template = self.bps[arm]["template"]["run"], self.bps[arm]["template"]
            self.assertEqual(tuple(run["budget"][key] for key in
                                   ("max_cycles", "max_jobs", "max_attempts", "max_run_seconds",
                                    "max_storage_bytes")), (4, 1024, 1024, 28800, 32 * 1024 ** 3))
            self.assertEqual((template["limits"]["memory_bytes"], template["limits"]["campaign_cpu_seconds"],
                              template["limits"]["max_infra_retries"], run["cpu_threads"]),
                             (8 * 1024 ** 3, 40000, 0, 2))

    def test_validate_blueprints_rejects_drift(self):
        cases = {
            "label": lambda bps: bps["control"].update(model_label="Prism Beta v0.1.0 CANDIDATE"),
            "run_seed": lambda bps: bps["beta"]["template"]["run"].update(seed=62041002),
            "run_id": lambda bps: bps["beta"]["template"]["run"].update(run_id="m62-control-building"),
            "schedule_seed": lambda bps: bps["beta"]["template"]["cycles"][0][0].update(environment_seed=9631001),
            "schedule_count": lambda bps: bps["control"]["template"]["cycles"][3].pop(),
            "opponent_mode": lambda bps: bps["control"]["template"]["opponents"]["prism-v01"].update(mode="T1"),
            "action_seed": lambda bps: bps["control"]["template"]["opponents"]["prism-general-v011"]["args"].__setitem__(
                -1, "999"),
            "parent_action_seed": lambda bps: bps["control"]["template"]["opponents"]["balance-parent-v010"]
                ["args"].__setitem__(-1, "62041002"),
            "style": lambda bps: bps["control"]["template"]["run"]["style"].update(early_window_main_actions=13),
            "coefficients": lambda bps: bps["control"]["template"]["run"]["ppo"].update(style_beta=.3),
            "budget": lambda bps: bps["control"]["template"]["run"]["budget"].update(max_jobs=512),
            "limits": lambda bps: bps["control"]["template"]["limits"].update(memory_bytes=4 * 1024 ** 3),
            "cpu_threads": lambda bps: bps["control"]["template"]["run"].update(cpu_threads=4),
            "opponent_rename": lambda bps: bps["control"]["template"]["opponents"].update(
                {"prism-v02": bps["control"]["template"]["opponents"].pop("prism-v01")}),
            "weights": lambda bps: bps["control"].update(
                weight_hashes={"parent": "9" * 64, "general": "2" * 64, "initial": "3" * 64}),
        }
        for name, mutation in cases.items():
            with self.subTest(mutation=name):
                bps = copy.deepcopy(self.bps)
                mutation(bps)
                with self.assertRaises(ValueError):
                    m62.validate_blueprints(bps)
        for name, mutation in (("drop_arm", lambda bps: bps.pop("beta")),
                               ("extra_arm", lambda bps: bps.update(gamma=copy.deepcopy(bps["control"])))):
            with self.subTest(mutation=name):
                bps = copy.deepcopy(self.bps)
                mutation(bps)
                with self.assertRaises(ValueError):
                    m62.validate_blueprints(bps)

    def test_validate_blueprints_pins_job_identity(self):
        # Unlike M61, each arm's exact schedule (including job ids) is pinned;
        # normalization only serves the cross-arm identity/coefficients comparison.
        bps = copy.deepcopy(self.bps)
        for cycle in bps["control"]["template"]["cycles"]:
            for job in cycle:
                job["job_id"] = "renamed-" + job["job_id"]
        with self.assertRaisesRegex(ValueError, "schedule"):
            m62.validate_blueprints(bps)

    def test_evaluation_contract_exact_values(self):
        contract = m62.evaluation_contract()
        self.assertEqual(contract["status"], "NOT_RUN")
        self.assertEqual(contract["total_games"], 9280)
        self.assertEqual(contract["candidate_and_parent_mode"], "agent-prism-sample T1, action seed 62042001")
        self.assertEqual(contract["anchor_modes"], {"heuristic-v031": "greedy", "prism-v01": "greedy",
                                                    "prism-general-v011": "T1, action seed 62042001"})
        self.assertEqual(contract["development"], {
            "seed_start": 9636000, "seed_end": 9636031, "blocks": 32, "total_games": 576,
            "models": ["base", "control", "beta"], "anchors": ANCHORS, "action_seed": 62042001,
            "selection": "descriptive only; final c4 fixed before samples; no tuning"})
        acceptance = contract["acceptance"]
        self.assertEqual(acceptance["seed_start"], 9641000)
        self.assertEqual(acceptance["seed_end"], 9641255)
        self.assertEqual(acceptance["direct_seed_end"], 9641511)
        self.assertEqual((acceptance["blocks"], acceptance["direct_blocks"]), (256, 512))
        self.assertEqual(acceptance["action_seed"], 62042001)
        self.assertEqual((acceptance["models"], acceptance["anchors"]),
                         (["base", "control", "beta"], ANCHORS))
        self.assertEqual(acceptance["anchor_total_games"], 4608)
        self.assertEqual((acceptance["direct_parent_games"], acceptance["between_arms_games"],
                          acceptance["direct_alpha_games"]), (2048, 1024, 1024))
        self.assertEqual((acceptance["direct_total_games"], acceptance["total_games"],
                          acceptance["total_physical_budget"]), (4096, 8704, 11328))
        self.assertEqual(acceptance["direct_pairs"],
                         [["control", "base"], ["beta", "base"], ["beta", "control"], ["beta", "alpha"]])
        self.assertEqual((acceptance["bootstrap_rng_seed"], acceptance["bootstrap_samples"],
                          acceptance["family_alpha"]), (62049999, 20000, .05))
        self.assertEqual((acceptance["simultaneous_comparisons"], acceptance["one_sided_claims"],
                          acceptance["interval_sides"], acceptance["lower_quantile"]),
                         (9, 9, "one-sided", .05 / 9))
        self.assertTrue(acceptance["unused_for_training"] and acceptance["control_cohort_required"])

    def test_evaluation_contract_gates_and_required_gates_exact(self):
        acceptance = m62.evaluation_contract()["acceptance"]
        self.assertEqual(acceptance["gates"], GATES)
        self.assertEqual(acceptance["required_gates"], REQUIRED_GATES)

    def test_evaluation_contract_returns_fresh_copies(self):
        contract = m62.evaluation_contract()
        contract["acceptance"]["gates"]["beta/general_anchor"] = 99
        contract["acceptance"]["required_gates"]["control"].append("injected")
        self.assertEqual(m62.evaluation_contract()["acceptance"]["gates"], GATES)
        self.assertEqual(m62.evaluation_contract()["acceptance"]["required_gates"], REQUIRED_GATES)

    def test_draft_config_schema_bindings_and_never_freezes(self):
        config = self.draft_config()
        self.assertEqual((config["format"], config["status"]),
                         ("m62-prism-beta-building-v1", "DESIGNED"))
        self.assertEqual(config["base_model"], {"name": "Prism Balance v0.1.0", **synthetic_assets()["parent"]})
        self.assertEqual(config["alpha_model"], {"name": "Prism Alpha v0.1.4", **synthetic_assets()["alpha"]})
        self.assertEqual(set(config["assets"]), {"parent", "general", "initial", "fixtures", "alpha"})
        training = config["training"]
        self.assertEqual(training["execution_order"], ["control", "beta"])
        self.assertEqual(set(training["arms"]), {"control", "beta"})
        self.assertEqual([training[key] for key in ("cycles", "games_per_cycle", "games_per_arm",
                                                    "total_games", "run_seed")],
                         [4, 256, 1024, 2048, 62041001])
        self.assertEqual(training["mix_per_arm"], MIX)
        self.assertEqual(training["opponent_action_seeds"],
                         {"prism-general-v011": 62041002, "balance-parent-v010": 62041003})
        self.assertEqual(training["opponents_action_mode"], "greedy")
        self.assertEqual(training["action_mode"], "categorical-T1 learned policy")
        self.assertEqual(config["seed_reservations"], m62.RESERVATIONS)
        self.assertEqual(config["resources"], {
            "memory_bytes": 8 * 1024 ** 3, "cpu_quota_percent": 200, "cpu_seconds": 40000,
            "cpu_threads": 2, "storage_bytes": 32 * 1024 ** 3, "wall_seconds_from_initialization": 28800,
            "infrastructure_retries": 0, "wall_deadline_survives_transfer": True,
            "scope": "per training arm", "serial_execution": True})
        self.assertEqual(config["serial_resources"],
                         {"memory_bytes": 1024 ** 3, "cpu_quota_percent": 20, "wall_seconds": 61200})
        self.assertEqual(config["evaluation"]["total_games"], 9280)
        self.assertEqual(config["evaluation"]["native_path_and_sha256"], self.previous_config["runtime"]["engine"])
        self.assertEqual(config["runtime"]["cloud_root"], m62.CLOUD)
        self.assertEqual(config["heuristic_identity"], self.previous_config["heuristic_identity"])
        for arm, bp in self.bps.items():
            row = training["arms"][arm]
            self.assertEqual(row["blueprint_path"], f"benchmarks/m62-prism-{arm}-building.train.json")
            self.assertEqual(row["blueprint_sha256"], m62.serialized_sha(bp))
            self.assertEqual(row["blueprint_identity"], m62.identity(bp))
            self.assertEqual(row["campaign"], m62.CLOUD + f"/campaigns/m62-{arm}-building-g0")
            self.assertEqual(row["line"], f"m62-{arm}-building")
            self.assertEqual(row["identity"], {"label": LABELS[arm], "status": "CANDIDATE", "published": False})
            self.assertEqual(row["ppo"], bp["template"]["run"]["ppo"])
            self.assertEqual(row["style"], bp["template"]["run"]["style"])
        self.assertIn("no retry or extension", config["constraints"])
        self.assertIn("create beta only after control stopped committed", config["constraints"])

    def test_validate_config_rejects_config_drift(self):
        config = self.draft_config()
        mutations = {
            "format": lambda c: c.update(format="m62-old-v0"),
            "parent_hash": lambda c: c["base_model"].update(sha256="0" * 64),
            "parent_name": lambda c: c["base_model"].update(name="Prism Alpha v0.1.4"),
            "alpha_hash": lambda c: c["alpha_model"].update(sha256="1" * 64),
            "asset_set": lambda c: c["assets"].pop("fixtures"),
            "execution_order": lambda c: c["training"].update(execution_order=["beta", "control"]),
            "training_counts": lambda c: c["training"].update(total_games=2047),
            "run_seed": lambda c: c["training"].update(run_seed=62041002),
            "mix": lambda c: c["training"].update(mix_per_arm=dict(MIX, **{"prism-v01": 129})),
            "action_seeds": lambda c: c["training"].update(
                opponent_action_seeds={"prism-general-v011": 62041002, "balance-parent-v010": 62041004}),
            "reservations": lambda c: c["seed_reservations"].__setitem__(0, (9631000, 9631510, "m62-training-paired-arms")),
            "resources": lambda c: c["resources"].update(infrastructure_retries=1),
            "serial_resources": lambda c: c["serial_resources"].update(wall_seconds=61300),
            "evaluation_gate": lambda c: c["evaluation"]["acceptance"]["gates"].update({"beta/general_anchor": -.08}),
            "evaluation_total": lambda c: c["evaluation"].update(total_games=9281),
            "cloud_root": lambda c: c["runtime"].update(cloud_root="/home/ubuntu/other"),
        }
        for name, mutation in mutations.items():
            with self.subTest(mutation=name):
                drifted = copy.deepcopy(config)
                mutation(drifted)
                with self.assertRaises(ValueError):
                    m62.validate_config(drifted, self.bps)
        m62.validate_config(config, self.bps)  # unmutated contract still passes

    def test_validate_config_rejects_blueprint_binding_drift(self):
        config = self.draft_config()
        for name, mutation in (
                ("schedule", lambda bp: bp["template"]["cycles"][0][0].update(environment_seed=9631001)),
                ("style", lambda bp: bp["template"]["run"]["style"].update(global_use_cap=25)),
                ("weights", lambda bp: bp.update(weight_hashes=dict(EXPECTED, parent="8" * 64))),
                ("ppo", lambda bp: bp["template"]["run"]["ppo"].update(lr=6e-05))):
            with self.subTest(mutation=name):
                bps = copy.deepcopy(self.bps)
                mutation(bps["beta"])
                with self.assertRaises(ValueError):
                    m62.validate_config(config, bps)

    def test_dynamic_seed_ranges(self):
        rows = m62.dynamic_seed_ranges({"acceptance": {"seed_start": 100, "seed_end": 110, "direct_seed_end": 120},
                                        "cycles": [[{"environment_seed": 300}]],
                                        "seed_reservations": [[400, 410, "held"]]}, "config")
        self.assertIn((100, 120, "config/acceptance"), rows)
        self.assertTrue(any(lo == 300 == hi for lo, hi, _ in rows))
        self.assertTrue(any(lo == 400 and hi == 410 for lo, hi, _ in rows))

    def test_validate_final_progress(self):
        progress = {"cycle": 4, "attempts": 1024, "jobs": list(range(256)),
                    "consumed": ["a", "b", "c", "d"]}
        m62.validate_final_progress(progress)
        for name, mutation in (("cycle", {"cycle": 3}), ("attempts", {"attempts": 1023}),
                               ("jobs", {"jobs": list(range(255))}),
                               ("consumed", {"consumed": ["a", "b", "c"]}),
                               ("duplicate_consumed", {"consumed": ["a", "b", "c", "c"]})):
            with self.subTest(mutation=name):
                with self.assertRaises(ValueError):
                    m62.validate_final_progress(dict(progress, **mutation))

    def test_prepare_fails_closed_before_any_write(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "benchmarks").mkdir()
            (project / "benchmarks" / "m62-prism-beta-building.config.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "already reserved"):
                m62.prepare(project)
            created = sorted(path.relative_to(project).as_posix() for path in project.rglob("*"))
            self.assertEqual(created, ["benchmarks", "benchmarks/m62-prism-beta-building.config.json"])
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):  # missing helper-readiness receipt
                m62.prepare(Path(directory))
            self.assertEqual(list(Path(directory).rglob("*")), [])


if __name__ == "__main__":
    unittest.main()
