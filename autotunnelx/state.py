from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable


class StateStore:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS tunnel_status (
                    name TEXT PRIMARY KEY,
                    protocol TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 0,
                    latency_ms REAL,
                    jitter_ms REAL,
                    packet_loss_pct REAL,
                    throughput_mbps REAL,
                    score REAL,
                    last_error TEXT,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    latency_ms REAL,
                    jitter_ms REAL,
                    packet_loss_pct REAL,
                    throughput_mbps REAL,
                    score REAL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_metrics_name_time ON metrics(name, created_at);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    name TEXT,
                    payload TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS kv (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
                """
            )

    def upsert_tunnel(self, spec: dict[str, Any], status: dict[str, Any]) -> None:
        now = time.time()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO tunnel_status
                  (name, protocol, mode, enabled, status, active, latency_ms, jitter_ms,
                   packet_loss_pct, throughput_mbps, score, last_error, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                  protocol=excluded.protocol,
                  mode=excluded.mode,
                  enabled=excluded.enabled,
                  status=excluded.status,
                  active=excluded.active,
                  latency_ms=excluded.latency_ms,
                  jitter_ms=excluded.jitter_ms,
                  packet_loss_pct=excluded.packet_loss_pct,
                  throughput_mbps=excluded.throughput_mbps,
                  score=excluded.score,
                  last_error=excluded.last_error,
                  updated_at=excluded.updated_at
                """,
                (
                    spec.get("name"),
                    spec.get("type"),
                    spec.get("mode", "proxy"),
                    1 if spec.get("enabled", True) else 0,
                    status.get("status", "unknown"),
                    1 if status.get("active") else 0,
                    status.get("latency_ms"),
                    status.get("jitter_ms"),
                    status.get("packet_loss_pct"),
                    status.get("throughput_mbps"),
                    status.get("score"),
                    status.get("last_error"),
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO metrics
                  (name, latency_ms, jitter_ms, packet_loss_pct, throughput_mbps, score, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    spec.get("name"),
                    status.get("latency_ms"),
                    status.get("jitter_ms"),
                    status.get("packet_loss_pct"),
                    status.get("throughput_mbps"),
                    status.get("score"),
                    status.get("status", "unknown"),
                    now,
                ),
            )

    def set_active(self, names: Iterable[str]) -> None:
        active_names = set(names)
        with self.connect() as conn:
            conn.execute("UPDATE tunnel_status SET active = 0")
            conn.executemany("UPDATE tunnel_status SET active = 1 WHERE name = ?", [(name,) for name in active_names])
            conn.execute(
                """
                INSERT INTO kv(key, value, updated_at) VALUES ('active_names', ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (json.dumps(sorted(active_names), separators=(",", ":")), time.time()),
            )

    def list_status(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM tunnel_status ORDER BY active DESC, score DESC, name ASC").fetchall()
        return [dict(row) for row in rows]

    def history(self, name: str | None = None, limit: int = 240) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if name:
                rows = conn.execute(
                    "SELECT * FROM metrics WHERE name = ? ORDER BY created_at DESC LIMIT ?",
                    (name, limit),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM metrics ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in reversed(rows)]

    def event(self, event_type: str, name: str | None = None, payload: dict[str, Any] | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO events(event_type, name, payload, created_at) VALUES (?, ?, ?, ?)",
                (event_type, name, json.dumps(payload or {}, separators=(",", ":")), time.time()),
            )

    def set_kv(self, key: str, value: Any) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO kv(key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (key, json.dumps(value, separators=(",", ":")), time.time()),
            )

    def get_kv(self, key: str, default: Any = None) -> Any:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return default
