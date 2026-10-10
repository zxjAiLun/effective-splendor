#!/usr/bin/env python3
"""M50 fixed v0.3.1 teacher replacement; reuse the frozen TB72 model and arena."""
from __future__ import annotations

import argparse
import concurrent.futures as futures
import json
import subprocess
import sys
import time
from pathlib import Path

import m50_reserve_target_binding_round as common

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "benchmarks/m50-aran-v031-teacher-v1.config.json"


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def root_dir(config: dict) -> Path:
    return ROOT / config["artifact_root"]


def verify_identities(config: dict) -> None:
    for section, path_key, hash_key in [
        ("teacher", "program", "sha256"),
        ("evaluation", "candidate_exe", "candidate_exe_sha256"),
        ("evaluation", "opponent_exe", "opponent_exe_sha256"),
        ("evaluation", "metrics_exe", "metrics_exe_sha256"),
        ("training", "pretrained", "pretrained_sha256"),
        ("training", "parent_published_weights", "parent_published_sha256"),
    ]:
        assert common.sha256(ROOT / config[section][path_key]) == config[section][hash_key], path_key
    for rel, expected in config["source_sha256"].items():
        assert common.sha256(ROOT / rel) == expected, f"frozen source changed: {rel}"


def teacher_seeds(config: dict) -> list[int]:
    spec = config["teacher"]
    seeds = list(range(spec["seed_start"], spec["seed_start"] + spec["games"]))
    assert len(seeds) == len(set(seeds)) == 2000
    used = set(seeds)
    for phase in ("smoke", "screen", "confirmation"):
        part = config["evaluation"][phase]
        values = set(range(part["seed_start"], part["seed_start"] + part["seed_count"]))
        assert not used.intersection(values), "training/evaluation seed overlap"
        used.update(values)
    return seeds


def teacher_match_config(config: dict, seed: int) -> dict:
    teacher = {"program": str(ROOT / config["teacher"]["program"]), "args": list(config["teacher"]["args"])}
    return {"game_id": f"{config['round_id']}-teacher-{seed}", "seed": seed,
            "agents": [teacher.copy(), teacher.copy()], "handshake_timeout_ms": 10000,
            "move_timeout_ms": 60000, "shutdown_grace_ms": 2000}


