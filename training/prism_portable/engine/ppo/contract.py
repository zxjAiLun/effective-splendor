"""Strict M54 messages/configuration. Metadata is never a network feature."""
from dataclasses import asdict, dataclass
import math
import re

from ..data import collate_states
from ..io import canonical_hash

MAX_MESSAGE_BYTES = 16 * 1024 * 1024
REQUEST_KEYS = {"format", "behavior_id", "job_id", "game_id", "actor", "request_id",
                "decision_index", "catalog_fingerprint", "input"}
RESPONSE_KEYS = {"format", "behavior_id", "job_id", "game_id", "actor", "request_id",
                 "decision_index", "chosen_index", "log_prob", "value", "style_value", "probabilities"}
ROW_KEYS = {"format", "request", "response", "observation", "visible_history", "legal_actions", "chosen_action"}
AUDIT_KEYS = {"format", "behavior_id", "job_id", "actor", "game_id", "catalog_fingerprint",
              "replay_sha256", "sidecar_sha256", "terminal", "result", "decisions"}


def exact(value, keys, name):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(f"{name}: unknown/missing fields")


def integer(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name}: integer outside [{low},{high}]")
    return value


def number(value, low, high, name):
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and low <= value <= high
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f"{name}: invalid finite number")
    return float(value)


def text(value, name):
    if not isinstance(value, str) or not value or len(value) > 256 or any(ord(c) < 32 for c in value):
        raise ValueError(f"{name}: invalid string")
    return value


def sha(value, name):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{name}: expected lowercase sha256")
    return value


def validate_input(value):
    exact(value, {"entities", "actions", "targets"}, "encoded input")
    # Reject bool coercion before NumPy can turn mixed JSON lists into integers.
    for key, width, maximum in (("entities", 96, 128), ("actions", 80, 4096)):
        rows = value[key]
        if not isinstance(rows, list) or not 1 <= len(rows) <= maximum:
            raise ValueError(f"{key}: invalid row count")
        for row in rows:
            if not isinstance(row, list) or len(row) != width:
                raise ValueError(f"{key}: invalid width")
            for x in row:
                if type(x) not in (int, float) or not math.isfinite(x):
                    raise ValueError(f"{key}: expected finite real numbers, never bool")
    target_bound = len(value["entities"])
    if not isinstance(value["targets"], list):
        raise ValueError("targets required")
    for t in value["targets"]:
        if type(t) is not int or not (-1 <= t < target_bound):
            raise ValueError("targets require JSON integers, never bool")
    return value


def validate_request(value, *, authenticated=False):
    exact(value, REQUEST_KEYS | ({"token"} if authenticated else set()), "request")
    if value["format"] != "prism-ppo-request-v1":
        raise ValueError("request format")
    sha(value["behavior_id"], "behavior_id")
    for key in ("job_id", "game_id", "catalog_fingerprint"):
        text(value[key], key)
    integer(value["actor"], 0, 1, "actor")
    integer(value["request_id"], 1, 2**63 - 1, "request_id")
    integer(value["decision_index"], 0, 2**63 - 1, "decision_index")
    if authenticated:
        text(value["token"], "token")
    validate_input(value["input"])
    return value


def validate_response(response, request):
    exact(response, RESPONSE_KEYS, "response")
    if response["format"] != "prism-ppo-response-v1":
        raise ValueError("response format")
    for key in ("behavior_id", "job_id", "game_id", "actor", "request_id", "decision_index"):
        if type(response[key]) is not type(request[key]) or response[key] != request[key]:
            raise ValueError(f"response {key} mismatch")
    n = len(request["input"]["actions"])
    index = integer(response["chosen_index"], 0, n - 1, "chosen_index")
    probs = response["probabilities"]
    if not isinstance(probs, list) or len(probs) != n:
        raise ValueError("probability count mismatch")
    for p in probs:
        number(p, 0, 1, "probability")
    if abs(math.fsum(probs) - 1) > 1e-10 or probs[index] <= 0:
        raise ValueError("invalid probability distribution")
    lp = number(response["log_prob"], -math.inf, 0, "log_prob")
    if abs(math.log(probs[index]) - lp) > 1e-10:
        raise ValueError("log_prob is not the sampled probability")
    number(response["value"], 0, 1, "value")
    number(response["style_value"], -math.inf, math.inf, "style_value")
    return response


