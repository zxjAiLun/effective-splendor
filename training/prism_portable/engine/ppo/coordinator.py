"""Synchronous PPO transactions; v2 ingestion requires a pinned Arena package."""
from contextlib import contextmanager
import copy
from pathlib import Path
import time
import uuid

import torch

from ..io import canonical_hash, read_json, sha256_file, tensor_identity, write_json
from .audit import audit_game, bounded_json
from .contract import PPOConfig, exact, integer, number, sha, text, validate_audit
from .learner import Learner, prepare_batch, validate_batch
from .model import new_model, warm_start
from .runtime import capture_rng, configure, restore_rng, seed_all
from .sampling import Behavior
from .store import CommitStore

CONFIG_KEYS = {"format", "run_id", "catalog_fingerprint", "parent_sha256", "auditor_sha256",
               "device", "cpu_threads", "seed", "ppo", "budget", "opponents"}
BUDGET_KEYS = {"max_cycles", "max_optimizer_steps", "max_update_attempts", "max_jobs", "max_attempts",
               "max_decisions", "max_job_decisions", "max_run_seconds", "max_storage_bytes"}
STATE_KEYS = {"format", "identity", "runtime", "phase", "paused", "cycle", "global_step", "update_attempts",
              "attempts", "decisions", "all_jobs", "schedule", "jobs", "snapshot", "batch", "cursor", "order",
              "consumed", "metrics", "started_at", "model", "optimizer", "rng"}


def validate_config(value):
    version = value.get("format") if isinstance(value, dict) else None
    exact(value, CONFIG_KEYS | ({"arena_contract_sha256"} if version in ("prism-ppo-run-v2", "prism-ppo-run-v3") else set())
          | ({"style"} if version == "prism-ppo-run-v3" else set()), "run config")
    if version not in ("prism-ppo-run-v1", "prism-ppo-run-v2", "prism-ppo-run-v3"):
        raise ValueError("run config format")
    if version in ("prism-ppo-run-v2", "prism-ppo-run-v3"):
        sha(value["arena_contract_sha256"], "Arena contract hash")
    for key in ("run_id", "catalog_fingerprint"):
        text(value[key], key)
    for key in ("parent_sha256", "auditor_sha256"):
        sha(value[key], key)
    integer(value["seed"], 0, 2**63 - 1, "seed")
    integer(value["cpu_threads"], 1, 64, "cpu_threads")
    if value["device"] not in ("cpu", "cuda"):
        raise ValueError("device must be cpu/cuda")
    ppo = PPOConfig.from_dict(value["ppo"])
    # v3 binds a supported extractor in the immutable run contract; legacy
    # versions still reject arbitrary user-supplied live style labels.
    if version == "prism-ppo-run-v3":
        from .style import validate_style_config
        validate_style_config(value["style"])
        if ppo.style_beta > 0 and ppo.style_value_weight <= 0:
            raise ValueError("style learning requires a positive style value loss weight")
    elif ppo.style_beta != 0:
        raise ValueError("coordinator style campaigns require the later reward-extractor gate")
    exact(value["budget"], BUDGET_KEYS, "budget")
    for key in BUDGET_KEYS - {"max_run_seconds"}:
        integer(value["budget"][key], 1, 2**63 - 1, key)
    if number(value["budget"]["max_run_seconds"], 0, float("inf"), "max_run_seconds") <= 0:
        raise ValueError("positive run wall-time budget required")
    if not isinstance(value["opponents"], dict) or not value["opponents"]:
        raise ValueError("explicit frozen opponent map required")
    for key, identity in value["opponents"].items():
        text(key, "opponent name"); sha(identity, "opponent identity")
    return ppo


def source_identity():
    from ...common import numerical_identity
    return numerical_identity()