def logged_command(directory: Path, name: str, argv: list[str], timeout: int | None = None):
    receipt = directory / f"{name}.command.json"
    if receipt.exists():
        raise FileExistsError(f"refusing repeated operation {receipt}")
    metadata = {"argv": argv, "cwd": str(ROOT), "status": "RUNNING", "started_unix": time.time()}
    common.write_json(receipt, metadata)
    started = time.perf_counter()
    try:
        with (directory / f"{name}.log").open("x", encoding="utf-8") as log:
            result = subprocess.run(argv, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
        metadata.update(status="FINISHED", returncode=result.returncode, seconds=time.perf_counter() - started)
        receipt.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        if result.returncode:
            raise RuntimeError(f"{name} exited {result.returncode}; see {directory / (name + '.log')}")
        return metadata
    except BaseException as error:
        if metadata["status"] == "RUNNING":
            metadata.update(status="INTERRUPTED", error=repr(error), seconds=time.perf_counter() - started)
            receipt.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        raise


def run_teacher_game(config: dict, seed: int) -> dict:
    directory = root_dir(config) / "teacher" / f"seed-{seed}"
    directory.mkdir(exist_ok=False)
    cfg = teacher_match_config(config, seed)
    common.write_json(directory / "match-config.json", cfg)
    engine = str(ROOT / config["evaluation"]["candidate_exe"])
    logged_command(directory, "arena", [engine, "run-match", "--config", str(directory / "match-config.json"),
                                      "--report-out", str(directory / "arena-report.json"),
                                      "--replay-out", str(directory / "match-replay.json")], 300)
    report = read(directory / "arena-report.json")
    assert report["outcome"]["status"] == "completed" and report["player_count"] == 2
    assert report["game_id"] == cfg["game_id"]
    logged_command(directory, "verify", [engine, "verify-replay", "--input", str(directory / "match-replay.json")], 120)
    return {"seed": seed, "group": "teacher-v031-selfplay", "replay_path": str((directory / "match-replay.json").relative_to(ROOT)).replace("\\", "/"),
            "replay_sha256": common.sha256(directory / "match-replay.json"),
            "report_sha256": common.sha256(directory / "arena-report.json"),
            "config_sha256": common.sha256(directory / "match-config.json"),
            "teacher_sha256": config["teacher"]["sha256"], "engine_sha256": config["evaluation"]["candidate_exe_sha256"],
            "split": "val" if seed % 5 == 0 else "train"}


def collect(config: dict) -> dict:
    verify_identities(config)
    seeds = teacher_seeds(config)
    out = root_dir(config) / "teacher"
    out.mkdir(exist_ok=False)
    common.write_json(out / "planned-seeds.json", seeds)
    rows, errors = [], []
    with (out / "completion.jsonl").open("x", encoding="utf-8") as journal:
        def record(row):
            journal.write(json.dumps(row) + "\n")
            journal.flush()
        # The first real corpus game is the collection smoke, counted only once.
        try:
            first = run_teacher_game(config, seeds[0])
            rows.append(first)
            record({"status": "completed", **first})
        except Exception as error:
            record({"status": "error", "seed": seeds[0], "error": repr(error)})
            raise
        print("teacher collection smoke passed (1/2000)", flush=True)
        remaining = iter(seeds[1:])
        with futures.ThreadPoolExecutor(max_workers=config["workers"]) as pool:
            pending = {}
            while pending or not errors:
                if not errors:
                    while len(pending) < config["workers"]:
                        seed = next(remaining, None)
                        if seed is None:
                            break
                        pending[pool.submit(run_teacher_game, config, seed)] = seed
                if not pending:
                    break
                done, _ = futures.wait(pending, return_when=futures.FIRST_COMPLETED)
                for future in done:
                    seed = pending.pop(future)
                    try:
                        row = future.result()
                        rows.append(row)
                        record({"status": "completed", **row})
                    except Exception as error:
                        failure = {"status": "error", "seed": seed, "error": repr(error)}
                        errors.append(failure)
                        record(failure)
                if len(rows) % 100 == 0 or len(rows) == len(seeds):
                    print(f"teacher: {len(rows)}/2000 valid, errors={len(errors)}", flush=True)
    rows.sort(key=lambda row: row["seed"])
    common.write_json(out / "manifest.json", {"rows": rows, "errors": errors})
    if errors:
        raise RuntimeError("teacher collection stopped; no automatic retries or replacement seeds")
    assert [row["seed"] for row in rows] == seeds
    verify_identities(config)
    return {"status": "PASS", "teacher_games": len(rows)}


def source_rows(config: dict) -> list[dict]:
    collection = read(root_dir(config) / "teacher/manifest.json")
    assert not collection["errors"]
    rows = collection["rows"]
    assert [row["seed"] for row in rows] == teacher_seeds(config)
    reference = ROOT / config["dataset"]["coev_reference_manifest"]
    assert common.sha256(reference) == config["dataset"]["coev_reference_manifest_sha256"]
    prefix = config["dataset"]["coev_dir"].rstrip("/") + "/"
    old = [item for item in read(reference) if item["path"].startswith(prefix)]
    assert len(old) == 2000
    teacher_set = set(teacher_seeds(config))
    combined = list(rows)
    for item in old:
        replay_path = ROOT / item["path"]
        assert common.sha256(replay_path) == item["sha256"], f"old coev changed: {replay_path}"
        seed = read(replay_path)["seed"]
        assert seed not in teacher_set
        combined.append({"group": "retained-coev", "seed": seed, "replay_path": item["path"],
                         "replay_sha256": item["sha256"], "split": "val" if seed % 5 == 0 else "train"})
    assert len({r["replay_path"] for r in combined}) == len(combined) == 4000
    for row in rows:
        replay_path = ROOT / row["replay_path"]
        assert common.sha256(replay_path) == row["replay_sha256"]
        replay = read(replay_path)
        assert replay["seed"] == row["seed"] and replay["player_count"] == 2
    return combined


def extract(config: dict) -> dict:
    verify_identities(config)
    sources = source_rows(config)
    provenance = root_dir(config) / "provenance"
    common.write_json(provenance / "source-replays.json", sources)
    destination = ROOT / config["training"]["data_dir"]
    if destination.exists():
        raise FileExistsError(f"refusing existing dataset {destination}")
    argv = [str(ROOT / config["evaluation"]["candidate_exe"]), "m50-extract-replays",
            "--replays-dir", str(root_dir(config) / "teacher"), "--replays-dir", str(ROOT / config["dataset"]["coev_dir"]),
            "--semantic", "--reserve-target-binding", "--val-modulus", "5", "--val-remainder", "0",
            "--out-dir", str(destination)]
    return logged_command(provenance, "extract", argv, 600)


def check_data(config: dict) -> dict:
    import numpy as np
    directory = ROOT / config["training"]["data_dir"]
    manifest = read(directory / "manifest.json")
    sources = source_rows(config)
    assert manifest["total_replays_parsed"] == 4000
    assert (manifest["observation_width"], manifest["action_width"], manifest["action_representation"]) == (368, 72, "semantic-reserve-target-v1")
    assert (manifest["val_modulus"], manifest["val_remainder"]) == (5, 0)
    declared = {Path(p).resolve() for p in json.loads(manifest["source_replays_dir"])}
    assert declared == {(root_dir(config) / "teacher").resolve(), (ROOT / config["dataset"]["coev_dir"]).resolve()}
    assert {r["seed"] for r in sources if r["split"] == "train"}.isdisjoint(r["seed"] for r in sources if r["split"] == "val")
    result = {"status": "PASS", "manifest_sha256": common.sha256(directory / "manifest.json"),
              "source_manifest_sha256": common.sha256(root_dir(config) / "provenance/source-replays.json"), "splits": {}}
    for split in ("train", "val"):
        meta = manifest["splits"][split]
        assert meta["game_count"] == sum(r["split"] == split for r in sources)
        obs = np.memmap(directory / split / "obs.f32", dtype="<f4", mode="r").reshape(-1, 368)
        actions = np.memmap(directory / split / "actions.f32", dtype="<f4", mode="r").reshape(-1, 72)
        offsets = np.memmap(directory / split / "action_offsets.u64", dtype="<u8", mode="r")
        chosen = np.memmap(directory / split / "chosen_action.u32", dtype="<u4", mode="r")
        values = np.memmap(directory / split / "values.f32", dtype="<f4", mode="r").reshape(-1, 3)
        assert len(obs) == len(chosen) == len(values) == meta["step_count"]
        assert len(actions) == meta["total_actions"] and len(offsets) == len(obs) + 1
        assert offsets[0] == 0 and offsets[-1] == len(actions)
        assert (offsets[1:] > offsets[:-1]).all() and (chosen < offsets[1:] - offsets[:-1]).all()
        assert np.isin(values[:, 0], [0.0, 0.5, 1.0]).all() and (values[:, 2] >= 0).all()
        for array in (obs, actions, values):
            for start in range(0, len(array), 100000):
                assert np.isfinite(array[start:start + 100000]).all()
        hashes = {}
        for filename, key in [("obs.f32", "obs_sha256"), ("actions.f32", "actions_sha256"),
                              ("action_offsets.u64", "action_offsets_sha256"), ("chosen_action.u32", "chosen_action_sha256"),
                              ("values.f32", "values_sha256")]:
            hashes[filename] = common.sha256(directory / split / filename)
            assert hashes[filename] == meta[key]
        result["splits"][split] = {"games": meta["game_count"], "decisions": len(obs), "actions": len(actions), "hashes": hashes}
    assert sum(s["decisions"] for s in result["splits"].values()) == manifest["total_steps"]
    common.write_json(root_dir(config) / "provenance/data-check.json", result)
    return result


def train(config: dict) -> dict:
    verify_identities(config)
    import torch
    sys.path.insert(0, str(ROOT / "training/m17_gpu"))
    from m50_train_mortal_actor_critic import MortalActorCriticNet, load_pretrained_weights
    assert torch.cuda.is_available(), "this round requires CUDA; no silent CPU training"
    spec = config["training"]
    check = read(root_dir(config) / "provenance/data-check.json")
    assert check["status"] == "PASS" and common.sha256(ROOT / spec["data_dir"] / "manifest.json") == check["manifest_sha256"]
    model = MortalActorCriticNet(act_dim=72, hidden_dim=256, num_blocks=2)
    parent = load_pretrained_weights(model, ROOT / spec["pretrained"])
    assert parent["migration"] == [] and parent["parent_action_dim"] == 72
    original = torch.load(ROOT / spec["pretrained"], weights_only=True, map_location="cpu")
    assert model.state_dict().keys() == original.keys()
    assert all(torch.equal(value, original[name]) for name, value in model.state_dict().items())
    parent["all_parameters_exact"] = True
    common.write_json(root_dir(config) / "provenance/initialization.json", parent)
    del model, original
    argv = [spec["python"], "-u", "-B", str(ROOT / spec["script"]), "--data-dir", str(ROOT / spec["data_dir"]),
            "--out-dir", str(ROOT / spec["out_dir"]), "--pretrained", str(ROOT / spec["pretrained"]),
            "--hidden-dim", "256", "--num-blocks", "2", "--epochs", "10", "--batch-size", "512",
            "--accumulation-steps", "4", "--lr", "0.0003"]
    return logged_command(root_dir(config) / "provenance", "training", argv)


def select(config: dict, config_path: Path) -> dict:
    verify_identities(config)
    import numpy as np
    import torch
    sys.path.insert(0, str(ROOT / "training/m17_gpu"))
    from m50_train_mortal_actor_critic import MortalActorCriticNet, SemanticDataset, load_pretrained_weights
    torch.set_num_threads(1)
    run = ROOT / config["training"]["out_dir"]
    summary = read(run / "training-summary.json")
    assert len(summary["history"]) == summary["epochs"] == 10 and summary["seed"] == 50000001
    assert not summary["critic_backbone_grad"] and summary["migration"] == []
    assert summary["parent_sha256"] == config["training"]["pretrained_sha256"]
    assert summary["best_epoch"] == max(summary["history"], key=lambda r: r["val_top1"])["epoch"]
    state = torch.load(run / "best_model.pt", weights_only=True, map_location="cpu")
    exported = read(run / "mortal_actor_critic_weights.json")
    assert (exported["action_dim"], exported["action_representation"], exported["is_argmax"]) == (72, "semantic-reserve-target-v1", True)
    for name, tensor in state.items():
        assert torch.isfinite(tensor).all() and torch.equal(tensor, torch.tensor(exported[name], dtype=tensor.dtype))
    parent, selected = (MortalActorCriticNet(act_dim=72, hidden_dim=256, num_blocks=2) for _ in range(2))
    load_pretrained_weights(parent, ROOT / config["training"]["pretrained"])
    selected.load_state_dict(state, strict=True)
    data = SemanticDataset(ROOT / config["training"]["data_dir"] / "val")
    obs, actions, parents, *_ = data.get_batch(np.array([0, 1, 2]), torch.device("cpu"))
    fixture = {"obs": obs.tolist(), "actions72": actions.tolist(), "parent_idx": parents.tolist(), "cases": {}}
    for name, model, path in [("parent72", parent, ROOT / config["training"]["parent_published_weights"]),
                               ("selected72", selected, run / "mortal_actor_critic_weights.json")]:
        model.eval()
        with torch.no_grad():
            h = model.entity_backbone(obs)
            for block in model.state_res_blocks:
                h = block(h)
            logits, _, _ = model(obs, actions, parents)
        fixture["cases"][name] = {"weights": str(path), "action_dim": 72, "state_h": h.tolist(), "adv_logits": logits.tolist()}
    out = root_dir(config) / "provenance"
    common.write_json(out / "selected-fixture.json", fixture)
    identity = {"config_sha256": common.sha256(config_path), "checkpoint_sha256": common.sha256(run / "best_model.pt"),
                "weights_sha256": common.sha256(run / "mortal_actor_critic_weights.json"),
                "training_summary_sha256": common.sha256(run / "training-summary.json"),
                "best_epoch": summary["best_epoch"], "pt_export_exact": True}
    common.write_json(out / "selected-model.json", identity)
    return identity


def evaluate(config: dict, phase: str, config_path: Path = DEFAULT_CONFIG) -> dict:
    verify_identities(config)
    if phase not in ("smoke", "screen", "confirmation"):
        raise ValueError(phase)
    # The frozen helper checks its own DEFAULT_CONFIG; bind it only in this process.
    previous = common.DEFAULT_CONFIG
    common.DEFAULT_CONFIG = config_path
    try:
        return common.evaluate(config, phase)
    finally:
        common.DEFAULT_CONFIG = previous


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("collect", "extract", "check-data", "train", "select", "smoke", "screen", "confirmation"))
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    config = read(args.config)
    assert config["status"] == "FROZEN"
    if args.operation == "select":
        result = select(config, args.config)
    elif args.operation in ("smoke", "screen", "confirmation"):
        result = evaluate(config, args.operation, args.config)
    else:
        result = {"collect": collect, "extract": extract, "check-data": check_data, "train": train}[args.operation](config)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
