"""Versioned host binding and full committed-state handoff; no relaxed checks."""
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import time
import uuid

from .common import component, digest, identity, lock, numerical_identity, package_identity, read, write

MAX_BUNDLE_BYTES = 4 * 1024**3


def bind(blueprint, host):
    from .engine.io import canonical_hash
    from .engine.ppo.execution import validate_spec
    if blueprint["format"] != "prism-portable-blueprint-v1":
        raise ValueError("unknown portable blueprint")
    if host["code_identity"] != package_identity():
        raise ValueError("portable package drift")
    assets = host["assets"]
    for name, item in assets.items():
        if digest(item["path"]) != item["sha256"]:
            raise ValueError("native host asset drift: " + name)
    mappings = {name: item["path"] for name, item in assets.items()}
    mappings.update({name + "_sha256": item["sha256"] for name, item in assets.items()})

    def expand(value):
        if isinstance(value, str) and value.startswith("@"):
            return mappings[value[1:]]
        if isinstance(value, dict):
            return {expand(k): expand(v) for k, v in value.items()}
        if isinstance(value, list):
            return [expand(x) for x in value]
        return value
    spec = expand(copy.deepcopy(blueprint["template"]))
    for name, expected in blueprint["weight_hashes"].items():
        if assets[name]["sha256"] != expected:
            raise ValueError("logical weight identity changed")
    spec["run"]["opponents"] = {name: canonical_hash(row) for name, row in spec["opponents"].items()}
    spec["run"]["auditor_sha256"] = spec["arena"]["sha256"]
    content = copy.deepcopy(spec)
    content["run"].pop("arena_contract_sha256", None)
    spec["run"]["arena_contract_sha256"] = canonical_hash(content)
    return validate_spec(spec)


def assert_owner(root, host_id=None, nonce=None):
    owner = read(Path(root) / "ownership.json")
    if owner["status"] != "ACTIVE":
        raise ValueError("campaign writing authority has been released")
    expected_host = host_id or os.environ.get("PRISM_PPO_HOST_ID")
    expected_nonce = nonce or os.environ.get("PRISM_PPO_OWNER_NONCE")
    if owner["host_id"] != expected_host or owner["nonce"] != expected_nonce:
        raise ValueError("campaign host/ownership token mismatch")
    if owner["code_identity"] != package_identity():
        raise ValueError("campaign executable source drift")
    if identity(read(Path(root) / "blueprint.json")) != owner["blueprint_identity"]:
        raise ValueError("campaign logical blueprint drift")
    return owner


def state_digest(value):
    import numpy as np
    import torch
    h = hashlib.sha256()
    def visit(x):
        if isinstance(x, torch.Tensor):
            x = x.detach().cpu().contiguous()
            h.update(("tensor:" + str(x.dtype) + ":" + str(tuple(x.shape))).encode())
            h.update(x.numpy().tobytes())
        elif isinstance(x, np.ndarray):
            h.update(("array:" + str(x.dtype) + ":" + str(x.shape)).encode())
            h.update(np.ascontiguousarray(x).tobytes())
        elif isinstance(x, dict):
            h.update(b"dict{")
            for k in sorted(x, key=lambda k: (type(k).__name__, repr(k))):
                visit(k)
                visit(x[k])
            h.update(b"}")
        elif isinstance(x, (list, tuple)):
            h.update(type(x).__name__.encode() + b"[")
            for item in x:
                visit(item)
            h.update(b"]")
        else:
            h.update((type(x).__name__ + ":" + repr(x) + ";").encode())
    visit(value)
    return h.hexdigest()


def state_fingerprints(state):
    keys = ("cycle", "global_step", "update_attempts", "attempts", "decisions",
            "all_jobs", "consumed", "schedule", "jobs", "cursor", "order", "started_at")
    return {"model": state_digest(state["model"]), "optimizer": state_digest(state["optimizer"]),
            "rng": state_digest(state["rng"]), "progress": state_digest({k: state[k] for k in keys})}


def validate_launch_ledger(ledger, state, spec):
    """Committed run progress and its physical-work ledger must agree."""
    if ledger["format"] != "prism-ppo-launch-ledger-v1" or ledger["failed"]:
        raise ValueError("failed or unknown launch ledger cannot be transferred")
    attempts = ledger["attempts"]
    if len(attempts) != state["attempts"]:
        raise ValueError("launch attempt budget disagrees with run")
    completed = [row["job"]["job_id"] for row in attempts.values() if row["status"] == "COMPLETE"]
    if len(set(completed)) != len(completed) or set(completed) != set(state["all_jobs"]):
        raise ValueError("completed launch jobs disagree with committed run")
    if sum(row.get("charged_decisions", 0) for row in attempts.values()) != ledger["physical_decisions"]:
        raise ValueError("physical decision ledger mismatch")
    if sum(bool(row.get("retry_charged")) for row in attempts.values()) != ledger["retries"]:
        raise ValueError("physical retry ledger mismatch")
    if not 0 <= ledger["physical_decisions"] <= spec["limits"]["max_physical_decisions"]:
        raise ValueError("physical decision budget exhausted")
    if not 0 <= ledger["retries"] <= spec["limits"]["max_infra_retries"]:
        raise ValueError("physical retry budget exhausted")