class Run:
    def __init__(self, directory, config):
        self.root = Path(directory)
        self.config = copy.deepcopy(config)
        self.ppo = validate_config(config)
        self.runtime = configure(config["device"], config["cpu_threads"])
        self.identity = canonical_hash({"config": config, "runtime": self.runtime, "source": source_identity()})
        self.store = CommitStore(directory, self.identity, max_bytes=config["budget"]["max_storage_bytes"])
        self.state = self.parent = self.learner = None
        self._dirty = False
        self._behavior_cache = {}
        self._batch_cache = None

    @classmethod
    def create(cls, directory, config, weights):
        directory = Path(directory)
        if directory.exists():
            raise ValueError("new run directory must not exist")
        run = cls(directory, config)
        if sha256_file(weights) != config["parent_sha256"]:
            raise ValueError("warm-start weights hash mismatch")
        seed_all(config["seed"])
        model = warm_start(weights, config["catalog_fingerprint"], style_enabled=run.ppo.style_beta > 0,
                           initialization_seed=config["seed"]).to(config["device"])
        run.learner = Learner(model, run.ppo)
        with run.store.lock():
            if any(p.name != "writer.lock" for p in directory.iterdir()):
                raise ValueError("run directory was initialized by another writer")
            write_json(directory / "config.json", config)
            run.state = {"format": "prism-ppo-state-v1", "identity": run.identity, "runtime": run.runtime,
                         "phase": "READY", "paused": False, "cycle": 0, "global_step": 0,
                         "update_attempts": 0, "attempts": 0, "decisions": 0, "all_jobs": [],
                         "schedule": [], "jobs": {}, "snapshot": None, "batch": None,
                         "cursor": 0, "order": [], "consumed": [], "metrics": [], "started_at": time.time(),
                         "model": None, "optimizer": None, "rng": None}
            run._commit()
        return run

    @classmethod
    def open(cls, directory):
        run = cls(directory, read_json(Path(directory) / "config.json"))
        with run.store.lock():
            run._reload()
        return run

    def _reload(self):
        self._batch_cache = None
        self._behavior_cache.clear()
        self.parent, self.state = self.store.load()
        if self.state is None:
            raise ValueError("no committed run state; init was not completed")
        exact(self.state, STATE_KEYS, "run state")
        s = self.state
        if s["format"] != "prism-ppo-state-v1" or s["identity"] != self.identity or s["runtime"] != self.runtime:
            raise ValueError("checkpoint identity/runtime mismatch")
        if s["phase"] not in ("READY", "COLLECTING", "UPDATING", "COMMITTED", "FAILED") or type(s["paused"]) is not bool:
            raise ValueError("invalid run state")
        for key in ("cycle", "global_step", "update_attempts", "attempts", "decisions", "cursor"):
            integer(s[key], 0, 2**63 - 1, key)
        if len(set(s["consumed"])) != len(s["consumed"]) or len(set(s["all_jobs"])) != len(s["all_jobs"]):
            raise ValueError("duplicate consumption/jobs in checkpoint")
        model = new_model(style_enabled=self.ppo.style_beta > 0, state_dict=s["model"]).to(self.runtime["device"])
        self.learner = Learner(model, self.ppo)
        self.learner.load_optimizer(s["optimizer"])
        behavior = None
        if s["snapshot"] is not None:
            behavior = Behavior.from_payload(self.store.get_payload(s["snapshot"]), runtime=self.runtime)
            self._behavior_cache[s['snapshot']] = behavior
        if s["batch"] is not None:
            batch = self.store.get_json(s["batch"])
            validate_batch(batch, self.ppo)
            if behavior is None or batch["behavior_id"] != behavior.identity:
                raise ValueError("batch/snapshot identity mismatch")
            n = len(batch["rows"])
            if len(s["order"]) != n * self.ppo.passes or not 0 <= s["cursor"] <= len(s["order"]):
                raise ValueError("invalid update cursor/order")
            for start in range(0, len(s["order"]), n):
                if sorted(s["order"][start:start+n]) != list(range(n)):
                    raise ValueError("invalid saved minibatch permutation")
            if s["phase"] == "UPDATING" and (batch["batch_id"] in s["consumed"] or s["cursor"] == len(s["order"])):
                raise ValueError("active batch already consumed")
            self._batch_cache = (s['batch'], batch)
        restore_rng(s["rng"])

    def _commit(self, fault=None):
        self.state["model"] = {k: v.detach().cpu().clone() for k, v in self.learner.model.state_dict().items()}
        self.state["optimizer"] = self.learner.optimizer.state_dict()
        self.state["rng"] = capture_rng()
        self.parent = self.store.commit(self.state, expected_parent=self.parent, fault=fault)

    @contextmanager
    def _transaction(self):
        with self.store.lock():
            head = self.store.head()
            if self._dirty or head != self.parent or self.state is None or self.learner is None:
                self._reload()
                self._dirty = False
            try:
                yield
            except Exception:
                self._dirty = True
                raise
    def _admit(self):
        if self.state["paused"] or self.state["phase"] == "FAILED":
            raise ValueError("run is paused/failed")
        elapsed = time.time() - self.state["started_at"]
        if elapsed < 0 or elapsed >= self.config["budget"]["max_run_seconds"]:
            raise ValueError("run wall-time budget exhausted or clock moved backwards")

    def begin_cycle(self, schedule):
        with self._transaction():
            self._admit()
            s, budget = self.state, self.config["budget"]
            if s["phase"] not in ("READY", "COMMITTED") or s["cycle"] >= budget["max_cycles"]:
                raise ValueError("cycle boundary/budget violation")
            if not isinstance(schedule, list) or not schedule or len(s["all_jobs"]) + len(schedule) > budget["max_jobs"]:
                raise ValueError("job schedule budget")
            names = []
            for job in schedule:
                exact(job, {"job_id", "actor", "opponent_id", "environment_seed"}, "job")
                names.append(text(job["job_id"], "job_id"))
                integer(job["actor"], 0, 1, "actor")
                integer(job["environment_seed"], 0, 2**64 - 1, "environment seed")
                if job["opponent_id"] not in self.config["opponents"]:
                    raise ValueError("opponent outside frozen pool")
            if len(set(names)) != len(names) or set(names) & set(s["all_jobs"]):
                raise ValueError("reused job identity")
            if s["decisions"] + len(schedule) * budget["max_job_decisions"] > budget["max_decisions"]:
                raise ValueError("insufficient reserved decision budget")
            behavior = Behavior(self.learner.model, catalog_fingerprint=self.config["catalog_fingerprint"],
                                action_seed=self.config["seed"], runtime=self.runtime)
            s["snapshot"] = self.store.put_payload(behavior.payload())
            self._behavior_cache = {s['snapshot']: behavior}
            self._batch_cache = None
            s["phase"], s["schedule"], s["jobs"] = "COLLECTING", copy.deepcopy(schedule), {}
            s["all_jobs"].extend(names); s["cycle"] += 1
            s["batch"], s["order"], s["cursor"] = None, [], 0
            self._commit()
            return {"behavior_id": behavior.identity, "snapshot_sha256": s["snapshot"],
                    "snapshot": str(self.root / "objects" / (s["snapshot"] + ".pt"))}

    def start_attempt(self, job_id):
        with self._transaction():
            self._admit()
            s = self.state
            if s["phase"] != "COLLECTING" or job_id not in {j["job_id"] for j in s["schedule"]}:
                raise ValueError("not a collecting job")
            if s["jobs"].get(job_id, {}).get("status") == "COMPLETE":
                raise ValueError("completed job must not be replayed")
            if s["attempts"] >= self.config["budget"]["max_attempts"]:
                raise ValueError("attempt budget exhausted")
            s["attempts"] += 1
            attempt = s["attempts"]
            # Prior attempt stays in immutable commit history. No seed changes.
            s["jobs"][job_id] = {"status": "RUNNING", "attempt": attempt}
            self._commit()
            return attempt

    def submit(self, job_id, attempt, *, executable, replay, sidecar, completion=None):
        integer(attempt, 1, 2**63 - 1, "attempt")
        with self._transaction():
            # Graceful pause allows already-running jobs to finish ingestion.
            s = self.state
            if s["phase"] != "COLLECTING" or s["jobs"].get(job_id) != {"status": "RUNNING", "attempt": attempt}:
                raise ValueError("stale/duplicate/unstarted attempt")
            job = next(j for j in s["schedule"] if j["job_id"] == job_id)
            behavior = self._behavior_cache.get(s["snapshot"])
            if behavior is None:
                behavior = Behavior.from_payload(self.store.get_payload(s["snapshot"]), runtime=self.runtime)
                self._behavior_cache[s["snapshot"]] = behavior
            try:
                if self.config["format"] in ("prism-ppo-run-v2", "prism-ppo-run-v3"):
                    if completion is None:
                        raise ValueError("v2 submission requires Arena completion package")
                    from .execution import verify_completion
                    result = verify_completion(self.config, job, attempt, completion, replay=replay,
                                               sidecar=sidecar, behavior_id=behavior.identity)
                    if bounded_json(completion)["snapshot_sha256"] != s["snapshot"]:
                        raise ValueError("completion snapshot mismatch")
                    replay_meta = bounded_json(replay)
                    if replay_meta.get("seed") != job["environment_seed"] or replay_meta.get("player_count") != 2:
                        raise ValueError("replay/schedule mismatch")
                    from ..io import parse_json
                    decisions = []
                    with open(sidecar, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                decisions.append(parse_json(line))
                    game = {
                        "format": "prism-ppo-game-v1",
                        "behavior_id": behavior.identity,
                        "job_id": job_id,
                        "actor": job["actor"],
                        "game_id": replay_meta.get("game_id", job_id),
                        "catalog_fingerprint": behavior.catalog,
                        "replay_sha256": sha256_file(replay),
                        "sidecar_sha256": sha256_file(sidecar),
                        "terminal": True,
                        "result": result,
                        "decisions": decisions,
                    }
                    validate_audit(game, behavior_id=behavior.identity, catalog_fingerprint=behavior.catalog,
                                   max_decisions=self.config["budget"]["max_job_decisions"])
                else:
                    audit_dir = self.root / "audit-attempts"
                    audit_dir.mkdir(exist_ok=True)
                    output = audit_dir / (uuid.uuid4().hex + ".json")
                    replay_meta = bounded_json(replay)
                    if replay_meta.get("seed") != job["environment_seed"] or replay_meta.get("player_count") != 2:
                        raise ValueError("replay/schedule mismatch")
                    game = audit_game(executable, self.config["auditor_sha256"], replay, sidecar, output,
                                      behavior_id=behavior.identity, job_id=job_id, actor=job["actor"])
                    validate_audit(game, behavior_id=behavior.identity, catalog_fingerprint=behavior.catalog,
                                   max_decisions=self.config["budget"]["max_job_decisions"])
                    if game["job_id"] != job_id or game["actor"] != job["actor"]:
                        raise ValueError("audited job/actor mismatch")
                artifact = self.store.put_json(game)
            except (ValueError, OSError, RuntimeError) as exc:
                s["phase"] = "FAILED"
                s["metrics"].append({"event": "audit_failed", "job_id": job_id, "error_type": type(exc).__name__})
                self._commit()
                raise
            s["decisions"] += len(game["decisions"])
            s["jobs"][job_id] = {"status": "COMPLETE", "attempt": attempt, "artifact": artifact}
            if completion is not None:
                s["jobs"][job_id]["completion"] = self.store.put_json(bounded_json(completion))
            self._commit()

    def seal(self):
        with self._transaction():
            self._admit()
            s = self.state
            if s["phase"] != "COLLECTING" or any(s["jobs"].get(j["job_id"], {}).get("status") != "COMPLETE" for j in s["schedule"]):
                raise ValueError("cannot seal incomplete/noncollecting batch")
            games = [self.store.get_json(s["jobs"][j["job_id"]]["artifact"]) for j in s["schedule"]]
            behavior = self._behavior_cache.get(s["snapshot"])
            if behavior is None:
                behavior = Behavior.from_payload(self.store.get_payload(s["snapshot"]), runtime=self.runtime)
                self._behavior_cache[s["snapshot"]] = behavior
            style_targets = None
            if self.ppo.style_beta > 0:
                from .style import extract_style_targets
                style_targets, style_summary = extract_style_targets(games, self.config["style"])
                style_artifact = self.store.put_json(style_summary)
                style_metrics = {'event': 'style_extracted', 'cycle': s['cycle'],
                                 'artifact': style_artifact,
                                 'style_contract_sha256': style_summary['style_contract_sha256']}
                if self.config['style']['format'] == 'prism-building-style-v1':
                    style_metrics.update(mean_building_utility=style_summary['mean_building_utility'],
                                         mean_early_bonus_auc12=style_summary['mean_early_bonus_auc12'])
                elif self.config['style']['format'] == 'prism-building-timed-style-v1':
                    style_metrics.update(
                        mean_time_weighted_utility=style_summary['mean_time_weighted_utility'],
                        mean_building_utility=style_summary['mean_building_utility'],
                        mean_early_bonus_auc12=style_summary['mean_early_bonus_auc12'])
                else:
                    style_metrics.update(mean_rush_auc=style_summary['mean_rush_auc'],
                                         vp_threshold_by_horizon_rate=style_summary['vp_threshold_by_horizon_rate'])
                s['metrics'].append(style_metrics)
            batch = prepare_batch(games, behavior, self.ppo, max_decisions=self.config["budget"]["max_decisions"],
                                  style_returns=style_targets, verify=False)
            if batch["batch_id"] in s["consumed"]:
                raise ValueError("batch already consumed")
            validate_batch(batch, self.ppo)
            s['batch'] = self.store.put_json(batch)
            self._batch_cache = (s['batch'], batch)
            s['order'] = [i for _ in range(self.ppo.passes) for i in torch.randperm(len(batch['rows'])).tolist()]
            s['cursor'], s['phase'] = 0, 'UPDATING'
            # Bind learner to frozen snapshot without a second policy forward.
            if tensor_identity(self.learner.model.state_dict()) != tensor_identity(behavior.model.state_dict()):
                raise ValueError('learner is not the frozen behavior')
            s['metrics'].append({'event': 'sealed', 'cycle': s['cycle'], 'batch_id': batch['batch_id'],
                                 'games': len(games), 'decisions': len(batch['rows']),
                                 'advantage_mean': batch['advantage_mean'], 'advantage_std': batch['advantage_std']})
            self._commit()
            return batch["batch_id"]

    def step(self, *, fault=None):
        with self._transaction():
            self._admit()
            s, budget = self.state, self.config["budget"]
            if s["phase"] != "UPDATING":
                raise ValueError("no unconsumed active batch")
            if s["global_step"] >= budget["max_optimizer_steps"] or s["update_attempts"] >= budget["max_update_attempts"]:
                raise ValueError("optimizer budget exhausted")
            if self._batch_cache is None or self._batch_cache[0] != s['batch']:
                batch = self.store.get_json(s['batch'])
                validate_batch(batch, self.ppo)
                self._batch_cache = (s['batch'], batch)
            batch = self._batch_cache[1]
            n = len(batch['rows'])
            start = s['cursor']
            end = min(start + self.ppo.minibatch_size, ((start // n) + 1) * n)
            indices = s['order'][start:end]
            # Charge attempt before computation. Cursor/model/AdamW advance
            # together only in the subsequent successful atomic commit.
            s['update_attempts'] += 1
            s['metrics'].append({'event': 'optimizer_attempt', 'cycle': s['cycle'],
                                 'attempt': s['update_attempts'], 'cursor': start})
            self._commit()
            metrics = self.learner.step(batch, indices, fault=fault, validated=True)
            if metrics['optimizer_applied']:
                s['cursor'] = end; s['global_step'] += 1
                s['metrics'].append(dict(metrics, event='optimizer_step', cycle=s['cycle'],
                                         global_step=s['global_step'], cursor=end, pass_index=start // n))
                if end == len(s['order']):
                    self._finish_batch(batch, 'passes_complete')
            else:
                s['metrics'].append(dict(metrics, event='optimizer_diagnostic', cycle=s['cycle'], cursor=start))
                self._finish_batch(batch, 'kl_stop')
            self._commit(fault)
            return dict(metrics, stopped=s['phase'] == 'COMMITTED')

    def _finish_batch(self, batch, reason):
        if batch["batch_id"] in self.state["consumed"]:
            raise ValueError("double consumption")
        self.state["consumed"].append(batch["batch_id"])
        self.state["phase"] = "COMMITTED"
        self.state['metrics'].append({'event': reason, 'cycle': self.state['cycle'], 'batch_id': batch['batch_id']})

    def pause(self, paused=True):
        if type(paused) is not bool:
            raise ValueError("pause flag must be bool")
        with self._transaction():
            self.state["paused"] = paused
            self._commit()

    def status(self):
        with self._transaction():
            return {key: copy.deepcopy(self.state[key]) for key in ("phase", "paused", "cycle", "global_step", "update_attempts", "attempts", "decisions", "cursor", "consumed", "jobs")}

    def export(self, directory):
        with self._transaction():
            if self.state["phase"] not in ("READY", "COMMITTED"):
                raise ValueError("export only committed cycle boundaries")
            directory = Path(directory)
            if directory.exists():
                raise ValueError("export directory must be new")
            directory.mkdir(parents=True)
            return self.learner.model.export(directory / "weights.json", self.config["catalog_fingerprint"],
                                             provenance={"run_identity": self.identity, "commit": self.parent,
                                                         "cycle": self.state["cycle"], "sampling": "softmax-t1",
                                                         "not_promoted": True})
