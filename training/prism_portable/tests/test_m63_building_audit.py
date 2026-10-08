"""M63 audit fail-closed checks on synthetic drifted trees; no games or training."""
import copy
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
import prism_building_audit_m63 as audit
import prism_building_prepare_m63 as prepare
from training.prism_portable.common import identity
from training.prism_portable.engine.ppo.building import default_building_config
from training.prism_portable.engine.ppo.building_timed import default_timed_building_config, _timed_utility
from training.prism_portable.engine.ppo.model import new_model

PARENT = "225daf49e8746576b1edc3508ca0454715e5454529fea53dc7dfeb9043cf01f1"
EXPECTED = {"parent": PARENT, "general": "2" * 64, "initial": "3" * 64}
CONTRACT_SHA = identity(default_building_config())


def building_summary(contract_sha, *, games=256, units=None, utility=None, mean_utility=None,
                     mean_auc=.4, fmt="prism-building-targets-v1", timed=False):
    rows = []
    for index in range(games):
        use_units = 1 if units is None else units
        source = {"format": "prism-building-profile-v1", "building_use_units": use_units,
                  "building_utility": use_units / 24 if utility is None else utility,
                  "early_bonus_auc12": .4, "main_actions": 24,
                  "building_observed_use_units": 1, "building_use_units_before_global_cap": 1,
                  "investments": [{"credited_uses": 1, "observed_uses": 1,
                                   "use_main_actions": [3], "printed_vp": 0,
                                   "acquired_main": 2}]}
        if timed:
            rows.append(dict(source, format="prism-building-timed-profile-v1", building_v1_profile=source,
                             **_timed_utility(source, default_timed_building_config())))
        else:
            rows.append(source)
    summary = {"format": fmt, "games": rows, "style_contract_sha256": contract_sha,
            "mean_building_utility": sum(r["building_utility"] for r in rows) / len(rows)
            if mean_utility is None else mean_utility,
            "mean_early_bonus_auc12": mean_auc}
    if timed:
        summary["mean_time_weighted_utility"] = sum(r["time_weighted_utility"] for r in rows)/len(rows)
    return summary


def beta_events(pairs):
    """Build style_extracted metric rows from explicit (cycle, summary) pairs."""
    return {"metrics": [{"event": "style_extracted", "cycle": cycle, "artifact": f"style-c{cycle}",
                         "style_contract_sha256": summary["style_contract_sha256"],
                         "mean_building_utility": summary["mean_building_utility"],
                         "mean_early_bonus_auc12": summary["mean_early_bonus_auc12"],
                         **({"mean_time_weighted_utility": summary["mean_time_weighted_utility"]}
                            if "mean_time_weighted_utility" in summary else {})}
                        for cycle, summary in pairs]}


class FakeStore:
    def __init__(self, summaries):
        self.summaries = summaries

    def get_json(self, path):
        return self.summaries[path]


