"""On-policy actor trajectories and clipped PPO, without any teacher CE."""
import math

import torch
from torch.nn import functional as F

from ..data import collate_states
from ..io import canonical_hash
from .contract import PPOConfig, number, validate_audit


def terminal_gae(values, outcome, lam):
    """gamma=1, own-decision time axis, real terminal only; never ply sign flip."""
    number(outcome, 0, 1, "outcome")
    number(lam, 0, 1, "lambda")
    if not values:
        raise ValueError("empty trajectory")
    for value in values:
        number(value, 0, 1, "old value")
    advantages, running = [0.0] * len(values), 0.0
    for i in range(len(values) - 1, -1, -1):
        next_value = outcome if i + 1 == len(values) else values[i + 1]
        running = next_value - values[i] + (lam * running if i + 1 < len(values) else 0)
        advantages[i] = running
    return advantages


def prepare_batch(games, behavior, config, *, max_decisions, style_returns=None, verify=True):
    """Join complete Arena actor shards (or explicit synthetic test fixtures).

    Live v2 trusts Arena's online rules and recorded behavior; legacy/manual
    auditing may request verify=True. Style reward extraction is a later gate.
    """
    if not isinstance(config, PPOConfig) or not games:
        raise ValueError("nonempty games and explicit PPOConfig required")
    if behavior.model.style_enabled != (config.style_beta > 0):
        raise ValueError("style architecture/config mismatch")
    expected_keys = {(game["job_id"], game["actor"]) for game in games}
    if len(expected_keys) != len(games):
        raise ValueError("duplicate game/actor shard")
    if config.style_beta > 0:
        if style_returns is None or set(style_returns) != expected_keys:
            raise ValueError("style targets must cover exactly the actor shards")
    elif style_returns is not None:
        raise ValueError("balanced run cannot accept style targets")
    rows = []
    for game in sorted(games, key=lambda x: (x["job_id"], x["actor"])):
        outcome = validate_audit(game, behavior_id=behavior.identity,
                                 catalog_fingerprint=behavior.catalog, max_decisions=max_decisions)
        decisions = game["decisions"]
        if len(rows) + len(decisions) > max_decisions:
            raise ValueError("batch decision budget exceeded")
        if verify:
            for row in decisions:
                behavior.verify(row, logp_tolerance=config.logp_tolerance, value_tolerance=config.value_tolerance)
        values = [row["response"]["value"] for row in decisions]
        adv = terminal_gae(values, outcome, config.gae_lambda)
        style_return = 0.0 if style_returns is None else number(style_returns[(game["job_id"], game["actor"])], 0, 1, "style return")
        for i, row in enumerate(decisions):
            old = row["response"]
            rows.append({"input": row["request"]["input"], "chosen": old["chosen_index"],
                         "old_logp": old["log_prob"], "old_probabilities": old["probabilities"],
                         "outcome": outcome, "style_return": style_return,
                         "advantage": adv[i] + config.style_beta * (style_return - old["style_value"]),
                         "key": [game["job_id"], game["actor"], i]})
    raw = [row["advantage"] for row in rows]
    mean = math.fsum(raw) / len(raw)
    std = math.sqrt(math.fsum((a - mean) ** 2 for a in raw) / len(raw))
    if config.normalize_advantage:
        for row in rows:
            row["advantage"] = (row["advantage"] - mean) / (std + 1e-8)
    content = {"format": "prism-ppo-batch-v1", "behavior_id": behavior.identity,
               "config_sha256": canonical_hash(config.to_dict()), "rows": rows,
               "advantage_mean": mean, "advantage_std": std,
               "games_sha256": canonical_hash(games)}
    return dict(content, batch_id=canonical_hash(content))


