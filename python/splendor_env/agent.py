"""NDJSON v0.5 玩家视角 Agent 运行时。"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any, Callable, TextIO


@dataclass(frozen=True)
class Decision:
    observation: dict[str, Any]
    visible_history: tuple[dict[str, Any], ...]
    legal_actions: list[dict[str, Any]]
    player_id: int
    game_id: str
    request_id: int
    deadline_ms: int


def run_agent(
    choose_action: Callable[[Decision], dict[str, Any]],
    *,
    name: str,
    version: str = "0.1.0",
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
) -> dict[str, Any]:
    """运行一场比赛；返回 game_end 或 game_truncated，协议错误抛出异常。"""
    if input_stream is None:
        sys.stdin.reconfigure(encoding="utf-8")
    source = sys.stdin if input_stream is None else input_stream
    target = sys.stdout if output_stream is None else output_stream
    game_id = None
    seat = None
    observation = None
    observation_hash = None
    last_request_id = -1
    history: list[dict[str, Any]] = []

    def send(kind: str, **fields: Any) -> None:
        message = {"type": kind, "protocol_version": "0.5", "game_id": game_id, **fields}
        target.write(json.dumps(message, ensure_ascii=True, separators=(",", ":")) + "\n")
        target.flush()

    for line in source:
        if not line.strip():
            continue
        message = json.loads(line)
        kind = message["type"]
        if message["protocol_version"] != "0.5":
            raise ValueError("不支持的 Agent 协议版本")
        if kind == "hello":
            if game_id is not None:
                raise ValueError("重复的 hello")
            game_id = message["game_id"]
            send("hello", agent_name=name, agent_version=version)
            continue
        if game_id is None or message["game_id"] != game_id:
            raise ValueError("消息不属于当前比赛")
        if kind == "game_start":
            if seat is not None:
                raise ValueError("重复的 game_start")
            seat = message["recipient_player_id"]
            continue
        if seat is None or message["recipient_player_id"] != seat:
            raise ValueError("消息不属于当前座位")
        if kind == "observation":
            observation = message["observation"]
            if observation["viewer"] != seat:
                raise ValueError("观察视角与座位不一致")
            observation_hash = message["observation_hash"]
        elif kind == "event":
            history.append(message["event"])
        elif kind == "action_applied":
            history.append({"type": "action_applied", "player": message["actor_player_id"],
                            "action": message["action"]})
        elif kind == "request_action":
            if observation is None or message["observation_hash"] != observation_hash:
                raise ValueError("动作请求与当前观察不一致")
            request_id = message["request_id"]
            if request_id <= last_request_id:
                raise ValueError("request_id 必须递增")
            legal_actions = message["legal_actions"]
            if not legal_actions:
                raise ValueError("动作请求没有合法动作")
            action = choose_action(Decision(
                observation=observation,
                visible_history=tuple(history),
                legal_actions=legal_actions,
                player_id=seat,
                game_id=game_id,
                request_id=request_id,
                deadline_ms=message["deadline_ms"],
            ))
            if action not in legal_actions:
                raise ValueError("策略返回的动作不在 legal_actions 中")
            send("action", request_id=request_id, action=action)
            last_request_id = request_id
        elif kind == "ping":
            send("pong")
        elif kind in ("game_end", "game_truncated"):
            return message
        elif kind == "error":
            raise RuntimeError(message["message"])
        else:
            raise ValueError(f"未知服务端消息：{kind}")
    raise EOFError("比赛结束前服务端关闭了连接")