def create(root, blueprint, host, line):
    from .engine.ppo.arena import Campaign
    root = Path(root)
    component(line)
    if root.exists():
        raise ValueError("new campaign path already exists")
    campaign = Campaign.create(root, bind(blueprint, host))
    write(root / "blueprint.json", blueprint)
    owner = {"format": "prism-portable-owner-v1", "line": line, "host_id": host["host_id"],
             "generation": 0, "nonce": uuid.uuid4().hex, "status": "ACTIVE",
             "blueprint_identity": identity(blueprint), "code_identity": package_identity()}
    write(root / "ownership.json", owner)
    write(root / "resource-ledger.json", {"format": "prism-portable-resources-v1", "cpu_spent": 0.0,
                                         "sessions": [], "deadline": campaign.run.state["started_at"]
                                         + blueprint["template"]["run"]["budget"]["max_run_seconds"]})
    write(root / "initialization.json", {"status": "PASS", "commit": campaign.run.parent,
                                        "state": state_fingerprints(campaign.run.state),
                                        "run_identity": campaign.run.identity, "new_games": 0})
    return owner


def prepare_handoff(root, host, destination, archive):
    from .engine.ppo.coordinator import Run
    from .engine.ppo.store import CommitStore
    root = Path(root)
    component(destination)
    with lock(root / "control"):
        owner = read(root / "ownership.json")
        assert_owner(root, host["host_id"], owner["nonce"])
        status_path = root / "control/status.json"
        if status_path.exists() and read(status_path)["status"] in ("STARTING", "RUNNING"):
            raise ValueError("stop the owned worker before handoff")
        run = Run.open(root / "run")
        if run.state["phase"] not in ("READY", "COMMITTED"):
            raise ValueError("cross-host import requires a committed cycle boundary")
        if run.state["phase"] == "COMMITTED" and len(run.state["consumed"]) != run.state["cycle"]:
            raise ValueError("committed consumption count mismatch")
        spec = read(root / "contract.json")
        launch_store = CommitStore(root / "launch-ledger", spec["run"]["arena_contract_sha256"])
        launch_head, launch_state = launch_store.load()
        validate_launch_ledger(launch_state, run.state, spec)
        # Fencing is persistent before any bundle can be consumed elsewhere.
        run.pause(True)
        owner.update(status="RELEASED", destination=destination, transfer_id=uuid.uuid4().hex)
        write(root / "ownership.json", owner)
        ticket = {"format": "prism-portable-transfer-v1", "transfer_id": owner["transfer_id"],
                  "source_owner": owner, "destination": destination, "generation": owner["generation"] + 1,
                  "source_commit": run.parent, "source_run_identity": run.identity,
                  "source_runtime": run.runtime, "source_code_identity": package_identity(),
                  "source_numerical_identity": numerical_identity(),
                  "source_launch_commit": launch_head, "source_launch_identity": launch_store.identity,
                  "source_launch_state": state_digest(launch_state),
                  "state": state_fingerprints(run.state), "issued_at": time.time()}
        write(root / "transfer.json", ticket)
        files = {}
        for p in sorted(root.rglob("*")):
            if p.is_symlink():
                raise ValueError("symlink in trusted checkpoint package")
            if p.is_file() and "control" not in p.relative_to(root).parts and p.name != "writer.lock":
                files[str(p.relative_to(root)).replace("\\", "/")] = digest(p)
        if sum((root / p).stat().st_size for p in files) > MAX_BUNDLE_BYTES:
            raise ValueError("checkpoint package exceeds fixed maximum")
        manifest = {"format": "prism-portable-bundle-v1", "ticket": ticket, "files": files}
        archive = Path(archive)
        if archive.exists():
            raise ValueError("handoff archive must be new")
        archive.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive, "w:gz", compresslevel=1) as stream:
            import io
            data = (json.dumps(manifest, sort_keys=True) + "\n").encode()
            info = tarfile.TarInfo("manifest.json")
            info.size = len(data)
            stream.addfile(info, io.BytesIO(data))
            for name in files:
                stream.add(root / name, arcname="campaign/" + name, recursive=False)
        return {"archive": str(archive), "sha256": digest(archive), "transfer_id": owner["transfer_id"],
                "destination": destination, "state": ticket["state"]}


