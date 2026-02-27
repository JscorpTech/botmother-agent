"""SQLite database layer for user data, sessions, and generated flows."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

_DB_PATH = os.environ.get(
    "DATABASE_PATH",
    str(Path(__file__).resolve().parent.parent / "data" / "agent.db"),
)


def _ensure_dir() -> None:
    Path(_DB_PATH).parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def get_db():
    _ensure_dir()
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Schema ───────────────────────────────────────────────────────────────

def init_db() -> None:
    """Create tables if they don't exist."""
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                role TEXT DEFAULT 'user',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                phase TEXT DEFAULT 'chat',
                turn_count INTEGER DEFAULT 0,
                requirements TEXT DEFAULT '[]',
                flow_json TEXT,
                messages TEXT DEFAULT '[]',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

            CREATE TABLE IF NOT EXISTS flows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                session_id TEXT,
                name TEXT,
                description TEXT,
                flow_json TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );

            CREATE INDEX IF NOT EXISTS idx_flows_user ON flows(user_id);
        """)


# ── Users ────────────────────────────────────────────────────────────────

def upsert_user(
    user_id: str,
    email: str | None = None,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    role: str = "user",
) -> dict:
    with get_db() as db:
        db.execute(
            """INSERT INTO users (id, email, username, first_name, last_name, role)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 email = COALESCE(excluded.email, email),
                 username = COALESCE(excluded.username, username),
                 first_name = COALESCE(excluded.first_name, first_name),
                 last_name = COALESCE(excluded.last_name, last_name),
                 role = excluded.role,
                 updated_at = datetime('now')
            """,
            (str(user_id), email, username, first_name, last_name, role),
        )
        row = db.execute("SELECT * FROM users WHERE id = ?", (str(user_id),)).fetchone()
        return dict(row)


def get_user(user_id: str) -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM users WHERE id = ?", (str(user_id),)).fetchone()
        return dict(row) if row else None


# ── Sessions ─────────────────────────────────────────────────────────────

def create_session(session_id: str, user_id: str) -> dict:
    with get_db() as db:
        db.execute(
            "INSERT INTO sessions (id, user_id) VALUES (?, ?)",
            (session_id, str(user_id)),
        )
        row = db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return dict(row)


def get_session(session_id: str, user_id: str) -> dict | None:
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM sessions WHERE id = ? AND user_id = ?",
            (session_id, str(user_id)),
        ).fetchone()
        return dict(row) if row else None


def update_session(
    session_id: str,
    *,
    phase: str | None = None,
    turn_count: int | None = None,
    requirements: list[str] | None = None,
    flow_json: str | None = None,
    messages_json: str | None = None,
) -> None:
    parts = []
    vals: list[Any] = []
    if phase is not None:
        parts.append("phase = ?")
        vals.append(phase)
    if turn_count is not None:
        parts.append("turn_count = ?")
        vals.append(turn_count)
    if requirements is not None:
        parts.append("requirements = ?")
        vals.append(json.dumps(requirements, ensure_ascii=False))
    if flow_json is not None:
        parts.append("flow_json = ?")
        vals.append(flow_json)
    if messages_json is not None:
        parts.append("messages = ?")
        vals.append(messages_json)
    if not parts:
        return
    parts.append("updated_at = datetime('now')")
    vals.append(session_id)
    sql = f"UPDATE sessions SET {', '.join(parts)} WHERE id = ?"
    with get_db() as db:
        db.execute(sql, vals)


def list_sessions(user_id: str) -> list[dict]:
    with get_db() as db:
        rows = db.execute(
            "SELECT id, phase, turn_count, flow_json IS NOT NULL as has_flow, created_at, updated_at "
            "FROM sessions WHERE user_id = ? ORDER BY updated_at DESC",
            (str(user_id),),
        ).fetchall()
        return [dict(r) for r in rows]


def delete_session(session_id: str, user_id: str) -> bool:
    with get_db() as db:
        cur = db.execute(
            "DELETE FROM sessions WHERE id = ? AND user_id = ?",
            (session_id, str(user_id)),
        )
        return cur.rowcount > 0


# ── Flows ────────────────────────────────────────────────────────────────

def save_flow_record(
    user_id: str,
    flow_json: str,
    name: str | None = None,
    description: str | None = None,
    session_id: str | None = None,
) -> dict:
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO flows (user_id, session_id, name, description, flow_json) VALUES (?, ?, ?, ?, ?)",
            (str(user_id), session_id, name, description, flow_json),
        )
        row = db.execute("SELECT * FROM flows WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)


def list_flows(user_id: str) -> list[dict]:
    with get_db() as db:
        rows = db.execute(
            "SELECT id, name, description, created_at, updated_at "
            "FROM flows WHERE user_id = ? ORDER BY created_at DESC",
            (str(user_id),),
        ).fetchall()
        return [dict(r) for r in rows]


def get_flow(flow_id: int, user_id: str) -> dict | None:
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM flows WHERE id = ? AND user_id = ?",
            (flow_id, str(user_id)),
        ).fetchone()
        return dict(row) if row else None


def delete_flow(flow_id: int, user_id: str) -> bool:
    with get_db() as db:
        cur = db.execute(
            "DELETE FROM flows WHERE id = ? AND user_id = ?",
            (flow_id, str(user_id)),
        )
        return cur.rowcount > 0
