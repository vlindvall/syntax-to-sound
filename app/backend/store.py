from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class Store:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    status TEXT NOT NULL,
                    active_song_path TEXT
                );

                CREATE TABLE IF NOT EXISTS turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    model TEXT NOT NULL,
                    latency_ms INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                );

                CREATE TABLE IF NOT EXISTS patches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    turn_id INTEGER NOT NULL,
                    json_commands TEXT NOT NULL,
                    emitted_code TEXT NOT NULL,
                    validation_status TEXT NOT NULL,
                    apply_status TEXT NOT NULL,
                    revert_commands TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(turn_id) REFERENCES turns(id)
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    source TEXT NOT NULL,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload_json TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    song_path TEXT NOT NULL,
                    notes TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                );
                """
            )

    def ensure_session(self, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions(id, status)
                VALUES (?, 'ready')
                ON CONFLICT(id) DO UPDATE SET updated_at=CURRENT_TIMESTAMP
                """,
                (session_id,),
            )

    def update_session_song(self, session_id: str, song_path: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE sessions
                SET active_song_path=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (song_path, session_id),
            )

    def create_turn(self, session_id: str, prompt: str, model: str, latency_ms: int) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO turns(session_id, prompt, model, latency_ms)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, prompt, model, latency_ms),
            )
            return int(cur.lastrowid)

    def create_patch(
        self,
        turn_id: int,
        json_commands: list[dict[str, Any]],
        emitted_code: str,
        validation_status: str,
        apply_status: str,
        revert_commands: list[dict[str, Any]] | None = None,
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO patches(turn_id, json_commands, emitted_code, validation_status, apply_status, revert_commands)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    turn_id,
                    json.dumps(json_commands),
                    emitted_code,
                    validation_status,
                    apply_status,
                    json.dumps(revert_commands or []),
                ),
            )
            return int(cur.lastrowid)

    def log_event(
        self,
        session_id: str | None,
        source: str,
        level: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO events(session_id, source, level, message, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, source, level, message, json.dumps(payload or {})),
            )

    def record_snapshot(self, session_id: str, song_path: str, notes: str = "") -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO snapshots(session_id, song_path, notes)
                VALUES (?, ?, ?)
                """,
                (session_id, song_path, notes),
            )

    def get_patch(self, patch_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, json_commands, emitted_code, validation_status, apply_status, revert_commands
                FROM patches
                WHERE id=?
                """,
                (patch_id,),
            ).fetchone()
            if row is None:
                return None
            return {
                "id": row["id"],
                "json_commands": json.loads(row["json_commands"]),
                "emitted_code": row["emitted_code"],
                "validation_status": row["validation_status"],
                "apply_status": row["apply_status"],
                "revert_commands": json.loads(row["revert_commands"] or "[]"),
            }

    def get_last_applied_patch(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT p.id, p.json_commands, p.revert_commands
                FROM patches p
                JOIN turns t ON t.id = p.turn_id
                WHERE t.session_id=? AND p.apply_status='applied'
                ORDER BY p.id DESC
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            return {
                "id": row["id"],
                "json_commands": json.loads(row["json_commands"]),
                "revert_commands": json.loads(row["revert_commands"] or "[]"),
            }

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            session = conn.execute(
                "SELECT * FROM sessions WHERE id=?",
                (session_id,),
            ).fetchone()
            if session is None:
                return None

            turns = conn.execute(
                "SELECT * FROM turns WHERE session_id=? ORDER BY id DESC LIMIT 30",
                (session_id,),
            ).fetchall()
            events = conn.execute(
                "SELECT * FROM events WHERE session_id=? ORDER BY id DESC LIMIT 100",
                (session_id,),
            ).fetchall()

        return {
            "session": dict(session),
            "turns": [dict(r) for r in turns],
            "events": [
                {
                    **dict(r),
                    "payload_json": json.loads(r["payload_json"] or "{}"),
                }
                for r in events
            ],
        }