def unpack_verified(archive, expected_hash, directory):
    if digest(archive) != expected_hash:
        raise ValueError("transfer archive hash mismatch")
    directory = Path(directory)
    if directory.exists():
        raise ValueError("import staging path already exists")
    with tarfile.open(archive) as stream:
        members = stream.getmembers()
        names = [m.name for m in members]
        if len(names) != len(set(names)) or len(names) > 100000:
            raise ValueError("duplicate or excessive archive members")
        for m in members:
            p = PurePosixPath(m.name)
            if m.name != p.as_posix() or p.is_absolute() or ".." in p.parts or "\\" in m.name or ":" in m.name:
                raise ValueError("unsafe archive path")
            if not m.isfile():
                raise ValueError("non-file checkpoint archive member")
        if sum(m.size for m in members) > MAX_BUNDLE_BYTES:
            raise ValueError("archive expands past fixed budget")
        if "manifest.json" not in names:
            raise ValueError("missing checkpoint manifest")
        manifest = json.load(stream.extractfile("manifest.json"))
        expected = {"manifest.json"} | {"campaign/" + x for x in manifest["files"]}
        if set(names) != expected or manifest["format"] != "prism-portable-bundle-v1":
            raise ValueError("checkpoint archive inventory mismatch")
        directory.mkdir(parents=True)
        for m in members:
            if m.name == "manifest.json":
                continue
            name = m.name.removeprefix("campaign/")
            data = stream.extractfile(m).read()
            if hashlib.sha256(data).hexdigest() != manifest["files"][name]:
                raise ValueError("checkpoint member hash mismatch")
            p = directory / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
    return manifest