def validate_batch(batch, config):
    from .contract import exact, integer, sha, validate_input
    exact(batch, {"format", "behavior_id", "config_sha256", "rows", "advantage_mean", "advantage_std", "games_sha256", "batch_id"}, "batch")
    for key in ("behavior_id", "games_sha256", "batch_id"):
        sha(batch[key], key)
    number(batch["advantage_mean"], -math.inf, math.inf, "advantage mean")
    number(batch["advantage_std"], 0, math.inf, "advantage std")
    if not isinstance(batch["rows"], list) or not batch["rows"]:
        raise ValueError("empty batch")
    for row in batch["rows"]:
        exact(row, {"input", "chosen", "old_logp", "old_probabilities", "outcome", "style_return", "advantage", "key"}, "batch row")
        validate_input(row["input"])
        probs = row["old_probabilities"]
        if not isinstance(probs, list) or len(probs) != len(row["input"]["actions"]):
            raise ValueError("old probability count mismatch")
        for probability in probs:
            number(probability, 0, 1, "old probability")
        if abs(math.fsum(probs) - 1) > 1e-10:
            raise ValueError("old probabilities not normalized")
        integer(row["chosen"], 0, len(row["input"]["actions"]) - 1, "chosen")
        number(row["old_logp"], -math.inf, 0, "old logp")
        if probs[row["chosen"]] <= 0 or abs(math.log(probs[row["chosen"]]) - row["old_logp"]) > 1e-10:
            raise ValueError("old probability/logp mismatch")
        if row["outcome"] not in (0, 0.5, 1):
            raise ValueError("outcome is not a real terminal score")
        number(row["outcome"], 0, 1, "outcome")
        number(row["style_return"], 0, 1, "style return")
        number(row["advantage"], -math.inf, math.inf, "advantage")
    if batch.get("format") != "prism-ppo-batch-v1" or batch.get("config_sha256") != canonical_hash(config.to_dict()):
        raise ValueError("batch configuration/format mismatch")
    content = {k: v for k, v in batch.items() if k != "batch_id"}
    if batch.get("batch_id") != canonical_hash(content) or not batch.get("rows"):
        raise ValueError("batch hash/rows mismatch")


def clipped_surrogate(new_logp, old_logp, advantage, epsilon):
    ratio = torch.exp(new_logp - old_logp)
    if not torch.isfinite(ratio).all():
        raise ValueError("nonfinite importance ratio")
    return -torch.minimum(ratio * advantage, ratio.clamp(1 - epsilon, 1 + epsilon) * advantage).mean(), ratio


