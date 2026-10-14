"""Durable runtime status and cooldown-deduplicated SQLite event history."""

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path


class EventStore:
    def __init__(self, database_path):
        self.path = str(database_path)
        if self.path != ":memory:":
            Path(self.path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self):
        with self._lock, self._connect() as connection:
            if self.path != ":memory:":
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute("PRAGMA synchronous = FULL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS events ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL NOT NULL, "
                "kind TEXT NOT NULL, status TEXT NOT NULL, details_json TEXT NOT NULL, "
                "evidence_path TEXT)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_time ON events(timestamp DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_kind_time ON events(kind, timestamp DESC)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS runtime_status ("
                "id INTEGER PRIMARY KEY CHECK(id = 1), updated_at REAL NOT NULL, "
                "status_json TEXT NOT NULL)"
            )

    def set_status(self, status, **details):
        now = time.time()
        payload = dict(details)
        payload["status"] = status
        payload["updated_at"] = now
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO runtime_status(id, updated_at, status_json) VALUES(1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at, "
                "status_json=excluded.status_json",
                (now, json.dumps(payload, ensure_ascii=False, allow_nan=False)),
            )
        return payload

    def get_status(self):
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT status_json FROM runtime_status WHERE id=1"
            ).fetchone()
        return json.loads(row["status_json"]) if row else None

    def record_event(self, kind, details, evidence_path=None, cooldown_seconds=0,
                     timestamp=None):
        """Persist a discrete event; return None when its cooldown suppresses a repeat."""
        timestamp = time.time() if timestamp is None else float(timestamp)
        cooldown_seconds = max(0.0, float(cooldown_seconds))
        details_json = json.dumps(details, ensure_ascii=False, allow_nan=False, sort_keys=True)
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT timestamp FROM events WHERE kind=? ORDER BY timestamp DESC LIMIT 1",
                (str(kind),),
            ).fetchone()
            if row and timestamp - row["timestamp"] < cooldown_seconds:
                return None
            cursor = connection.execute(
                "INSERT INTO events(timestamp, kind, status, details_json, evidence_path) "
                "VALUES(?, ?, ?, ?, ?)",
                (timestamp, str(kind), "OPEN", details_json,
                 os.fspath(evidence_path) if evidence_path is not None else None),
            )
            return cursor.lastrowid

    def set_event_evidence(self, event_id, evidence_path):
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "UPDATE events SET evidence_path=? WHERE id=?",
                (os.fspath(evidence_path), int(event_id)),
            )
            return cursor.rowcount == 1

    def list_events(self, limit=100, before_id=None):
        limit = max(1, min(int(limit), 1000))
        query = "SELECT id, timestamp, kind, status, details_json, evidence_path FROM events"
        params = []
        if before_id is not None:
            query += " WHERE id < ?"
            params.append(int(before_id))
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._lock, self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [
            {"id": row["id"], "timestamp": row["timestamp"], "kind": row["kind"],
             "status": row["status"], "details": json.loads(row["details_json"]),
             "evidence_path": row["evidence_path"]}
            for row in rows
        ]

