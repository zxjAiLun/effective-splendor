"""Configuration profile loader for Splendor Pool."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib  # type: ignore
    except ImportError:
        tomllib = None  # type: ignore


@dataclass
class Config:
    config_path: Path
    data_dir: Path
    engine_exe: str
    initial_elo: float = 1500.0
    elo_k: float = 32.0
    poll_seconds: float = 2.0
    host: str = "127.0.0.1"
    port: int = 8720
    retain_replays: bool = True

    @classmethod
    def load(cls, path: Path | str) -> Config:
        p = Path(path).resolve()
        data: dict[str, Any] = {}
        if p.exists():
            if tomllib is not None:
                with p.open("rb") as f:
                    data = tomllib.load(f)
            else:
                # Basic key-value fallback parser for simple TOML
                data = cls._parse_simple_toml(p.read_text(encoding="utf-8"))

        base = p.parent
        raw_data_dir = data.get("data_dir", "data")
        data_dir = (base / raw_data_dir).resolve() if not Path(raw_data_dir).is_absolute() else Path(raw_data_dir)

        return cls(
            config_path=p,
            data_dir=data_dir,
            engine_exe=str(data.get("engine_exe", "/home/ubuntu/splendor/target/release/splendor")),
            initial_elo=float(data.get("initial_elo", 1500.0)),
            elo_k=float(data.get("elo_k", 32.0)),
            poll_seconds=float(data.get("poll_seconds", 2.0)),
            host=str(data.get("host", "127.0.0.1")),
            port=int(data.get("port", 8720)),
            retain_replays=bool(data.get("retain_replays", True)),
        )

    @classmethod
    def default(cls, base_dir: Path | str = ".") -> Config:
        base = Path(base_dir).resolve()
        return cls(
            config_path=base / "config.toml",
            data_dir=base / "data",
            engine_exe="/home/ubuntu/splendor/target/release/splendor",
        )

    @staticmethod
    def _parse_simple_toml(text: str) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if v.lower() == "true":
                    result[k] = True
                elif v.lower() == "false":
                    result[k] = False
                else:
                    try:
                        if "." in v:
                            result[k] = float(v)
                        else:
                            result[k] = int(v)
                    except ValueError:
                        result[k] = v
        return result