def validate_row(row):
    exact(row, ROW_KEYS, "decision")
    if row["format"] != "prism-ppo-decision-v1":
        raise ValueError("decision format")
    req = validate_request(row["request"])
    response = validate_response(row["response"], req)
    legal = row["legal_actions"]
    if not isinstance(legal, list) or len(legal) != len(req["input"]["actions"]):
        raise ValueError("legal actions count")
    if any(not isinstance(a, dict) for a in legal):
        raise ValueError("invalid legal actions")
    if row["chosen_action"] != legal[response["chosen_index"]]:
        raise ValueError("chosen semantic action mismatch")
    if not isinstance(row["visible_history"], list) or not isinstance(row["observation"], dict):
        raise ValueError("missing player projection")
    # Rules/projection/semantic action correctness are checked by the Rust auditor.
    # This verifier must not pretend that a Python structural check replaces it.
    return row


def validate_audit(game, *, behavior_id, catalog_fingerprint, max_decisions):
    exact(game, AUDIT_KEYS, "audit")
    if game["format"] not in ("prism-ppo-audit-v1", "prism-ppo-game-v1") or game["terminal"] is not True:
        raise ValueError("requires a real terminal audit, never truncation/abort")
    if game["behavior_id"] != behavior_id or game["catalog_fingerprint"] != catalog_fingerprint:
        raise ValueError("audit behavior/catalog mismatch")
    sha(behavior_id, "behavior_id")
    for key in ("replay_sha256", "sidecar_sha256"):
        sha(game[key], key)
    actor = integer(game["actor"], 0, 1, "actor")
    text(game["job_id"], "job_id"); text(game["game_id"], "game_id")
    result = game["result"]
    exact(result, {"scores", "ranks", "winners", "reason"}, "result")
    if result["reason"] not in ("prestige_threshold", "stalemate"):
        raise ValueError("not a core terminal reason")
    for key in ("scores", "ranks"):
        if not isinstance(result[key], list) or len(result[key]) != 2:
            raise ValueError("only two players supported")
        for x in result[key]:
            integer(x, 0, 255 if key == "scores" else 1, key)
    if result["ranks"] not in ([0, 0], [0, 1], [1, 0]):
        raise ValueError("invalid two-player ranks")
    winners = [p for p in range(2) if result["ranks"][p] == 0]
    if not isinstance(result["winners"], list) or any(type(x) is not int for x in result["winners"]) or sorted(result["winners"]) != winners:
        raise ValueError("winners/ranks mismatch")
    decisions = game["decisions"]
    if not isinstance(decisions, list) or not 1 <= len(decisions) <= max_decisions:
        raise ValueError("invalid trajectory size")
    last_request = 0
    for index, row in enumerate(decisions):
        validate_row(row)
        req = row["request"]
        for key in ("behavior_id", "catalog_fingerprint", "job_id", "game_id", "actor"):
            if req[key] != game[key]:
                raise ValueError(f"trajectory {key} mismatch")
        if req["decision_index"] != index or req["request_id"] <= last_request:
            raise ValueError("duplicate/gap/unordered actor trajectory")
        last_request = req["request_id"]
    return 0.5 if result["ranks"][0] == result["ranks"][1] else float(result["ranks"][actor] == 0)


@dataclass(frozen=True)
class PPOConfig:
    lr: float
    weight_decay: float
    clip_epsilon: float
    value_weight: float
    style_value_weight: float
    entropy_weight: float
    gae_lambda: float
    style_beta: float
    passes: int
    minibatch_size: int
    max_grad_norm: float
    target_kl: float
    logp_tolerance: float
    value_tolerance: float
    normalize_advantage: bool

    def __post_init__(self):
        for key in ("lr", "max_grad_norm", "target_kl", "logp_tolerance", "value_tolerance"):
            if number(getattr(self, key), 0, math.inf, key) <= 0:
                raise ValueError(f"{key} must be positive")
        if not 0 < number(self.clip_epsilon, 0, 1, "clip_epsilon") < 1:
            raise ValueError("clip_epsilon must be in (0,1)")
        for key in ("weight_decay", "value_weight", "style_value_weight", "entropy_weight", "style_beta"):
            number(getattr(self, key), 0, math.inf, key)
        number(self.gae_lambda, 0, 1, "gae_lambda")
        integer(self.passes, 1, 100, "passes")
        integer(self.minibatch_size, 1, 4096, "minibatch_size")
        if type(self.normalize_advantage) is not bool:
            raise ValueError("normalize_advantage must be bool")
        if self.style_beta == 0 and self.style_value_weight != 0:
            raise ValueError("balanced policy disables style loss")
        if self.style_beta > 0 and self.style_value_weight <= 0:
            raise ValueError("style policy requires its critic loss")

    @classmethod
    def from_dict(cls, value):
        exact(value, cls.__dataclass_fields__, "PPO config")
        return cls(**value)

    def to_dict(self):
        return asdict(self)
