"""Model definitions and agent adapters for Splendor arena."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AgentConfig:
    """Configuration for an agent subprocess in Splendor arena."""
    program: str
    args: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {"program": self.program, "args": self.args}


@dataclass
class ModelSpec:
    id: int | None = None
    name: str = ""
    model_type: str = "custom"  # heuristic, m50-policy, prism, custom
    config_json: str = "{}"
    weight: float = 1.0
    enabled: bool = True
    created_at: str = ""
    elo: float = 1500.0
    games: int = 0
    wins: int = 0
    ties: int = 0
    losses: int = 0
    stats_json: str = "{}"

    @property
    def config(self) -> dict[str, Any]:
        try:
            return json.loads(self.config_json)
        except Exception:
            return {}

    @property
    def stats(self) -> dict[str, Any]:
        try:
            return json.loads(self.stats_json)
        except Exception:
            return {}

    def to_agent_config(self, default_exe: str, seed: int | None = None) -> AgentConfig:
        """Create the execution config for run-match subprocess."""
        cfg = self.config
        program = cfg.get("program") or default_exe
        seed_val = str(seed if seed is not None else 42)

        if self.model_type == "heuristic":
            subcmd = cfg.get("subcommand", "agent-heuristic-v02")
            extra_args = list(cfg.get("extra_args", []))
            if "--seed" not in extra_args:
                extra_args.extend(["--seed", seed_val])
            args = [subcmd] + extra_args
        elif self.model_type == "m50-policy":
            weights = cfg.get("weights")
            mode = cfg.get("mode", "greedy")
            args = ["agent-m50-policy"]
            if weights:
                args.extend(["--weights", str(weights)])
            args.extend(["--mode", mode])
            if "extra_args" in cfg:
                args.extend(cfg["extra_args"])
        elif self.model_type == "prism":
            weights = cfg.get("weights")
            args = ["agent-prism"]
            if weights:
                args.extend(["--weights", str(weights)])
            if "extra_args" in cfg:
                args.extend(cfg["extra_args"])
        else:
            args = list(cfg.get("args", ["agent-heuristic"]))
            if args and args[0].startswith("agent-heuristic") and "--seed" not in args:
                args.extend(["--seed", seed_val])

        return AgentConfig(program=program, args=args)


def create_heuristic_spec(
    name: str,
    subcommand: str = "agent-heuristic-v02",
    program: str | None = None,
    extra_args: list[str] | None = None,
    weight: float = 1.0,
) -> ModelSpec:
    cfg = {"subcommand": subcommand, "extra_args": extra_args or []}
    if program:
        cfg["program"] = program
    return ModelSpec(
        name=name,
        model_type="heuristic",
        config_json=json.dumps(cfg),
        weight=weight,
    )


def create_m50_policy_spec(
    name: str,
    weights_path: str,
    mode: str = "greedy",
    program: str | None = None,
    weight: float = 1.0,
) -> ModelSpec:
    cfg = {"weights": str(weights_path), "mode": mode}
    if program:
        cfg["program"] = program
    return ModelSpec(
        name=name,
        model_type="m50-policy",
        config_json=json.dumps(cfg),
        weight=weight,
    )


def create_custom_spec(
    name: str,
    args: list[str],
    program: str | None = None,
    weight: float = 1.0,
) -> ModelSpec:
    cfg = {"args": args}
    if program:
        cfg["program"] = program
    return ModelSpec(
        name=name,
        model_type="custom",
        config_json=json.dumps(cfg),
        weight=weight,
    )
