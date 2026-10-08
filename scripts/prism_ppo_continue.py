"""One-time, hash-bound continuation at a completed PPO campaign boundary.

Trusted local checkpoints only. Read the source without Run.open/writer locks;
import model/AdamW/learner RNG, never source trajectories or resource budgets.
Normal recovery remains Run.open on the new run and never calls this again.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import torch

from training.prism.export import load_weights
from training.prism.io import canonical_hash, read_json, sha256_file, tensor_identity, write_json
from training.prism.ppo.arena import Campaign
from training.prism.ppo.coordinator import source_identity, validate_config
from training.prism.ppo.execution import check_assets, validate_spec
from training.prism.ppo.model import new_model
from training.prism.ppo.runtime import capture_rng, configure, restore_rng
from training.prism.ppo.store import CommitStore

FORMAT = "prism-ppo-continuation-v1"
KEYS = {"format", "authorized_by", "contract_sha256", "source_run", "source_identity",
        "source_commit", "source_payload_sha256", "source_config_sha256", "source_sha256",
        "initializer_sha256", "source_policy_tensor_sha256", "inherited_optimizer_steps"}


def state_digest(value):
    """Stable exact digest for nested optimizer/RNG state, including array bytes."""
    digest = hashlib.sha256()
    def visit(item):
        if isinstance(item, torch.Tensor):
            array = item.detach().cpu().contiguous().numpy()
            digest.update(b"torch:" + str(item.dtype).encode())
            visit(array)
        elif isinstance(item, np.ndarray):
            digest.update(b"array:" + item.dtype.str.encode() + repr(item.shape).encode())
            digest.update(item.tobytes(order="C"))
        elif isinstance(item, dict):
            digest.update(b"dict{")
            for key in sorted(item, key=lambda k: (type(k).__name__, repr(k))):
                visit(key); visit(item[key])
            digest.update(b"}")
        elif isinstance(item, (list, tuple)):
            digest.update(type(item).__name__.encode() + b"[")
            for member in item:
                visit(member)
            digest.update(b"]")
        else:
            digest.update(type(item).__name__.encode() + b":" + repr(item).encode() + b";")
    visit(value)
    return digest.hexdigest()


def validate_source(spec, lineage):
    validate_spec(spec); check_assets(spec)
    if set(lineage) != KEYS or lineage["format"] != FORMAT or lineage["authorized_by"] != "user-continue-training":
        raise ValueError("continuation lineage schema/authorization")
    if canonical_hash(spec) != lineage["contract_sha256"]:
        raise ValueError("continuation contract drift")
    if sha256_file(__file__) != lineage["initializer_sha256"] or source_identity() != lineage["source_sha256"]:
        raise ValueError("continuation source/initializer drift")
    directory = Path(lineage["source_run"])
    if sha256_file(directory / "config.json") != lineage["source_config_sha256"]:
        raise ValueError("source config drift")
    config = read_json(directory / "config.json")
    store = CommitStore(directory, lineage["source_identity"])
    head, state = store.load()  # read-only: does not mkdir or acquire a writer lock
    if head != lineage["source_commit"]:
        raise ValueError("source final commit drift")
    record = read_json(directory / "commits" / (head + ".json"))
    if record["payload"] != lineage["source_payload_sha256"]:
        raise ValueError("source payload drift")
    from training.prism.ppo.coordinator import STATE_KEYS
    validate_config(config)
    if set(state) != STATE_KEYS or state["identity"] != lineage["source_identity"]:
        raise ValueError("source state schema/identity")
    runtime = configure(spec["run"]["device"], spec["run"]["cpu_threads"])
    if state["runtime"] != runtime:
        raise ValueError("continuation runtime mismatch")
    expected = canonical_hash({"config": config, "runtime": runtime, "source": source_identity()})
    if expected != lineage["source_identity"]:
        raise ValueError("source config/runtime/source identity mismatch")
    if state["phase"] != "COMMITTED" or state["cycle"] != config["budget"]["max_cycles"]:
        raise ValueError("source campaign must be fully committed")
    if len(state["consumed"]) != state["cycle"] or len(set(state["consumed"])) != state["cycle"]:
        raise ValueError("source consumed batches mismatch")
    if len(state["all_jobs"]) != config["budget"]["max_jobs"] or any(
            row["status"] != "COMPLETE" for row in state["jobs"].values()):
        raise ValueError("source completed jobs mismatch")
    for key in ("ppo", "opponents", "catalog_fingerprint", "device", "cpu_threads", "auditor_sha256"):
        if spec["run"][key] != config[key]:
            raise ValueError("continuation changed " + key)
    new_jobs = {j['job_id'] for cycle in spec['cycles'] for j in cycle}
    if new_jobs.intersection(state['all_jobs']):
        raise ValueError('continuation reused source job IDs')
    inherited = state["global_step"] + sum(m.get("inherited_optimizer_steps", 0)
        for m in state["metrics"] if m.get("event") == "continuation_initialized")
    if type(lineage["inherited_optimizer_steps"]) is not int or inherited != lineage["inherited_optimizer_steps"]:
        raise ValueError("inherited optimizer step mismatch")
    model = new_model(style_enabled=False, state_dict=state["model"])
    policy_hash = tensor_identity(model.policy.state_dict())
    if policy_hash != lineage["source_policy_tensor_sha256"] or policy_hash != tensor_identity(
            load_weights(spec["parent_weights"], expected_catalog_fingerprint=config["catalog_fingerprint"]).state_dict()):
        raise ValueError("source model/parent export tensor mismatch")
    from training.prism.ppo.learner import Learner
    learner = Learner(model, validate_config(config))
    learner.load_optimizer(copy.deepcopy(state["optimizer"]))
    steps = [slot["step"].item() for slot in learner.optimizer.state.values()]
    if not steps or any(step != inherited for step in steps):
        raise ValueError("source AdamW step mismatch")
    before = capture_rng()
    try:
        restore_rng(state["rng"])
        if state_digest(capture_rng()) != state_digest(state["rng"]):
            raise ValueError("source RNG roundtrip mismatch")
    finally:
        restore_rng(before)
    if store.head() != head:
        raise ValueError("source changed during read-only import")
    return state


def initialize(campaign_path, spec, lineage):
    state = validate_source(spec, lineage)
    campaign = Campaign.create(campaign_path, spec)
    run = campaign.run
    model = new_model(style_enabled=False, state_dict=state["model"]).to(run.config["device"])
    metadata = {"event": "continuation_initialized", "cycle": 0,
                "lineage_sha256": canonical_hash(lineage), "source_commit": lineage["source_commit"],
                "inherited_optimizer_steps": lineage["inherited_optimizer_steps"],
                "model_sha256": tensor_identity(state["model"]),
                "optimizer_state_sha256": state_digest(state["optimizer"]),
                "rng_sha256": state_digest(state["rng"]), "new_consumable_batches": 0}
    with run.store.lock():
        if run.state["phase"] != "READY" or run.state["global_step"] != 0:
            raise ValueError("continuation must precede all jobs/updates")
        run.learner.model.load_state_dict(model.state_dict(), strict=True)
        run.learner.load_optimizer(copy.deepcopy(state["optimizer"]))
        restore_rng(state["rng"])
        run.state["metrics"].append(metadata)
        run._commit()
    receipt = metadata | {"format": "prism-ppo-continuation-receipt-v1", "identity": run.identity,
                          "initial_commit": run.parent, "started_at": run.state["started_at"]}
    write_json(Path(campaign_path) / "continuation.json", lineage)
    write_json(Path(campaign_path) / "continuation-receipt.json", receipt)
    return receipt


def verify_initialization(campaign, lineage):
    """Check the committed origin on every normal resume; never re-import it."""
    campaign = Path(campaign)
    if read_json(campaign / "continuation.json") != lineage:
        raise ValueError("continuation lineage drift")
    head = read_json(campaign / "run" / "HEAD.json")
    _, state = CommitStore(campaign / "run", head["identity"]).load()
    origins = [m for m in state["metrics"] if m.get("event") == "continuation_initialized"]
    if len(origins) != 1 or origins[0]["lineage_sha256"] != canonical_hash(lineage):
        raise ValueError("missing/changed committed continuation origin")
    return origins[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--lineage", required=True)
    args = parser.parse_args()
    import json
    print(json.dumps(initialize(args.campaign, read_json(args.contract), read_json(args.lineage))), flush=True)


if __name__ == "__main__":
    main()