class Learner:
    def __init__(self, model, config):
        if model.style_enabled != (config.style_beta > 0):
            raise ValueError("style architecture/config mismatch")
        self.model, self.config = model, config
        self.optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad],
                                           lr=config.lr, weight_decay=config.weight_decay)

    def load_optimizer(self, state):
        self.optimizer.load_state_dict(state)
        for group in self.optimizer.param_groups:
            if group["lr"] != self.config.lr or group["weight_decay"] != self.config.weight_decay:
                raise ValueError("restored optimizer LR/weight_decay differs from contract")
        for slot in self.optimizer.state.values():
            for value in slot.values():
                if isinstance(value, torch.Tensor) and not torch.isfinite(value).all():
                    raise ValueError("nonfinite optimizer state")

    def _features(self, rows):
        # Singleton microbatches deliberately used for both behavior and gradient
        # accumulation: avoids dynamic padding memory and batch-shape drift in I.
        batch = collate_states([row["input"] for row in rows])
        return {k: v.to(next(self.model.parameters()).device) for k, v in batch.items()}

    def diagnostics(self, batch):
        validate_batch(batch, self.config)
        kls, ratios, entropies, normalized = [], [], [], []
        with torch.inference_mode():
            for row in batch["rows"]:
                logits, _, _ = self.model.forward_batch(self._features([row]))
                lp = torch.log_softmax(logits[0].double(), -1)
                p = lp.exp()
                old = torch.tensor(row["old_probabilities"], device=p.device, dtype=torch.float64)
                positive = old > 0
                kl = (old[positive] * (old[positive].log() - lp[positive])).sum().item()
                entropy = -(p * lp).sum().item()
                ratio = math.exp(lp[row["chosen"]].item() - row["old_logp"])
                kls.append(max(0.0, kl)); ratios.append(ratio); entropies.append(entropy)
                if len(old) > 1:
                    normalized.append(entropy / math.log(len(old)))
        metrics = {"kl": math.fsum(kls) / len(kls), "entropy": math.fsum(entropies) / len(entropies),
                   "normalized_entropy": math.fsum(normalized) / len(normalized) if normalized else 0.0,
                   "clip_fraction": sum(abs(r - 1) > self.config.clip_epsilon for r in ratios) / len(ratios),
                   "max_ratio_error": max(abs(r - 1) for r in ratios)}
        if not all(math.isfinite(v) for v in metrics.values()):
            raise ValueError("nonfinite PPO diagnostics")
        return metrics

    def step(self, batch, indices, *, fault=None, validated=False):
        # Public calls remain strict; Run validated the resident batch at the
        # seal/recovery boundary, so its hot path checks only these indices.
        if not validated:
            validate_batch(batch, self.config)
        if not indices or len(indices) > self.config.minibatch_size or len(set(indices)) != len(indices):
            raise ValueError('invalid minibatch indices')
        if any(type(i) is not int or not 0 <= i < len(batch['rows']) for i in indices):
            raise ValueError('minibatch index outside batch')
        self.model.train()
        self.optimizer.zero_grad(set_to_none=True)
        totals = {key: 0.0 for key in ('policy_loss', 'outcome_bce', 'style_mse', 'entropy',
                                      'kl', 'clip_fraction', 'normalized_entropy')}
        normalized_count = 0
        max_ratio_error = 0.0
        for index in indices:
            row = batch['rows'][index]
            logits, value, style = self.model.forward_batch(self._features([row]))
            lp = torch.log_softmax(logits[0].double(), -1)
            logp = lp[row['chosen']]
            old = logp.new_tensor(row['old_logp'])
            advantage = logp.new_tensor(row['advantage'])
            policy, ratio = clipped_surrogate(logp, old, advantage, self.config.clip_epsilon)
            outcome = F.binary_cross_entropy_with_logits(value, value.new_tensor([row['outcome']]))
            style_loss = F.mse_loss(style, style.new_tensor([row['style_return']])) if self.model.style_enabled else style.sum() * 0
            entropy = -(lp.exp() * lp).sum()
            # Exact old||new KL reuses this pre-update training forward.
            with torch.no_grad():
                old_probs = lp.new_tensor(row['old_probabilities'])
                positive = old_probs > 0
                kl = max(0.0, (old_probs[positive] * (old_probs[positive].log() - lp[positive])).sum().item())
                ratio_error = abs(ratio.item() - 1)
                totals['kl'] += kl / len(indices)
                totals['clip_fraction'] += int(ratio_error > self.config.clip_epsilon) / len(indices)
                max_ratio_error = max(max_ratio_error, ratio_error)
                if len(old_probs) > 1:
                    totals['normalized_entropy'] += entropy.item() / math.log(len(old_probs))
                    normalized_count += 1
            loss = policy + self.config.value_weight * outcome + self.config.style_value_weight * style_loss - self.config.entropy_weight * entropy
            if not torch.isfinite(loss):
                raise ValueError('nonfinite PPO loss')
            (loss / len(indices)).backward()
            for key, term in zip(('policy_loss', 'outcome_bce', 'style_mse', 'entropy'), (policy, outcome, style_loss, entropy)):
                totals[key] += term.item() / len(indices)
        totals['normalized_entropy'] /= normalized_count or 1
        totals['max_ratio_error'] = max_ratio_error
        if not all(math.isfinite(value) for value in totals.values()):
            raise ValueError('nonfinite PPO diagnostics')
        if fault:
            fault('backward_done')
        norm = torch.nn.utils.clip_grad_norm_(self.model.parameters(), self.config.max_grad_norm, error_if_nonfinite=True)
        applied = totals['kl'] <= self.config.target_kl
        if applied:
            self.optimizer.step()
            if fault:
                fault('optimizer_done')
            if any(not torch.isfinite(p).all() for p in self.model.parameters()):
                raise ValueError('nonfinite updated weights')
        totals.update(grad_norm=norm.item(), samples=len(indices), optimizer_applied=applied)
        self.optimizer.zero_grad(set_to_none=True)
        return totals
