"""通过持久子进程调用 Rust 规则引擎。"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any


class SplendorEnv:
    """一个实例管理一局游戏；reset 可以在同一进程里开始下一局。"""

    def __init__(self, executable: str | os.PathLike[str] = "splendor") -> None:
        self._process = subprocess.Popen(
            [os.fspath(executable), "env"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self._closed = False

    def _request(self, request: dict[str, Any]) -> dict[str, Any]:
        if self._closed:
            raise RuntimeError("规则环境已关闭")
        assert self._process.stdin is not None
        assert self._process.stdout is not None
        self._process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
        self._process.stdin.flush()
        line = self._process.stdout.readline()
        if not line:
            raise RuntimeError(f"规则进程已退出，退出码：{self._process.poll()}")
        response = json.loads(line)
        if response["type"] == "error":
            raise ValueError(response["message"])
        if response.get("env_version") != "1":
            raise RuntimeError("不支持的规则环境协议版本")
        return response

    def reset(self, *, seed: int = 0, player_count: int = 2) -> dict[str, Any]:
        """开始新局，返回当前行动者的观察、合法动作和玩家可见历史。"""
        return self._request({"type": "reset", "player_count": player_count, "seed": seed})

    def step(self, action: dict[str, Any]) -> dict[str, Any]:
        """提交一个语义动作，返回下一次决策状态；选择贵族时行动者可不变。"""
        return self._request({"type": "step", "action": action})

    def observe(self, player_id: int) -> dict[str, Any]:
        """读取指定玩家视角；非行动者的 legal_actions 为空。"""
        return self._request({"type": "observe", "player_id": player_id})

    def catalog(self) -> dict[str, Any]:
        """获取规则参数和稳定的牌库标识。"""
        return self._request({"type": "catalog"})

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        assert self._process.stdin is not None
        assert self._process.stdout is not None
        try:
            self._process.stdin.close()
        except BrokenPipeError:
            pass
        try:
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait()
        finally:
            self._process.stdout.close()

    def __enter__(self) -> SplendorEnv:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