def import_handoff(archive, expected_hash, host):
    from .engine.io import canonical_hash
    from .engine.ppo.coordinator import Run, STATE_KEYS
    from .engine.ppo.runtime import capture_rng, restore_rng
    from .engine.ppo.store import CommitStore
    root = Path(host["root"])
    stage = root / "imports" / uuid.uuid4().hex
    manifest = unpack_verified(archive, expected_hash, stage)
    ticket = manifest["ticket"]
    component(ticket["transfer_id"])
    if ticket["destination"] != host["host_id"] or ticket["source_code_identity"] != package_identity():
        raise ValueError("transfer target/source package mismatch")
    if read(stage / "transfer.json") != ticket or read(stage / "ownership.json") != ticket["source_owner"]:
        raise ValueError("transfer ticket/source owner mismatch")
    if ticket["source_owner"]["status"] != "RELEASED":
        raise ValueError("active source cannot be imported")
    blueprint = read(stage / "blueprint.json")
    if identity(blueprint) != ticket["source_owner"]["blueprint_identity"]:
        raise ValueError("portable training semantics changed")
    old_config = read(stage / "run/config.json")
    if ticket["source_numerical_identity"] != numerical_identity():
        raise ValueError("numerical training/encoding/audit source changed")
    expected_identity = canonical_hash({"config": old_config, "runtime": ticket["source_runtime"],
                                        "source": ticket["source_numerical_identity"]})
    if expected_identity != ticket["source_run_identity"]:
        raise ValueError("source config/runtime/code identity mismatch")
    source = CommitStore(stage / "run", ticket["source_run_identity"])
    head, state = source.load()
    if head != ticket["source_commit"] or set(state) != STATE_KEYS:
        raise ValueError("source committed state identity/schema mismatch")
    if state["runtime"] != ticket["source_runtime"] or state["identity"] != ticket["source_run_identity"]:
        raise ValueError("source state identity/runtime mismatch")
    if state["phase"] not in ("READY", "COMMITTED") or not state["paused"]:
        raise ValueError("source was not stopped at a committed boundary")
    if state_fingerprints(state) != ticket["state"]:
        raise ValueError("full state/progress drift")
    if state["cycle"] != len(state["consumed"]) or len(set(state["consumed"])) != len(state["consumed"]):
        raise ValueError("source consumption/progress mismatch")
    old_spec = read(stage / "contract.json")
    if ticket["source_launch_identity"] != old_config["arena_contract_sha256"]:
        raise ValueError("source launch identity mismatch")
    launch_head, launch_state = CommitStore(stage / "launch-ledger", ticket["source_launch_identity"]).load()
    if launch_head != ticket["source_launch_commit"] or state_digest(launch_state) != ticket["source_launch_state"]:
        raise ValueError("source launch ledger drift")
    validate_launch_ledger(launch_state, state, old_spec)
    target = root / "campaigns" / (component(ticket["source_owner"]["line"]) + "-g" + str(ticket["generation"]))
    registry = root / "transfer-registry"
    with lock(registry):
        used = registry / (ticket["transfer_id"] + ".json")
        if used.exists() or target.exists():
            raise ValueError("duplicate transfer ticket or destination")
        # Claim first. A failed import remains inspectable and cannot be replayed silently.
        write(used, {"status": "CLAIMED", "target": str(target), "archive_sha256": expected_hash})
        create(target, blueprint, host, ticket["source_owner"]["line"])
        importing_owner = read(target / "ownership.json")
        importing_owner["status"] = "IMPORTING"
        write(target / "ownership.json", importing_owner)
        run = Run.open(target / "run")
        if run.runtime["device"] != "cpu" or ticket["source_runtime"]["device"] != "cpu":
            raise ValueError("cross-host restore supports CPU state only")
        if run.runtime["torch"].split("+")[0] != ticket["source_runtime"]["torch"].split("+")[0]:
            raise ValueError("Torch numerical version must match for portable resume")
        for name in ("python", "numpy", "dtype", "cpu_threads", "batch_shape", "amp", "tf32"):
            if run.runtime[name] != ticket["source_runtime"][name]:
                raise ValueError("unsupported portable runtime transition: " + name)
        # All raw objects and old commit ancestors remain in staging for provenance.
        # Copy content-addressed objects, never rewrite a previously consumed shard.
        for p in (stage / "run/objects").iterdir():
            if p.is_file():
                q = target / "run/objects" / p.name
                if q.exists() and digest(q) != digest(p):
                    raise ValueError("checkpoint object collision")
                if not q.exists():
                    shutil.copyfile(p, q)
        with run.store.lock():
            run.state = copy.deepcopy(state)
            run.state.update(identity=run.identity, runtime=run.runtime, paused=False)
            # A consumed active-batch cache is local-runtime evidence. It is retained
            # in the source package, while a committed target starts its next cycle fresh.
            run.state.update(snapshot=None, batch=None)
            run.learner.model.load_state_dict(state["model"], strict=True)
            run.learner.load_optimizer(copy.deepcopy(state["optimizer"]))
            restore_rng(state["rng"])
            if state_digest(capture_rng()) != ticket["state"]["rng"]:
                raise ValueError("portable RNG restoration mismatch")
            run.state["metrics"].append({"event": "portable_runtime_transition",
                                         "source_commit": head, "source_runtime": ticket["source_runtime"],
                                         "target_runtime": run.runtime, "transfer_id": ticket["transfer_id"]})
            run._commit()
        after = state_fingerprints(run.state)
        # Progress intentionally clears only the completed cycle's local cache.
        for name in ("model", "optimizer", "rng"):
            if after[name] != ticket["state"][name]:
                raise ValueError("portable numeric state was not preserved: " + name)
        for name in ("cycle", "global_step", "update_attempts", "attempts", "decisions",
                     "all_jobs", "consumed", "started_at"):
            if state_digest(run.state[name]) != state_digest(state[name]):
                raise ValueError("portable budget/progress changed: " + name)
        # Rebind only the ledger's host-specific envelope. All physical work,
        # retry charges and completed-attempt records remain byte-equivalent state.
        new_spec = read(target / "contract.json")
        target_launch = CommitStore(target / "launch-ledger", new_spec["run"]["arena_contract_sha256"])
        with target_launch.lock():
            target_launch.commit(copy.deepcopy(launch_state), expected_parent=target_launch.head())
        _, restored_launch = target_launch.load()
        if state_digest(restored_launch) != ticket["source_launch_state"]:
            raise ValueError("portable physical-work ledger was not preserved")
        write(target / "resource-ledger.json", read(stage / "resource-ledger.json"))
        owner = read(target / "ownership.json")
        owner.update(status="ACTIVE", generation=ticket["generation"], transfer_id=ticket["transfer_id"])
        write(target / "ownership.json", owner)
        receipt = {"status": "PASS", "source_commit": head, "target_commit": run.parent,
                   "source_state": ticket["state"], "target_state": after, "target": str(target),
                   "source_launch_state": ticket["source_launch_state"],
                   "target_launch_state": state_digest(restored_launch),
                   "physical_decisions": restored_launch["physical_decisions"],
                   "physical_retries": restored_launch["retries"],
                   "source_runtime": ticket["source_runtime"], "target_runtime": run.runtime,
                   "source_archive_sha256": expected_hash, "source_archive": str(Path(archive).resolve()),
                   "retained_source": str(stage), "new_games": 0, "new_optimizer_steps": 0}
        write(target / "migration.json", receipt)
        write(used, {"status": "IMPORTED", "target": str(target), "receipt": str(target / "migration.json")})
        return receipt