class M63AuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        previous = audit.read(ROOT / "benchmarks/m61-prism-balance-ab.train.json")
        cls.bps = prepare.build_blueprints(previous, EXPECTED)

    def progress_fixture(self):
        state = {"phase": "COMMITTED", "cycle": 4, "attempts": 1024, "all_jobs": list(range(1024)),
                 "consumed": list("abcd"), "decisions": 40, "global_step": 4,
                 "update_attempts": 4, "metrics": []}
        summaries = []
        for cycle in range(1, 5):
            step = {"event": "optimizer_step", "cycle": cycle, "global_step": cycle, "optimizer_applied": True}
            state["metrics"].extend([
                {"event": "sealed", "cycle": cycle, "batch_id": "abcd"[cycle - 1], "decisions": 10},
                {"event": "optimizer_attempt", "cycle": cycle, "attempt": cycle}, step,
                {"event": "passes_complete", "cycle": cycle, "batch_id": "abcd"[cycle - 1]}])
            summaries.append({"cycle": cycle, "stop_reason": "passes_complete", "updates": [step],
                              "optimizer_steps": 1, "update_attempts": 1,
                              "groups": {"all": {"games": 256, "decisions": 10}}})
        return state, summaries

    def slots(self, enabled):
        model = new_model(style_enabled=enabled)
        optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad])
        saved = optimizer.state_dict()
        params = [p for p in model.parameters() if p.requires_grad]
        saved["state"] = {index: {"step": torch.tensor(7.), "exp_avg": torch.zeros_like(p),
                                  "exp_avg_sq": torch.zeros_like(p)}
                          for index, p in enumerate(params)}
        return model, optimizer, saved

    def test_matched_blueprints_accept_built_arms(self):
        audit.matched_blueprints(self.bps["control"], self.bps["beta"])

    def test_matched_blueprints_rejects_drift_and_missing_bindings(self):
        mutations = {
            "seed": lambda bp: bp["template"]["run"].update(seed=62041002),
            "schedule": lambda bp: bp["template"]["cycles"][0][0].update(environment_seed=9631001),
            "action_seed": lambda bp: bp["template"]["opponents"]["prism-general-v011"]["args"].__setitem__(-1, "7"),
            "style": lambda bp: bp["template"]["run"]["style"].update(format="wrong-style-v1"),
            "budget": lambda bp: bp["template"]["run"]["budget"].update(max_cycles=3),
            "ppo": lambda bp: bp["template"]["run"]["ppo"].update(lr=6e-05),
            "opponents": lambda bp: bp["template"]["opponents"].update(
                {"other": bp["template"]["opponents"].pop("prism-v01")}),
            "weights": lambda bp: bp.update(weight_hashes=dict(EXPECTED, parent="9" * 64)),
        }
        for name, mutation in mutations.items():
            with self.subTest(mutation=name):
                beta = copy.deepcopy(self.bps["beta"])
                mutation(beta)
                with self.assertRaises(ValueError):
                    audit.matched_blueprints(self.bps["control"], beta)
        with self.assertRaises((ValueError, KeyError)):
            audit.matched_blueprints(self.bps["control"], {"template": self.bps["beta"]["template"]})

    def test_stopped_passes_on_well_formed_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "control").mkdir()
            row = {"status": "STOPPED_COMMITTED", "alive": False,
                   "resources": {"returncode": 0, "stop_reason": None, "wall_seconds": 100,
                                 "cpu_seconds": 10, "peak_memory_bytes": 100}}
            (root / "control/status.json").write_text(json.dumps(row), encoding="utf-8")
            self.assertEqual(audit.stopped(root), row)

    def test_stopped_fails_closed_on_drifted_or_missing_receipts(self):
        cases = {
            "failed_status": {"status": "FAILED"},
            "still_running": {"status": "RUNNING", "alive": True},
            "alive_flag": {"alive": True},
            "returncode": {"resources": {"returncode": 1}},
            "stop_reason": {"resources": {"stop_reason": "oom"}},
            "wall_ceiling": {"resources": {"wall_seconds": 28801}},
            "unmeasured_wall": {"resources": {"wall_seconds": 0}},
            "cpu_ceiling": {"resources": {"cpu_seconds": 40001}},
            "memory_ceiling": {"resources": {"peak_memory_bytes": 8 * 1024 ** 3 + 1}},
            "memory_unmeasured": {"resources": {"peak_memory_bytes": None}},
        }
        for name, override in cases.items():
            with self.subTest(mutation=name):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    (root / "control").mkdir()
                    row = {"status": "STOPPED_COMMITTED", "alive": False,
                           "resources": {"returncode": 0, "stop_reason": None, "wall_seconds": 100,
                                         "cpu_seconds": 10, "peak_memory_bytes": 100}}
                    for key, value in override.items():
                        if key == "resources":
                            row["resources"].update(value)
                        else:
                            row[key] = value
                    (root / "control/status.json").write_text(json.dumps(row), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        audit.stopped(root)
        with tempfile.TemporaryDirectory() as directory:  # missing status receipt
            with self.assertRaises(FileNotFoundError):
                audit.stopped(Path(directory))
        with tempfile.TemporaryDirectory() as directory:  # owned process still alive
            root = Path(directory)
            (root / "control").mkdir()
            row = {"status": "STOPPED_COMMITTED", "pid": 12, "launch_token": "owned", "alive": False,
                   "resources": {"returncode": 0, "stop_reason": None, "wall_seconds": 100,
                                 "cpu_seconds": 10, "peak_memory_bytes": 100}}
            (root / "control/status.json").write_text(json.dumps(row), encoding="utf-8")
            with patch("training.prism_portable.control.owned_alive", return_value=True):
                with self.assertRaisesRegex(ValueError, "still alive"):
                    audit.stopped(root)

    def test_both_arms_require_four_style_extraction_events(self):
        for arm, config, fmt, timed in (("control", default_building_config(), "prism-building-targets-v1", False),
                                        ("beta", default_timed_building_config(), "prism-building-timed-targets-v1", True)):
            digest = identity(config)
            summaries = {f"style-c{cycle}": building_summary(digest, fmt=fmt, timed=timed)
                         for cycle in (1, 2, 3, 4)}
            result = audit.style_evidence(beta_events([(c, summaries[f"style-c{c}"]) for c in (1, 2, 3, 4)]),
                                          FakeStore(summaries), config, arm)
            self.assertEqual(result["style_extraction_events"], 4)
            with self.assertRaises(ValueError):
                audit.style_evidence({"metrics": []}, FakeStore(summaries), config, arm)

    def test_timed_utility_rejects_malformed_actual_use_evidence(self):
        config = default_timed_building_config()
        valid = {"format": "prism-building-profile-v1", "main_actions": 4,
                 "building_observed_use_units": 2, "building_use_units": 2,
                 "investments": [{"acquired_main": 1, "observed_uses": 2, "credited_uses": 2,
                                  "use_main_actions": [2, 4]}]}
        self.assertGreater(_timed_utility(valid, config)["time_weighted_utility"], 0)
        for bad in (
            dict(valid, main_actions=0),
            dict(valid, investments=[dict(valid["investments"][0], acquired_main=5)]),
            dict(valid, investments=[dict(valid["investments"][0], use_main_actions=[4, 2])]),
            dict(valid, investments=[dict(valid["investments"][0], use_main_actions=[2, 2])]),
            dict(valid, building_use_units=1),
            dict(valid, investments=None),
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    _timed_utility(bad, config)

    def test_style_evidence_beta_passes_on_well_formed_summaries(self):
        timed_config = default_timed_building_config()
        digest = identity(timed_config)
        summaries = {f"style-c{cycle}": building_summary(digest, mean_auc=.4 + cycle / 100,
                                                         fmt="prism-building-timed-targets-v1", timed=True)
                     for cycle in (1, 2, 3, 4)}
        result = audit.style_evidence(beta_events([(c, summaries[f"style-c{c}"]) for c in (1, 2, 3, 4)]),
                                      FakeStore(summaries), timed_config, "beta")
        self.assertEqual(result["style_extraction_events"], 4)
        self.assertEqual(sorted(result["artifacts"]), ["1", "2", "3", "4"])
        self.assertEqual(result["style_contract"], timed_config)

    def test_style_evidence_beta_fails_closed_on_drift(self):
        timed_config = default_timed_building_config()
        timed_sha = identity(timed_config)
        good = {f"style-c{cycle}": building_summary(timed_sha, mean_auc=.4 + cycle / 100,
                                                     fmt="prism-building-timed-targets-v1", timed=True)
                for cycle in (1, 2, 3, 4)}

        def swap_cycles(summaries):
            summaries["style-c1"], summaries["style-c2"] = summaries["style-c2"], summaries["style-c1"]
            return summaries

        def game_count(summaries):
            summaries["style-c3"] = building_summary(CONTRACT_SHA, mean_auc=.43, games=255)
            return summaries

        def contract_sha(summaries):
            summaries["style-c4"] = building_summary("0" * 64, mean_auc=.44)
            return summaries

        def unit_range(summaries):
            summaries["style-c1"] = building_summary(CONTRACT_SHA, mean_auc=.41, units=25)
            return summaries

        def utility_binding(summaries):
            summaries["style-c1"] = building_summary(CONTRACT_SHA, mean_auc=.41, units=12, utility=.5)
            return summaries

        def investment_cap(summaries):
            drifted = building_summary(CONTRACT_SHA, mean_auc=.42)
            for profile in drifted["games"]:
                profile["investments"] = [dict(profile["investments"][0], credited_uses=4)]
            summaries["style-c2"] = drifted
            return summaries

        def printed_vp(summaries):
            drifted = building_summary(CONTRACT_SHA, mean_auc=.42)
            for profile in drifted["games"]:
                profile["investments"] = [dict(profile["investments"][0], printed_vp=2, credited_uses=0,
                                               observed_uses=0)]
            summaries["style-c2"] = drifted
            return summaries

        def acquired_main(summaries):
            drifted = building_summary(CONTRACT_SHA, mean_auc=.42)
            for profile in drifted["games"]:
                profile["investments"] = [dict(profile["investments"][0], acquired_main=13)]
            summaries["style-c2"] = drifted
            return summaries

        def mean_drift(summaries):
            summaries["style-c3"] = building_summary(CONTRACT_SHA, mean_auc=.43, mean_utility=.9)
            return summaries

        def auc_drift(summaries):
            summaries["style-c4"] = building_summary(CONTRACT_SHA, mean_auc=.99)
            return summaries

        store_mutations = {"cycle_swap": swap_cycles, "game_count": game_count,
                           "contract_sha": contract_sha, "unit_range": unit_range,
                           "utility_binding": utility_binding, "investment_cap": investment_cap,
                           "printed_vp": printed_vp, "acquired_main": acquired_main,
                           "mean_drift": mean_drift, "auc_drift": auc_drift}
        events = [(c, good[f"style-c{c}"]) for c in (1, 2, 3, 4)]
        for name, mutation in store_mutations.items():
            with self.subTest(mutation=name):
                summaries = mutation(copy.deepcopy(good))
                with self.assertRaises(ValueError):
                    audit.style_evidence(beta_events(events), FakeStore(summaries), timed_config, "beta")
        for name, pairs in (("missing_cycle", [(c, good[f"style-c{c}"]) for c in (1, 2, 3)]),
                            ("cycle_order", [(1, good["style-c1"]), (2, good["style-c2"]),
                                             (4, good["style-c3"]), (3, good["style-c4"])])):
            with self.subTest(mutation=name):
                with self.assertRaises(ValueError):
                    audit.style_evidence(beta_events(pairs), FakeStore(good), timed_config, "beta")

    def test_progress_evidence_passes_and_rejects_drift(self):
        state, summaries = self.progress_fixture()
        config = {"budget": {"max_optimizer_steps": 10, "max_update_attempts": 10, "max_decisions": 100}}
        self.assertEqual(audit.progress_evidence(state, config, summaries)["global_step"], 4)
        mutations = {
            "phase": {"phase": "FAILED"},
            "cycle": {"cycle": 3},
            "attempts": {"attempts": 1023},
            "job_count": {"all_jobs": list(range(1023))},
            "duplicate_jobs": {"all_jobs": list(range(1023)) + [0]},
            "consumed": {"consumed": list("abc")},
            "duplicate_consumed": {"consumed": list("abcc")},
            "decisions": {"decisions": 39},
        }
        for name, override in mutations.items():
            with self.subTest(mutation=name):
                with self.assertRaises(ValueError):
                    audit.progress_evidence(dict(state, **override), config, summaries)
        for name, summaries_mutation in (
                ("missing_summary", lambda rows: rows[:3]),
                ("game_count", lambda rows: [dict(rows[0], groups={"all": {"games": 255, "decisions": 10}})] + rows[1:]),
                ("stop_reason", lambda rows: [dict(rows[1], stop_reason="kl_stop")] + rows[2:]),
                ("batch_binding", lambda rows: [dict(rows[0], updates=[])] + rows[1:])):
            with self.subTest(mutation=name):
                with self.assertRaises(ValueError):
                    audit.progress_evidence(state, config, summaries_mutation(summaries))

    def test_optimizer_evidence_control_and_beta(self):
        for arm in ("control", "beta"):
            model, optimizer, saved = self.slots(True)
            result = audit.optimizer_evidence(model, optimizer, saved, arm, 7)
            self.assertEqual(result["optimizer_slots"], 36)
            self.assertTrue(result["style_enabled"])
            self.assertTrue(all(result["style_parameters_require_grad"]))

    def test_optimizer_evidence_requires_style_enabled_in_both_arms(self):
        for arm in ("control", "beta"):
            model, optimizer, saved = self.slots(False)
            with self.assertRaises(ValueError):
                audit.optimizer_evidence(model, optimizer, saved, arm, 7)

    def test_compare_values_rejects_drift(self):
        for left, right in ((.2, .3), (float("nan"), float("nan")), ({"x": 1}, {"y": 1}),
                            ([1], [1, 2]), ("a", 1), (True, 1)):
            with self.subTest(pair=(left, right)):
                with self.assertRaises(ValueError):
                    audit.compare_values(left, right, [])
        errors = []
        audit.compare_values({"a": [1.0, {"b": 2}]}, {"a": [1.0, {"b": 2}]}, errors)
        self.assertEqual(len(errors), 2)

    def test_load_contract_rejects_unfrozen_and_incomplete_projects(self):
        previous_train = audit.read(ROOT / "benchmarks/m61-prism-balance-ab.train.json")
        bps = prepare.build_blueprints(previous_train, EXPECTED)
        previous_config = audit.read(ROOT / "benchmarks/m61-prism-alpha-balance-ab.config.json")
        alpha = audit.read(ROOT / "benchmarks/m61-prism-alpha-v0.1.4.model.json")["weights_sha256"]
        assets = {"parent": {"path": "synthetic-parent.json", "sha256": PARENT},
                  "general": {"path": "synthetic-general.json", "sha256": "2" * 64},
                  "initial": {"path": "synthetic-initial.json", "sha256": "3" * 64},
                  "fixtures": {"path": "synthetic-fixtures.jsonl", "sha256": "4" * 64},
                  "alpha": {"path": "synthetic-alpha.json", "sha256": alpha},
                  "previous_beta": {"path": "synthetic-beta.json", "sha256": prepare.PREVIOUS_BETA}}
        config = prepare.build_draft_config(previous_config, bps, assets)
        self.assertEqual(config["status"], "DESIGNED")
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "benchmarks").mkdir(parents=True)
            config_path = project / "benchmarks" / "m63-prism-beta-timed-building.config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not frozen before sampling"):
                audit.load_contract(project, "control")
            frozen = copy.deepcopy(config)
            frozen["status"] = "FROZEN_BEFORE_FIRST_GAME"
            config_path.write_text(json.dumps(frozen), encoding="utf-8")
            with self.assertRaises(FileNotFoundError):  # missing host.json fails closed
                audit.load_contract(project, "control")

    def test_project_context_restores_cwd_and_sys_path(self):
        before = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                with audit.project_context(directory) as project:
                    self.assertEqual(project, Path(directory).resolve())
                    self.assertEqual(Path.cwd(), Path(directory).resolve())
                    raise RuntimeError("boom")
            except RuntimeError:
                pass
            self.assertEqual(Path.cwd(), before)
            self.assertNotIn(str(Path(directory).resolve()), sys.path)


if __name__ == "__main__":
    unittest.main()
