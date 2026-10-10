"""Zero-dependency HTTP server for Splendor Pool REST API and Web dashboard."""

from __future__ import annotations

import json
import mimetypes
import os
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .config import Config
from .store import Store

STATIC_DIR = Path(__file__).parent / "static"


class PoolRequestHandler(BaseHTTPRequestHandler):
    store: Store
    config: Config

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress noisy HTTP request logging
        return

    def _send_json(self, data: Any, status: int = HTTPStatus.OK) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(payload)

    def _send_file(self, file_path: Path, content_type: str | None = None) -> None:
        if not file_path.exists() or not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return
        if content_type is None:
            content_type, _ = mimetypes.guess_type(str(file_path))
        if content_type is None:
            content_type = "application/octet-stream"

        data = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        if not path:
            path = "/"

        if path == "/":
            self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            return
        if path.startswith("/static/"):
            rel = path[len("/static/"):]
            target = (STATIC_DIR / rel).resolve()
            if STATIC_DIR in target.parents or target == STATIC_DIR:
                self._send_file(target)
            else:
                self.send_error(HTTPStatus.FORBIDDEN)
            return

        # REST APIs
        if path == "/api/overview":
            self._send_json(self.store.get_overview_summary())
            return

        if path == "/api/models":
            models = self.store.list_models()
            res = [
                {
                    "id": m.id,
                    "name": m.name,
                    "model_type": m.model_type,
                    "weight": m.weight,
                    "enabled": m.enabled,
                    "created_at": m.created_at,
                    "elo": m.elo,
                    "games": m.games,
                    "wins": m.wins,
                    "ties": m.ties,
                    "losses": m.losses,
                    "stats": m.stats,
                }
                for m in models
            ]
            self._send_json(res)
            return

        m_trend = re.match(r"^/api/models/(\d+)/trend$", path)
        if m_trend:
            mid = int(m_trend.group(1))
            self._send_json(self.store.get_elo_trend(mid))
            return

        if path == "/api/matches":
            qs = parse_qs(parsed.query)
            limit = int(qs.get("limit", ["25"])[0])
            self._send_json(self.store.list_recent_matches(limit=limit))
            return

        m_match = re.match(r"^/api/matches/(\d+)$", path)
        if m_match:
            mid = int(m_match.group(1))
            recent = self.store.list_recent_matches(limit=100)
            target = next((x for x in recent if x["id"] == mid), None)
            if target:
                self._send_json(target)
            else:
                self.send_error(HTTPStatus.NOT_FOUND, "Match not found")
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Endpoint not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length > 0 else b"{}"
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            payload = {}

        if path == "/api/pause":
            paused = bool(payload.get("paused", True))
            self.store.pause(paused)
            self._send_json({"success": True, "paused": paused})
            return

        m_update = re.match(r"^/api/models/(\d+)/update$", path)
        if m_update:
            mid = int(m_update.group(1))
            weight = payload.get("weight")
            enabled = payload.get("enabled")
            name = payload.get("name")
            self.store.update_model(mid, weight=weight, enabled=enabled, name=name)
            self._send_json({"success": True, "model_id": mid})
            return

        self.send_error(HTTPStatus.NOT_FOUND)


def serve_web(config: Config) -> None:
    store = Store(config)
    store.initialize()

    handler_cls = type(
        "CustomPoolHandler",
        (PoolRequestHandler,),
        {"store": store, "config": config},
    )

    server = ThreadingHTTPServer((config.host, config.port), handler_cls)
    print(f"Splendor Pool Web Dashboard running on http://{config.host}:{config.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
