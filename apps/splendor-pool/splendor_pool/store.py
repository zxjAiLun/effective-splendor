"""SQLite WAL persistence ledger for Splendor Pool."""

from __future__ import annotations

import json
import random
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import Config
from .elo import EloResult
from .models import ModelSpec


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, config: Config):
        self.config = config
        self.root = config.data_dir
        self.db_path = self.root / "pool.sqlite3"

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        self.root.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=30.0,
            isolation_level=None,  # Autocommit mode; transactions managed explicitly
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        try:
            yield conn
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS models (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    model_type TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    weight REAL NOT NULL DEFAULT 1.0 CHECK(weight >= 0),
                    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
                    created_at TEXT NOT NULL,
                    elo REAL NOT NULL DEFAULT 1500.0,
                    games INTEGER NOT NULL DEFAULT 0,
                    wins INTEGER NOT NULL DEFAULT 0,
                    ties INTEGER NOT NULL DEFAULT 0,
                    losses INTEGER NOT NULL DEFAULT 0,
                    stats_json TEXT NOT NULL DEFAULT '{}'
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS matches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    seed INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending', 'running', 'completed', 'error')),
                    p0_id INTEGER NOT NULL REFERENCES models(id),
                    p1_id INTEGER NOT NULL REFERENCES models(id),
                    winner_id INTEGER REFERENCES models(id),
                    p0_score INTEGER,
                    p1_score INTEGER,
                    completed_plies INTEGER,
                    started_at TEXT,
                    completed_at TEXT,
                    error TEXT,
                    replay_path TEXT,
                    report_path TEXT
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS elo_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    match_id INTEGER NOT NULL REFERENCES matches(id),
                    model_id INTEGER NOT NULL REFERENCES models(id),
                    elo_before REAL NOT NULL,
                    elo_after REAL NOT NULL,
                    elo_delta REAL NOT NULL,
                    recorded_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_matches_status ON matches(status, id);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_elo_model ON elo_history(model_id, id);"
            )
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES ('paused', '0');"
            )
            conn.execute("COMMIT;")

    def pause(self, paused: bool) -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('paused', ?);",
                ("1" if paused else "0",),
            )

    def is_paused(self) -> bool:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = 'paused';"
            ).fetchone()
            return row["value"] == "1" if row else False

    def add_model(self, spec: ModelSpec) -> int:
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            cur = conn.execute(
                """
                INSERT INTO models (
                    name, model_type, config_json, weight, enabled,
                    created_at, elo, games, wins, ties, losses, stats_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0, '{}');
                """,
                (
                    spec.name,
                    spec.model_type,
                    spec.config_json,
                    spec.weight,
                    1 if spec.enabled else 0,
                    spec.created_at or now_iso(),
                    spec.elo or self.config.initial_elo,
                ),
            )
            model_id = cur.lastrowid
            conn.execute("COMMIT;")
            return model_id

    def update_model(
        self,
        model_id: int,
        weight: float | None = None,
        enabled: bool | None = None,
        name: str | None = None,
    ) -> None:
        clauses = []
        params = []
        if weight is not None:
            clauses.append("weight = ?")
            params.append(float(weight))
        if enabled is not None:
            clauses.append("enabled = ?")
            params.append(1 if enabled else 0)
        if name is not None:
            clauses.append("name = ?")
            params.append(str(name))

        if not clauses:
            return

        params.append(model_id)
        sql = f"UPDATE models SET {', '.join(clauses)} WHERE id = ?;"
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            conn.execute(sql, params)
            conn.execute("COMMIT;")

    def get_model(self, model_id: int) -> ModelSpec | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM models WHERE id = ?;", (model_id,)).fetchone()
            if not row:
                return None
            return self._row_to_spec(row)

    def get_model_by_name(self, name: str) -> ModelSpec | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM models WHERE name = ?;", (name,)).fetchone()
            if not row:
                return None
            return self._row_to_spec(row)

    def list_models(self, only_enabled: bool = False) -> list[ModelSpec]:
        sql = "SELECT * FROM models"
        if only_enabled:
            sql += " WHERE enabled = 1 AND weight > 0"
        sql += " ORDER BY elo DESC, wins DESC, id ASC;"
        with self.connection() as conn:
            rows = conn.execute(sql).fetchall()
            return [self._row_to_spec(r) for r in rows]

    def sample_matchup(self) -> tuple[ModelSpec, ModelSpec] | None:
        """Sample two distinct enabled models according to their weights."""
        models = self.list_models(only_enabled=True)
        if len(models) < 2:
            return None

        # Weighted sampling without replacement for 2 distinct models
        weights = [max(0.001, m.weight) for m in models]
        p0 = random.choices(models, weights=weights, k=1)[0]
        
        remaining_models = [m for m in models if m.id != p0.id]
        remaining_weights = [max(0.001, m.weight) for m in remaining_models]
        p1 = random.choices(remaining_models, weights=remaining_weights, k=1)[0]

        # 50% random seat assignment to eliminate seat bias
        if random.random() < 0.5:
            return p0, p1
        return p1, p0

    def create_match(self, p0_id: int, p1_id: int, seed: int) -> int:
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            cur = conn.execute(
                """
                INSERT INTO matches (
                    seed, status, p0_id, p1_id, started_at
                ) VALUES (?, 'pending', ?, ?, ?);
                """,
                (seed, p0_id, p1_id, now_iso()),
            )
            match_id = cur.lastrowid
            conn.execute("COMMIT;")
            return match_id

    def start_match(self, match_id: int) -> None:
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            conn.execute(
                "UPDATE matches SET status = 'running', started_at = ? WHERE id = ?;",
                (now_iso(), match_id),
            )
            conn.execute("COMMIT;")

    def complete_match(
        self,
        match_id: int,
        winner_id: int | None,
        p0_score: int,
        p1_score: int,
        completed_plies: int,
        replay_path: str,
        report_path: str,
        elo_result: EloResult,
        p0_new_stats_json: str,
        p1_new_stats_json: str,
    ) -> None:
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            # 1. Update match record
            conn.execute(
                """
                UPDATE matches SET
                    status = 'completed',
                    winner_id = ?,
                    p0_score = ?,
                    p1_score = ?,
                    completed_plies = ?,
                    completed_at = ?,
                    replay_path = ?,
                    report_path = ?
                WHERE id = ?;
                """,
                (
                    winner_id,
                    p0_score,
                    p1_score,
                    completed_plies,
                    now_iso(),
                    replay_path,
                    report_path,
                    match_id,
                ),
            )

            # Get player IDs
            match_row = conn.execute(
                "SELECT p0_id, p1_id FROM matches WHERE id = ?;", (match_id,)
            ).fetchone()
            p0_id = match_row["p0_id"]
            p1_id = match_row["p1_id"]

            now = now_iso()
            # 2. Record Elo history for both
            conn.execute(
                """
                INSERT INTO elo_history (
                    match_id, model_id, elo_before, elo_after, elo_delta, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?);
                """,
                (
                    match_id,
                    p0_id,
                    elo_result.elo_before_a,
                    elo_result.elo_after_a,
                    elo_result.delta_a,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO elo_history (
                    match_id, model_id, elo_before, elo_after, elo_delta, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?);
                """,
                (
                    match_id,
                    p1_id,
                    elo_result.elo_before_b,
                    elo_result.elo_after_b,
                    elo_result.delta_b,
                    now,
                ),
            )

            # 3. Update model tables
            p0_win_add = 1 if elo_result.score_a == 1.0 else 0
            p0_tie_add = 1 if elo_result.score_a == 0.5 else 0
            p0_loss_add = 1 if elo_result.score_a == 0.0 else 0

            p1_win_add = 1 if elo_result.score_b == 1.0 else 0
            p1_tie_add = 1 if elo_result.score_b == 0.5 else 0
            p1_loss_add = 1 if elo_result.score_b == 0.0 else 0

            conn.execute(
                """
                UPDATE models SET
                    elo = ?,
                    games = games + 1,
                    wins = wins + ?,
                    ties = ties + ?,
                    losses = losses + ?,
                    stats_json = ?
                WHERE id = ?;
                """,
                (
                    elo_result.elo_after_a,
                    p0_win_add,
                    p0_tie_add,
                    p0_loss_add,
                    p0_new_stats_json,
                    p0_id,
                ),
            )
            conn.execute(
                """
                UPDATE models SET
                    elo = ?,
                    games = games + 1,
                    wins = wins + ?,
                    ties = ties + ?,
                    losses = losses + ?,
                    stats_json = ?
                WHERE id = ?;
                """,
                (
                    elo_result.elo_after_b,
                    p1_win_add,
                    p1_tie_add,
                    p1_loss_add,
                    p1_new_stats_json,
                    p1_id,
                ),
            )
            conn.execute("COMMIT;")

    def fail_match(self, match_id: int, error: str) -> None:
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            conn.execute(
                "UPDATE matches SET status = 'error', error = ?, completed_at = ? WHERE id = ?;",
                (error, now_iso(), match_id),
            )
            conn.execute("COMMIT;")

    def list_recent_matches(self, limit: int = 15) -> list[dict[str, Any]]:
        with self.connection() as conn:
            cur = conn.execute(
                """
                SELECT
                    m.id, m.seed, m.status, m.p0_id, m.p1_id, m.winner_id,
                    m.p0_score, m.p1_score, m.completed_plies, m.completed_at,
                    m.error, m.replay_path,
                    p0.name as p0_name, p1.name as p1_name,
                    w.name as winner_name,
                    h0.elo_before as p0_elo_before, h0.elo_after as p0_elo_after, h0.elo_delta as p0_elo_delta,
                    h1.elo_before as p1_elo_before, h1.elo_after as p1_elo_after, h1.elo_delta as p1_elo_delta
                FROM matches m
                JOIN models p0 ON m.p0_id = p0.id
                JOIN models p1 ON m.p1_id = p1.id
                LEFT JOIN models w ON m.winner_id = w.id
                LEFT JOIN elo_history h0 ON h0.match_id = m.id AND h0.model_id = m.p0_id
                LEFT JOIN elo_history h1 ON h1.match_id = m.id AND h1.model_id = m.p1_id
                ORDER BY m.id DESC LIMIT ?;
                """,
                (limit,),
            )
            rows = cur.fetchall()
            return [dict(r) for r in rows]

    def get_elo_trend(self, model_id: int, limit: int = 200) -> list[dict[str, Any]]:
        with self.connection() as conn:
            cur = conn.execute(
                """
                SELECT match_id, elo_before, elo_after, elo_delta, recorded_at
                FROM elo_history
                WHERE model_id = ?
                ORDER BY id ASC LIMIT ?;
                """,
                (model_id, limit),
            )
            return [dict(r) for r in cur.fetchall()]

    def get_overview_summary(self) -> dict[str, Any]:
        with self.connection() as conn:
            total_models = conn.execute("SELECT COUNT(*) FROM models;").fetchone()[0]
            active_models = conn.execute("SELECT COUNT(*) FROM models WHERE enabled = 1;").fetchone()[0]
            total_matches = conn.execute("SELECT COUNT(*) FROM matches WHERE status = 'completed';").fetchone()[0]
            paused = self.is_paused()
            top_model = conn.execute("SELECT name, elo FROM models ORDER BY elo DESC LIMIT 1;").fetchone()
            top_info = {"name": top_model["name"], "elo": top_model["elo"]} if top_model else None

            return {
                "total_models": total_models,
                "active_models": active_models,
                "completed_matches": total_matches,
                "is_paused": paused,
                "top_model": top_info,
            }

    @staticmethod
    def _row_to_spec(row: sqlite3.Row) -> ModelSpec:
        return ModelSpec(
            id=row["id"],
            name=row["name"],
            model_type=row["model_type"],
            config_json=row["config_json"],
            weight=row["weight"],
            enabled=bool(row["enabled"]),
            created_at=row["created_at"],
            elo=row["elo"],
            games=row["games"],
            wins=row["wins"],
            ties=row["ties"],
            losses=row["losses"],
            stats_json=row["stats_json"],
        )
