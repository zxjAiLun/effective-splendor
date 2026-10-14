"""M79 dual-node fixed-reference evaluator; original M79 evaluator stays pinned.

The auxiliary node owns only the frozen base/style-reference shards. It has a
40,000 CPU-second reservation and zero infrastructure retries. Results return
to the control node with member SHA256s; only then may the control node run the
candidate grid and recover unfinished identities under the original 64-retry
authority.
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PLAN_REL = "benchmarks/m79-prism-mainline.execution-plan.json"
STATE_REL = "execution-revisions/dual-dispatch-r1.json"
REV_DIR_REL = "execution-revisions/dual-dispatch-r1"
STATE_FORMAT = "prism-m79-dual-dispatch-r1"
TRANSFER_FORMAT = "prism-m79-dual-transfer-r1"
AUX_CPU_SECONDS = 40000
EVAL_CPU_SECONDS = 120000
CONTROL_EVAL_BASE_SECONDS = 80000
INFRA_EXTRA_LIMIT = 64
SEATS_PER_SEED = 2
FIXED_INPUTS = (
    "inputs/parent.json", "inputs/style-reference.json", "inputs/general.json",
    "inputs/balance.json", "inputs/alpha.json", "inputs/beta.json",
    "inputs/released-alpha.json", "inputs/latest-alpha.json",
    "inputs/latest-balance.json", "bin/splendor",
)
RUNTIME_SOURCES = (
    "scripts/prism_m79_evaluate.py", "scripts/prism_m79_run.py",
    "scripts/prism_bounded_eval.py", "scripts/prism_eval_failure_guard.py",
    "scripts/prism_notebook_arena.py", "scripts/prism_ppo_fixed_eval.py",
    "scripts/prism_dsw_ppo_process.py", "training/prism_portable/common.py",
    "training/prism_portable/processes.py",
    "training/prism_portable/engine/ppo/processes.py",
)
SOURCE_MANIFEST_CANDIDATES = (
    "source-members.json",
    "local-artifacts/prism/m79-mainline/source-members.json",
)


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(canonical(value) + b"\n")
    os.replace(tmp, path)


def schedule(plan: dict) -> list[dict]:
    """Expand the frozen 32-seed blocks without consulting candidate weights."""
    e = plan["evaluation"]
    block = int(e["shard_seed_blocks"])
    groups = []
    groups.extend((actor, opponent, *bounds)
                  for actor in e["common_actors"]
                  for opponent, bounds in e["common_seed_by_opponent"].items())
    groups.extend((actor, opponent, *bounds)
                  for actor in e["coverage_actors"]
                  for opponent, bounds in e["coverage_seed_by_opponent"].items())
    groups.append((e["direct"]["candidate"], e["direct"]["opponent"],
                   *e["direct"]["seed_range"]))
    rows = []
    for actor, opponent, lo, hi in groups:
        if (hi - lo + 1) % block:
            raise ValueError("M79 seed range is not divisible into frozen 32-seed shards")
        for start in range(lo, hi + 1, block):
            seeds = list(range(start, start + block))
            rows.append({"label": f"{actor}-{opponent}-{start}", "actor": actor,
                         "opponent": opponent, "seeds": seeds,
                         "planned_games": len(seeds) * len(e["seats"]),
                         "category": "independent"})
    labels = [r["label"] for r in rows]
    if len(labels) != len(set(labels)) or sum(r["planned_games"] for r in rows) != 12288:
        raise ValueError("frozen M79 12,288-game grid drift")
    return rows


def aux_labels(plan: dict, rows: list[dict] | None = None) -> set[str]:
    e = plan["evaluation"]
    rows = rows if rows is not None else schedule(plan)
    common = set(e["common_opponents"])
    coverage = set(e["coverage_seed_by_opponent"])
    result = {r["label"] for r in rows
              if r["actor"] in ("base", "style-reference")
              and ((r["opponent"] in common and r["actor"] in e["common_actors"])
                   or (r["actor"] == "base" and r["opponent"] in coverage
                       and "base" in e["coverage_actors"]))}
    if sum(r["planned_games"] for r in rows if r["label"] in result) != 7168:
        raise ValueError("fixed auxiliary grid must remain base=4096 + style-reference=3072")
    return result


def safe_member(name: str) -> str:
    if not isinstance(name, str) or not name or "\\" in name or "\x00" in name:
        raise ValueError("invalid transfer member path")
    p = PurePosixPath(name)
    if p.is_absolute() or any(part in ("", ".", "..") for part in p.parts):
        raise ValueError("unsafe transfer member path")
    if p.parts and ":" in p.parts[0]:
        raise ValueError("drive-qualified transfer path")
    return p.as_posix()


def make_bundle(output: Path, files: dict[str, bytes], metadata: dict) -> dict:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    members = {}
    normalized = {}
    for raw_name, data in files.items():
        name = safe_member(raw_name)
        if name in normalized or name == "transfer-manifest.json":
            raise ValueError("duplicate/reserved transfer path")
        if not isinstance(data, bytes):
            raise TypeError("bundle payload must be bytes")
        normalized[name] = data
        members[name] = sha_bytes(data)
    embedded = {"format": TRANSFER_FORMAT, "metadata": metadata,
                "members": members}
    tmp = output.with_name(output.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as z:
        for name in sorted(normalized):
            z.writestr(name, normalized[name])
        z.writestr("transfer-manifest.json", canonical(embedded))
    os.replace(tmp, output)
    receipt = {"format": TRANSFER_FORMAT, "sha256": sha_file(output),
               "bytes": output.stat().st_size, "member_count": len(members),
               "metadata": metadata}
    write_json(Path(str(output) + ".receipt.json"), receipt)
    return receipt


def verify_bundle(archive: Path, receipt_path: Path, expected: dict | None = None) -> tuple[dict, dict]:
    archive, receipt_path = Path(archive), Path(receipt_path)
    receipt = read_json(receipt_path)
    if (receipt.get("format") != TRANSFER_FORMAT
            or archive.stat().st_size != receipt.get("bytes")
            or sha_file(archive) != receipt.get("sha256")):
        raise ValueError("transfer archive/receipt SHA256 mismatch")
    with zipfile.ZipFile(archive) as z:
        infos = z.infolist()
        names = [i.filename for i in infos]
        if len(names) != len(set(names)) or "transfer-manifest.json" not in names:
            raise ValueError("duplicate or missing transfer manifest")
        for name in names:
            safe_member(name)
        manifest = json.loads(z.read("transfer-manifest.json"))
        members = manifest.get("members", {})
        if (manifest.get("format") != TRANSFER_FORMAT
                or set(names) != set(members) | {"transfer-manifest.json"}
                or len(members) != receipt.get("member_count")):
            raise ValueError("transfer member set mismatch")
        payload = {name: z.read(name) for name in members}
    for name, data in payload.items():
        if sha_bytes(data) != members[name]:
            raise ValueError("transfer member SHA256 mismatch: " + name)
    if expected is not None and manifest.get("metadata") != expected:
        raise ValueError("transfer metadata identity mismatch")
    if manifest.get("metadata") != receipt.get("metadata"):
        raise ValueError("receipt metadata mismatch")
    return manifest, payload


def started(output: Path) -> bool:
    output = Path(output)
    if any((output / name).exists() for name in
           ("ledger.json", "once-only.lock", "worker.log", "grid-status.json")):
        return True
    games = output / "games"
    return games.exists() and any(games.iterdir())


def partition(rows: list[dict], aux: set[str], started_labels: set[str]) -> tuple[list[dict], list[dict]]:
    labels = [r["label"] for r in rows]
    if len(labels) != len(set(labels)):
        raise ValueError("duplicate shard label")
    if not aux.issubset(set(labels)):
        raise ValueError("auxiliary shard outside frozen grid")
    auxiliary, control = [], []
    for row in rows:
        # Any touched shard remains with the control owner. This prevents a
        # second writer and lets the original M79 ledger decide recovery.
        if row["label"] in aux and row["label"] not in started_labels:
            auxiliary.append(row)
        else:
            control.append(row)
    return auxiliary, control


def semantic_config(value, root: Path):
    root = Path(root)
    prefixes = {str(root), root.as_posix(), str(root.resolve()), root.resolve().as_posix()}
    prefixes = sorted((p for p in prefixes if p and p != "."), key=len, reverse=True)
    def visit(item):
        if isinstance(item, dict):
            return {k: visit(v) for k, v in item.items()}
        if isinstance(item, list):
            return [visit(v) for v in item]
        if isinstance(item, str):
            for prefix in prefixes:
                item = item.replace(prefix, "$ROOT").replace(prefix.replace("\\", "/"), "$ROOT")
            return item
        return item
    return visit(value)


def semantic_sha(value, root: Path) -> str:
    return sha_bytes(canonical(semantic_config(value, root)))


def _runtime(root: Path):
    sys.path.insert(0, str(root))
    from scripts import prism_bounded_eval as b
    from scripts import prism_m79_evaluate as e
    from scripts import prism_m79_run as run
    from scripts import prism_notebook_arena as arena
    for module in (b, e, run, arena):
        module.ROOT = root
    b.legacy.ROOT = root
    b.fixed.ROOT = root
    e.b.ROOT = root
    e.arena.ROOT = root
    return b, e, run


def _load_state(root: Path) -> dict:
    state = read_json(root / STATE_REL)
    execution = read_json(root / "execution.json")
    budget = read_json(root / "round-budget.json")
    plan = read_json(root / PLAN_REL)
    if state.get("format") != STATE_FORMAT or state.get("adapter_sha256") != sha_file(Path(__file__)):
        raise ValueError("dual-dispatch adapter revision drift")
    if sha_file(root / "execution.json") != state["execution_sha256"]:
        raise ValueError("M79 execution identity drift")
    if sha_file(root / PLAN_REL) != state["plan_sha256"]:
        raise ValueError("M79 frozen schedule drift")
    if (sha_file(root / "round-budget.json") != state["round_budget_sha256"]
            or budget.get("execution_sha256") != state["execution_sha256"]
            or budget.get("deadline") != state["deadline"]):
        raise ValueError("original M79 deadline/budget drift")
    if execution.get("plan_sha256") != state["plan_sha256"]:
        raise ValueError("execution does not bind frozen M79 plan")
    return state


def _verify_bound_sources(root: Path, execution: dict) -> None:
    for rel, expected in execution.get("files", {}).items():
        safe_member(rel)
        path = root / rel
        if not path.is_file() or sha_file(path) != expected:
            raise ValueError("pinned source member drift: " + rel)


def _verify_aux_sources(root: Path, execution: dict) -> None:
    for rel, expected in execution.get("files", {}).items():
        rel = safe_member(rel)
        if rel.startswith(("campaigns/a/", "audits/a/")) or rel == "candidate-registry.json":
            continue
        path = root / rel
        if not path.is_file() or sha_file(path) != expected:
            raise ValueError("pinned auxiliary source member drift: " + rel)


def _existing_cpu(root: Path) -> float:
    ledger_cpu = 0.0
    for base in (root / "evaluation", root / "development"):
        if not base.exists():
            continue
        for path in base.glob("*/ledger.json"):
            ledger_cpu += float(read_json(path).get("consumed_cpu_seconds", 0.0))
    journal_cpu = 0.0
    journal = root / "pipeline/resources.json"
    if journal.exists():
        for row in read_json(journal):
            if row.get("category") != "evaluation_development":
                continue
            if row.get("state") == "RUNNING":
                raise ValueError("control evaluation stage still owns the evaluation budget")
            journal_cpu += float(row.get("cpu_seconds", row.get("cpu_reserved", 0.0)))
    # Stage process-tree accounting includes grid CPU plus controller overhead;
    # use the larger view instead of summing the same work twice.
    return max(ledger_cpu, journal_cpu)


def prepare(root: Path = ROOT) -> dict:
    root = Path(root).resolve()
    state_path = root / STATE_REL
    if state_path.exists():
        return _load_state(root)
    b, e, run = _runtime(root)
    plan_path = root / PLAN_REL
    execution_path = root / "execution.json"
    budget_path = root / "round-budget.json"
    plan, execution, budget = read_json(plan_path), read_json(execution_path), read_json(budget_path)
    if execution.get("plan_sha256") != sha_file(plan_path):
        raise ValueError("execution does not bind frozen M79 plan")
    if budget.get("execution_sha256") != sha_file(execution_path):
        raise ValueError("round budget does not bind frozen execution")
    deadline = budget.get("deadline")
    if type(deadline) not in (int, float) or deadline <= time.time():
        raise ValueError("original M79 deadline is exhausted")
    _verify_bound_sources(root, execution)
    rows = schedule(plan)
    aux = aux_labels(plan, rows)
    touched = {r["label"] for r in rows if started(root / "evaluation" / r["label"])}
    aux_rows, control_rows = partition(rows, aux, touched)
    # A fixed 40k reservation bounds the independent node. Any unused amount
    # returns to the control owner after a SHA-verified import.
    used = _existing_cpu(root)
    remaining = EVAL_CPU_SECONDS - used
    if remaining <= 0:
        raise ValueError("shared evaluation/development CPU budget exhausted")
    aux_reserve = min(AUX_CPU_SECONDS, remaining)
    control_reserve = remaining - aux_reserve
    # Prepare only base/style configs; never require candidate a or its audit.
    per_shard = []
    for row in aux_rows:
        cfg = e.config(row["actor"], row["opponent"], row["seeds"])
        frozen = e.freeze(row["label"], cfg, "independent")
        per_shard.append({**row, "config_semantic_sha256": semantic_sha(cfg, root),
                          "manifest_sha256": frozen["manifest_sha256"]})
    control_labels = [r["label"] for r in control_rows]
    state = {
        "format": STATE_FORMAT, "revision": 1,
        "adapter_sha256": sha_file(Path(__file__)),
        "execution_sha256": sha_file(execution_path), "plan_sha256": sha_file(plan_path),
        "round_budget_sha256": sha_file(budget_path), "deadline": deadline,
        "grid_games": 12288, "aux_games": sum(r["planned_games"] for r in aux_rows),
        "aux_labels": [r["label"] for r in aux_rows],
        "control_labels": control_labels,
        "aux_shards": per_shard,
        "started_control_labels": sorted(touched),
        "evaluation_cpu_limit": EVAL_CPU_SECONDS,
        "cpu_used_before_split": used,
        "aux_cpu_reservation": aux_reserve,
        "control_eval_cpu_reservation": control_reserve,
        "aux_infra_reservation": 0,
        "global_infra_extra_limit": INFRA_EXTRA_LIMIT,
        "infra_authority": "control-node M79 CommitStore + infrastructure-retries.json",
        "control_authority": "single writer; main dispatch after result import",
        "aux_node_cpu_limit": 8,
        "aux_retry_policy": "zero; retain interruption evidence and hand unfinished identities to control",
    }
    if state["aux_games"] != len(aux_rows) * 64:
        raise ValueError("aux shard game count drift")
    write_json(state_path, state)
    return state


def _input_paths(root: Path, execution: dict) -> set[str]:
    paths = set(FIXED_INPUTS) | set(RUNTIME_SOURCES) | {
        PLAN_REL, "execution.json", "round-budget.json", STATE_REL,
        "scripts/prism_m79_dual_dispatch.py",
    }
    source_manifest = next((rel for rel in SOURCE_MANIFEST_CANDIDATES
                            if (root / rel).is_file()), None)
    if source_manifest is None:
        raise ValueError("pinned source-members.json is missing from both supported root locations")
    paths.add(source_manifest)
    # Carry pinned execution members needed to reproduce this exact adapter.
    # Candidate-training outputs and candidate registries are intentionally
    # excluded: auxiliary config construction never reads actor a.
    for rel in execution.get("files", {}):
        rel = safe_member(rel)
        if rel.startswith("campaigns/a/") or rel.startswith("audits/a/") or rel == "candidate-registry.json":
            continue
        paths.add(rel)
    for rel in paths:
        if rel.startswith("campaigns/a/") or rel.startswith("audits/a/") or rel == "candidate-registry.json":
            raise ValueError("candidate material is forbidden in auxiliary input bundle")
        if not (root / rel).is_file():
            raise ValueError("missing auxiliary input member: " + rel)
    return paths


def export_inputs(root: Path = ROOT, output: Path | None = None) -> dict:
    root = Path(root).resolve()
    state = prepare(root)
    execution = read_json(root / "execution.json")
    paths = _input_paths(root, execution)
    for rel, expected in execution.get("files", {}).items():
        if rel in paths and sha_file(root / rel) != expected:
            raise ValueError("pinned input SHA mismatch: " + rel)
    files = {rel: (root / rel).read_bytes() for rel in paths}
    metadata = {"kind": "inputs", "state_sha256": sha_bytes(canonical(state)),
                "adapter_sha256": state["adapter_sha256"],
                "execution_sha256": state["execution_sha256"],
                "plan_sha256": state["plan_sha256"], "deadline": state["deadline"],
                "labels": state["aux_labels"], "aux_cpu_reservation": state["aux_cpu_reservation"],
                "infra_reservation": 0}
    output = Path(output or (root / REV_DIR_REL / "inputs.zip"))
    return make_bundle(output, files, metadata)


def import_inputs(root: Path, archive: Path, receipt: Path | None = None) -> dict:
    root = Path(root).resolve()
    archive = Path(archive)
    receipt = Path(receipt or (str(archive) + ".receipt.json"))
    manifest, payload = verify_bundle(archive, receipt)
    meta = manifest["metadata"]
    if meta.get("kind") != "inputs" or meta.get("infra_reservation") != 0:
        raise ValueError("not an M79 auxiliary input bundle")
    members = set(payload)
    if any(p.startswith("campaigns/a/") or p.startswith("audits/a/")
           or p == "candidate-registry.json" for p in members):
        raise ValueError("candidate-training material must not enter auxiliary node")
    for name, data in payload.items():
        dest = root / safe_member(name)
        if dest.exists():
            if not dest.is_file() or sha_file(dest) != sha_bytes(data):
                raise ValueError("conflicting pinned input; refusing overwrite: " + name)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
    state = _load_state(root)
    if (sha_bytes(canonical(state)) != meta["state_sha256"]
            or state["aux_labels"] != meta["labels"]
            or state["adapter_sha256"] != meta["adapter_sha256"]):
        raise ValueError("imported input state does not match transfer receipt")
    return {"state": "INPUTS_IMPORTED_SHA_VERIFIED", "members": len(payload),
            "labels": len(state["aux_labels"]), "deadline": state["deadline"]}


def _compatible_eval_runtime(root: Path, execution: dict) -> dict:
    _, _, run = _runtime(root)
    actual = run.environment()
    expected = execution.get("environment", {})
    for key in ("python", "packages"):
        if actual.get(key) != expected.get(key):
            raise ValueError("auxiliary numerical runtime differs from pinned M79: " + key)
    return actual


def _cpu_capacity() -> tuple[list[int], float]:
    affinity = sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else list(range(os.cpu_count() or 1))
    quota = float("inf")
    try:
        q, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()[:2]
        if q != "max":
            quota = int(q) / int(period)
    except (OSError, ValueError, ZeroDivisionError):
        try:
            q = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us").read_text())
            p = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us").read_text())
            if q > 0:
                quota = q / p
        except (OSError, ValueError, ZeroDivisionError):
            pass
    return affinity, quota


def _shard_output(root: Path, label: str) -> Path:
    if "/" in label or "\\" in label or label in ("", ".", ".."):
        raise ValueError("invalid M79 shard label")
    return root / "evaluation" / label


def _dispatch_pristine(root: Path, rows: list[dict], workers: int, status_path: Path) -> dict:
    affinity, quota = _cpu_capacity()
    capacity = min(8, len(affinity), int(quota) if quota != float("inf") else 8)
    workers = min(max(1, int(workers)), capacity)
    if workers < 1:
        raise ValueError("no CPU capacity for auxiliary evaluator")
    chosen = affinity[:workers]
    if hasattr(os, "sched_setaffinity"):
        os.sched_setaffinity(0, set(chosen))
    pending = [r for r in rows if not started(_shard_output(root, r["label"]))]
    active = {}
    completed = []
    evaluator = root / "scripts/prism_m79_evaluate.py"
    started_at = time.time()
    deadline = read_json(root / "round-budget.json")["deadline"]
    try:
        while pending or active:
            if time.time() >= deadline:
                raise TimeoutError("original whole-round deadline reached")
            while pending and len(active) < workers:
                row = pending.pop(0)
                output = _shard_output(root, row["label"])
                if started(output):
                    continue
                output.mkdir(parents=True, exist_ok=True)
                log = (output / "worker.log").open("ab")
                proc = subprocess.Popen([sys.executable, "-B", str(evaluator), "grid",
                                         "--output", str(output)], cwd=root,
                                        stdout=log, stderr=subprocess.STDOUT)
                active[proc.pid] = (proc, log, row)
            for pid, (proc, log, row) in list(active.items()):
                if proc.poll() is None:
                    continue
                log.close()
                del active[pid]
                if proc.returncode:
                    raise RuntimeError("M79 auxiliary shard stopped: " + row["label"])
                completed.append(row["label"])
            write_json(status_path, {"state": "RUNNING", "pid": os.getpid(),
                                     "node": platform.node(), "observed_at": time.time(),
                                     "workers": workers, "cpu_affinity": chosen,
                                     "cpu_quota_cores": quota if quota != float("inf") else None,
                                     "completed_shards_this_run": completed,
                                     "pending_shards": [r["label"] for r in pending],
                                     "active_pids": list(active),
                                     "elapsed_seconds": time.time() - started_at,
                                     "deadline": deadline})
            if active:
                time.sleep(0.25)
    finally:
        for proc, _, _ in active.values():
            proc.terminate()
        for proc, log, _ in active.values():
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            log.close()
    return {"completed_shards_this_run": completed, "workers": workers,
            "cpu_affinity": chosen, "cpu_quota_cores": quota if quota != float("inf") else None,
            "elapsed_seconds": time.time() - started_at}


def _aux_worker(root: Path, workers: int) -> dict:
    state = _load_state(root)
    execution = read_json(root / "execution.json")
    _verify_aux_sources(root, execution)
    runtime = _compatible_eval_runtime(root, execution)
    b, e, _ = _runtime(root)
    todo = []
    for row in state["aux_shards"]:
        cfg = e.config(row["actor"], row["opponent"], row["seeds"])
        if semantic_sha(cfg, root) != row["config_semantic_sha256"]:
            raise ValueError("auxiliary fixed config drift: " + row["label"])
        e.freeze(row["label"], cfg, "independent")
        output = _shard_output(root, row["label"])
        if not started(output):
            todo.append(row)
    status_path = root / REV_DIR_REL / "aux-status.json"
    dispatch = _dispatch_pristine(root, todo, workers, status_path)
    summaries = []
    for row in state["aux_shards"]:
        output = _shard_output(root, row["label"])
        ledger_path = output / "ledger.json"
        if ledger_path.exists():
            summaries.append({"label": row["label"], "state": read_json(ledger_path)["execution_state"],
                              "completed_games": read_json(output / "grid-status.json").get("completed_games", 0)
                              if (output / "grid-status.json").exists() else 0})
        else:
            summaries.append({"label": row["label"], "state": "NOT_STARTED", "completed_games": 0})
    result = {"format": "prism-m79-aux-resource-v1", "state": "FINISHED" if all(
        s["state"] == "FINISHED" for s in summaries) else "STOPPED_WITH_RETAINED_WORK",
        "node": platform.node(), "pid": os.getpid(), "observed_at": time.time(),
        "runtime": runtime, "affinity_before_dispatch": sorted(os.sched_getaffinity(0))
        if hasattr(os, "sched_getaffinity") else None,
        "workers": dispatch["workers"], "cpu_affinity": dispatch["cpu_affinity"],
        "cpu_quota_cores": dispatch["cpu_quota_cores"], "cpu_reservation": state["aux_cpu_reservation"],
        "infra_retry_consumed": 0, "infra_reservation": 0,
        "summaries": summaries, "dispatch": dispatch,
        "deadline": state["deadline"]}
    write_json(root / REV_DIR_REL / "aux-worker-result.json", result)
    return result


def aux_run(root: Path = ROOT, workers: int = 8) -> dict:
    root = Path(root).resolve()
    state = _load_state(root)
    if state["aux_cpu_reservation"] <= 0:
        raise ValueError("auxiliary CPU reservation exhausted")
    if time.time() >= state["deadline"]:
        raise ValueError("original M79 deadline reached")
    from scripts.prism_dsw_ppo_process import ProcessTree
    out = root / REV_DIR_REL
    out.mkdir(parents=True, exist_ok=True)
    status = out / "aux-status.json"
    process_created = None
    with (out / "aux-run.log").open("ab") as log:
        # Leave a small polling margin so actual CPU remains within the fixed
        # 40k reservation; unused reservation returns only after import.
        cpu_cap = max(1.0, state["aux_cpu_reservation"] - min(300.0, workers * 30.0))
        with ProcessTree(cpu_seconds=cpu_cap, memory_bytes=8 * 1024**3, max_processes=128) as tree:
            proc = tree.start([sys.executable, "-B", str(Path(__file__).resolve()),
                               "aux-worker", "--root", str(root), "--workers", str(workers)],
                              cwd=root, stdout=log, stderr=log)
            try:
                import psutil
                process_created = psutil.Process(proc.pid).create_time()
            except Exception:
                process_created = None
            resources = tree.wait(wall_seconds=max(0.0, state["deadline"] - time.time()),
                                  storage_root=root,
                                  max_storage_bytes=read_json(root / PLAN_REL)["resources"]["dsw2_total_storage_bytes"],
                                  snapshot=lambda counters: write_json(status, {
                                      "state": "RUNNING", "pid": proc.pid,
                                      "node": platform.node(), "observed_at": time.time(),
                                      "resources": counters, "deadline": state["deadline"]}))
    resource = {"format": "prism-m79-aux-resource-v1",
                "state": "FINISHED" if resources["returncode"] == 0 and not resources["stop_reason"]
                else "STOPPED_WITH_RETAINED_WORK",
                "node": platform.node(), "pid": proc.pid, "create_time": process_created,
                "observed_at": time.time(), "execution_sha256": state["execution_sha256"],
                "adapter_sha256": state["adapter_sha256"], "deadline": state["deadline"],
                "cpu_reservation": state["aux_cpu_reservation"], "cpu_seconds": resources["cpu_seconds"],
                "resources": resources, "infra_retry_consumed": 0, "infra_reservation": 0,
                "worker_result": read_json(out / "aux-worker-result.json")
                if (out / "aux-worker-result.json").exists() else None}
    if resource["cpu_seconds"] > state["aux_cpu_reservation"]:
        resource["state"] = "BUDGET_OVERRUN_REQUIRES_RECONCILIATION"
    write_json(out / "aux-resource.json", resource)
    write_json(status, {"state": resource["state"], "resources": resources,
                        "node": platform.node(), "observed_at": resource["observed_at"],
                        "deadline": state["deadline"]})
    return resource


def _process_create_time(pid: int) -> float | None:
    try:
        import psutil
        return psutil.Process(pid).create_time()
    except Exception:
        return None


def export_results(root: Path = ROOT, output: Path | None = None) -> dict:
    root = Path(root).resolve()
    state = _load_state(root)
    resource_path = root / REV_DIR_REL / "aux-resource.json"
    if not resource_path.exists():
        raise ValueError("auxiliary run has no terminal resource receipt")
    resource = read_json(resource_path)
    if resource["state"] == "RUNNING":
        raise ValueError("cannot export while auxiliary writer is live")
    files = {STATE_REL: (root / STATE_REL).read_bytes(),
             f"{REV_DIR_REL}/aux-resource.json": resource_path.read_bytes()}
    labels = set(state["aux_labels"])
    for label in sorted(labels):
        output_dir = _shard_output(root, label)
        if not output_dir.exists():
            continue
        for path in output_dir.rglob("*"):
            if path.is_file():
                files[path.relative_to(root).as_posix()] = path.read_bytes()
        for suffix in (".json", ".policy.json"):
            path = root / "evaluation-configs" / (label + suffix)
            if path.is_file():
                files[path.relative_to(root).as_posix()] = path.read_bytes()
    metadata = {"kind": "results", "state_sha256": sha_bytes(canonical(state)),
                "execution_sha256": state["execution_sha256"],
                "plan_sha256": state["plan_sha256"], "adapter_sha256": state["adapter_sha256"],
                "labels": sorted(labels), "aux_state": resource["state"],
                "aux_cpu_seconds": resource.get("cpu_seconds"),
                "infra_retry_consumed": resource.get("infra_retry_consumed", 0)}
    output = Path(output or (root / REV_DIR_REL / "results.zip"))
    return make_bundle(output, files, metadata)


def _result_member_label(name: str, allowed: set[str]) -> str | None:
    p = safe_member(name)
    parts = PurePosixPath(p).parts
    if len(parts) >= 2 and parts[0] == "evaluation" and parts[1] in allowed:
        return parts[1]
    if len(parts) == 2 and parts[0] == "evaluation-configs":
        for label in allowed:
            if parts[1] in (label + ".json", label + ".policy.json"):
                return label
    if p in (STATE_REL, f"{REV_DIR_REL}/aux-resource.json"):
        return "__metadata__"
    raise ValueError("result package contains non-auxiliary member: " + p)


def _canonicalize_imported_shard(root: Path, label: str, b, e) -> dict:
    out = _shard_output(root, label)
    config_path = out / "config.json"
    policy_path = out / "policy.json"
    manifest_path = out / "manifest.json"
    config, policy, manifest = (read_json(p) for p in (config_path, policy_path, manifest_path))
    expected_config_path = root / "evaluation-configs" / (label + ".json")
    expected_cfg = read_json(expected_config_path)
    if semantic_config(config, root) != semantic_config(expected_cfg, root):
        raise ValueError("imported fixed config identity drift: " + label)
    if policy != read_json(root / "evaluation-configs" / (label + ".policy.json")):
        raise ValueError("imported fixed shard policy drift: " + label)
    if manifest.get("config_sha256") != b.fixed.canonical_hash(config):
        raise ValueError("imported config manifest hash drift: " + label)
    if manifest.get("policy_sha256") != b.fixed.canonical_hash(policy):
        raise ValueError("imported policy manifest hash drift: " + label)
    validated = b.arena.validate_arena_config(expected_cfg, expected_config_path)
    validated["config"] = expected_cfg
    for job in b.legacy.jobs(expected_cfg):
        game_dir = b.legacy.game_directory(out, job)
        match_path, result_path = game_dir / "match-config.json", game_dir / "process-result.json"
        if match_path.exists():
            write_json(game_dir / "aux-match-config.json", read_json(match_path))
            write_json(match_path, b.match_config(validated, job))
        if result_path.exists():
            raw = read_json(result_path)
            write_json(game_dir / "aux-process-result.json", raw)
            raw["argv"] = b.rollout_command(validated, policy, game_dir)
            write_json(result_path, raw)
        ledger_path = out / "ledger.json"
        if ledger_path.exists():
            ledger = read_json(ledger_path)
            key = b.fixed._game_key(*job)
            entry = ledger["entries"].get(key)
            if entry and entry["state"] in ("COMPLETED", "RETAINED_FAILURE") and game_dir.exists():
                if entry["state"] == "COMPLETED" or entry.get("kind") == "PLY_CAP_TRUNCATED":
                    checked = b.validate_artifacts(game_dir, expected_cfg, job, policy["ply_cap"])
                    write_json(game_dir / "game.json", checked)
                    entry = dict(checked)
                entry["evidence_sha256"] = b.evidence(game_dir)
                ledger["entries"][key] = entry
            write_json(ledger_path, ledger)
    manifest["config_origin"] = str(expected_config_path.resolve())
    manifest["config_sha256"] = b.fixed.canonical_hash(expected_cfg)
    manifest["policy_sha256"] = b.fixed.canonical_hash(policy)
    manifest["runtime"] = b.runtime()
    manifest["source_sha256"] = {rel: b.sha(root / rel) for rel in b.SOURCES}
    write_json(manifest_path, manifest)
    ledger_path = out / "ledger.json"
    if ledger_path.exists():
        ledger = read_json(ledger_path)
        ledger["manifest_sha256"] = b.sha(manifest_path)
        for key, entry in ledger["entries"].items():
            if entry["state"] in ("COMPLETED", "RETAINED_FAILURE"):
                job = next(j for j in b.legacy.jobs(expected_cfg) if b.fixed._game_key(*j) == key)
                entry["evidence_sha256"] = b.evidence(b.legacy.game_directory(out, job))
        write_json(ledger_path, ledger)
        b.inspect(out)
    return {"label": label, "state": read_json(ledger_path)["execution_state"]
            if ledger_path.exists() else "NOT_STARTED"}


def import_results(root: Path, archive: Path, receipt: Path | None = None) -> dict:
    root = Path(root).resolve()
    archive = Path(archive)
    receipt = Path(receipt or (str(archive) + ".receipt.json"))
    state = _load_state(root)
    expected_meta = None
    manifest, payload = verify_bundle(archive, receipt)
    meta = manifest["metadata"]
    if (meta.get("kind") != "results" or meta.get("state_sha256") != sha_bytes(canonical(state))
            or meta.get("execution_sha256") != state["execution_sha256"]
            or meta.get("plan_sha256") != state["plan_sha256"]
            or meta.get("adapter_sha256") != state["adapter_sha256"]
            or meta.get("infra_retry_consumed") != 0):
        raise ValueError("auxiliary result contract identity drift")
    allowed = set(state["aux_labels"])
    for name in payload:
        _result_member_label(name, allowed)
    resource_name = f"{REV_DIR_REL}/aux-resource.json"
    if resource_name not in payload:
        raise ValueError("auxiliary real-resource receipt missing")
    resource = json.loads(payload[resource_name])
    if (resource.get("state") == "RUNNING" or resource.get("infra_retry_consumed") != 0
            or resource.get("cpu_seconds", 0) > state["aux_cpu_reservation"]):
        raise ValueError("auxiliary result is live, retried, or exceeds its CPU reservation")
    _, e, _ = _runtime(root)
    b = e.b
    # This owner receipt is the handoff point. Existing control-side work on an
    # aux label is a hard conflict; completed games are never overwritten.
    labels_present = {name.split("/")[1] for name in payload
                      if name.startswith("evaluation/") and len(name.split("/")) > 2}
    if labels_present != allowed:
        raise ValueError("result bundle must contain every assigned auxiliary shard")
    for label in labels_present:
        dest = _shard_output(root, label)
        if started(dest):
            raise ValueError("single-writer conflict on auxiliary shard: " + label)
    for name, data in payload.items():
        if not name.startswith("evaluation/") and not name.startswith("evaluation-configs/"):
            continue
        dest = root / safe_member(name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    # Resource and state receipts are preserved byte-for-byte beside the import.
    import_dir = root / REV_DIR_REL
    write_json(import_dir / "aux-resource.json", resource)
    import_receipt = {"state": "AUX_RESULTS_IMPORTED_SHA_VERIFIED",
                      "archive_sha256": read_json(receipt)["sha256"],
                      "member_count": len(payload), "labels_present": sorted(labels_present),
                      "aux_cpu_seconds": resource["cpu_seconds"], "infra_retry_consumed": 0,
                      "imported_at": time.time(), "execution_sha256": state["execution_sha256"]}
    results = []
    for label in sorted(labels_present):
        results.append(_canonicalize_imported_shard(root, label, b, e))
    complete = {r["label"] for r in results if r["state"] == "FINISHED"}
    import_receipt["aux_finished_labels"] = sorted(complete)
    import_receipt["unfinished_handoff_labels"] = sorted(labels_present - complete)
    write_json(import_dir / "aux-import.json", import_receipt)
    return import_receipt


def _aux_import_ready(root: Path) -> bool:
    path = root / REV_DIR_REL / "aux-import.json"
    if not path.exists():
        return False
    state = _load_state(root)
    r = read_json(path)
    return (r.get("state") == "AUX_RESULTS_IMPORTED_SHA_VERIFIED"
            and r.get("execution_sha256") == state["execution_sha256"]
            and r.get("infra_retry_consumed") == 0)


def _external_eval_cpu(root: Path) -> float:
    state = _load_state(root)
    if not _aux_import_ready(root):
        return min(AUX_CPU_SECONDS, state["aux_cpu_reservation"])
    resource = read_json(root / REV_DIR_REL / "aux-resource.json")
    cpu = resource.get("cpu_seconds")
    if type(cpu) not in (int, float) or cpu < 0 or cpu > AUX_CPU_SECONDS:
        return AUX_CPU_SECONDS
    return float(cpu)


def control_evaluate(root: Path = ROOT) -> dict:
    root = Path(root).resolve()
    state = _load_state(root)
    if not _aux_import_ready(root):
        raise ValueError("import the complete SHA-verified auxiliary result bundle before control evaluation")
    if time.time() >= state["deadline"]:
        raise ValueError("original M79 deadline reached")
    _, e, _ = _runtime(root)
    registry = e.candidates()
    shards = e.make_grid(False)
    by_label = {s["label"]: s for s in shards}
    if len(shards) != 192 or sum(s["planned_games"] for s in shards) != 12288:
        raise ValueError("native M79 grid differs from frozen 12,288-game contract")
    aux = set(state["aux_labels"])
    if not aux.issubset(by_label):
        raise ValueError("auxiliary labels differ from the native full grid")
    imported = read_json(root / REV_DIR_REL / "aux-import.json")
    transferred = set(imported["unfinished_handoff_labels"])
    control_labels = set(state["control_labels"]) | transferred
    if control_labels & (aux - transferred):
        raise ValueError("control dispatch overlaps completed auxiliary ownership")
    plan = {"format": "prism-m79-bounded-shards-v1", "shards": shards,
            "total_games": 12288, "plan_sha256": state["plan_sha256"],
            "candidate_registry_sha256": sha_file(root / "candidate-registry.json"),
            "dual_dispatch_revision_sha256": state["adapter_sha256"],
            "aux_cpu_seconds": imported["aux_cpu_seconds"],
            "aux_retry_consumed": 0}
    destination = root / "evaluation-plan.json"
    if destination.exists() and read_json(destination) != plan:
        raise ValueError("existing full-grid binding differs; preserve prior plan")
    write_json(destination, plan)
    owned = [by_label[label] for label in sorted(control_labels)]
    done = e.dispatch(owned, "independent") if owned else []
    all_done = []
    for shard in shards:
        out = Path(shard["output"])
        if (out / "ledger.json").exists():
            all_done.append(dict(shard, grid=e.b.inspect(out)))
    completed = sum(row["grid"]["completed_games"] for row in all_done)
    missing = 12288 - sum(row["grid"]["completed_games"] + row["grid"]["truncated_games"]
                          for row in all_done)
    result = {"status": "FINISHED_WITH_EXPLICIT_MISSINGNESS", "shards": all_done,
              "completed_games": completed,
              "truncated_games": sum(row["grid"]["truncated_games"] for row in all_done),
              "missing_games": missing, "plan_sha256": sha_file(destination),
              "dual_dispatch_revision_sha256": state["adapter_sha256"],
              "aux_cpu_seconds": imported["aux_cpu_seconds"], "finished_at": time.time()}
    write_json(root / "evaluation-completion.json", result)
    return result


def _patch_pipeline_budget(function):
    source = inspect.getsource(function)
    replacements = (
        ("spent=sum(r.get('cpu_seconds',0) for r in journal if r['category']==category)",
         "external_eval=_external_eval_cpu(ROOT);spent=sum(r.get('cpu_seconds',0) for r in journal if r['category']==category)+(external_eval if category=='evaluation_development' else 0.)"),
        ("allspent=sum(r.get('cpu_seconds',0) for r in journal)",
         "allspent=sum(r.get('cpu_seconds',0) for r in journal)+external_eval"),
    )
    for old, new in replacements:
        if source.count(old) != 1:
            raise ValueError("pinned M79 controller budget site drift")
        source = source.replace(old, new)
    namespace = dict(function.__globals__)
    namespace["_external_eval_cpu"] = _external_eval_cpu
    exec(compile(source, str(Path(__file__)) + "::pipeline", "exec"), namespace)
    return namespace[function.__name__]


def pipeline(root: Path = ROOT) -> dict:
    """Run a separate controller revision that reserves aux CPU and excludes its shards."""
    root = Path(root).resolve()
    state = _load_state(root)
    b, e, run = _runtime(root)
    run.verify()
    execution = read_json(root / "execution.json")
    binding = execution.get("binding", {})
    if len(binding.get("training_affinity", [])) != 4:
        raise ValueError("M79 training node must retain its four-core DSW binding")
    plan = read_json(root / PLAN_REL)
    if plan["resources"]["evaluation_development_cpu_seconds"] != EVAL_CPU_SECONDS:
        raise ValueError("M79 shared evaluation CPU cap drift")
    # External aux CPU is charged once in the same 120k evaluation/development
    # ceiling and once in the all-round CPU ceiling. Before import, the full
    # 40k reservation stays unavailable to the control node.
    patched = _patch_pipeline_budget(run.pipeline)
    original_pipeline = run.pipeline
    original_start = run.ProcessTree.start

    def route_stage(self, argv, **kwargs):
        if len(argv) >= 3 and Path(argv[-2]).name == "prism_m79_evaluate.py":
            mode = argv[-1]
            if mode in ("curve", "evaluate") and not _aux_import_ready(root):
                argv = [sys.executable, "-B", str(Path(__file__).resolve()),
                        "aux-gate", "--root", str(root), "--stage", mode]
            elif mode == "evaluate":
                argv = [sys.executable, "-B", str(Path(__file__).resolve()),
                        "control-evaluate", "--root", str(root)]
        return original_start(self, argv, **kwargs)

    run.pipeline = patched
    run.ProcessTree.start = route_stage
    try:
        revision_path = root / "execution-revisions/r6.json"
        if revision_path.exists():
            from scripts import prism_m79_revision_r6 as r6
            r6.ROOT = root
            return r6.pipeline()
        return run.pipeline()
    finally:
        run.pipeline = original_pipeline
        run.ProcessTree.start = original_start


def aux_gate(root: Path, stage: str) -> int:
    if stage not in ("curve", "evaluate"):
        raise ValueError("invalid evaluation gate")
    if not _aux_import_ready(Path(root).resolve()):
        print(json.dumps({"state": "WAITING_FOR_AUX_RESULT_IMPORT", "stage": stage}), flush=True)
        return 2
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "export-inputs", "import-inputs",
                                          "aux-run", "aux-worker", "export-results",
                                          "import-results", "control-evaluate", "pipeline",
                                          "aux-gate"))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--stage", choices=("curve", "evaluate"))
    args = parser.parse_args()
    if args.mode == "prepare":
        result = prepare(args.root)
    elif args.mode == "export-inputs":
        result = export_inputs(args.root, args.output)
    elif args.mode == "import-inputs":
        if not args.bundle:
            parser.error("import-inputs requires --bundle")
        result = import_inputs(args.root, args.bundle, args.receipt)
    elif args.mode == "aux-run":
        result = aux_run(args.root, args.workers)
    elif args.mode == "aux-worker":
        result = _aux_worker(args.root, args.workers)
    elif args.mode == "export-results":
        result = export_results(args.root, args.output)
    elif args.mode == "import-results":
        if not args.bundle:
            parser.error("import-results requires --bundle")
        result = import_results(args.root, args.bundle, args.receipt)
    elif args.mode == "control-evaluate":
        result = control_evaluate(args.root)
    elif args.mode == "pipeline":
        result = pipeline(args.root)
    else:
        result = aux_gate(args.root, args.stage)
        if result:
            raise SystemExit(result)
        result = {"state": "AUX_IMPORT_READY", "stage": args.stage}
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
