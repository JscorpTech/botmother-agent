"""PostgreSQL database layer for sessions and generated flows."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from typing import Any

import psycopg2
import psycopg2.extras
import psycopg2.pool

_DATABASE_URL = os.environ.get("DATABASE_URL", "")

_pool: psycopg2.pool.ThreadedConnectionPool | None = None


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        if not _DATABASE_URL:
            raise RuntimeError("DATABASE_URL environment variable is not set")
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            dsn=_DATABASE_URL,
        )
    return _pool


@contextmanager
def get_db():
    pool = _get_pool()
    conn = pool.getconn()
    conn.autocommit = False
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def _row_to_dict(cursor) -> dict | None:
    row = cursor.fetchone()
    if not row:
        return None
    cols = [desc[0] for desc in cursor.description]
    return dict(zip(cols, row))


def _rows_to_list(cursor) -> list[dict]:
    rows = cursor.fetchall()
    cols = [desc[0] for desc in cursor.description]
    return [dict(zip(cols, row)) for row in rows]


# ── Schema ───────────────────────────────────────────────────────────────

def init_db() -> None:
    """Create tables if they don't exist."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                phase TEXT DEFAULT 'chat',
                turn_count INTEGER DEFAULT 0,
                requirements TEXT DEFAULT '[]',
                flow_json TEXT,
                project_id TEXT,
                messages TEXT DEFAULT '[]',
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS flows (
                id SERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                session_id TEXT REFERENCES sessions(id),
                name TEXT,
                description TEXT,
                flow_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_flows_user ON flows(user_id)")


# ── Sessions ─────────────────────────────────────────────────────────────

def create_session(session_id: str, user_id: str, project_id: str | None = None) -> dict:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO sessions (id, user_id, project_id) VALUES (%s, %s, %s)",
            (session_id, str(user_id), project_id),
        )
        cur.execute("SELECT * FROM sessions WHERE id = %s", (session_id,))
        return _row_to_dict(cur)


def get_session(session_id: str, user_id: str) -> dict | None:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM sessions WHERE id = %s AND user_id = %s",
            (session_id, str(user_id)),
        )
        return _row_to_dict(cur)


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
        parts.append("phase = %s")
        vals.append(phase)
    if turn_count is not None:
        parts.append("turn_count = %s")
        vals.append(turn_count)
    if requirements is not None:
        parts.append("requirements = %s")
        vals.append(json.dumps(requirements, ensure_ascii=False))
    if flow_json is not None:
        parts.append("flow_json = %s")
        vals.append(flow_json)
    if messages_json is not None:
        parts.append("messages = %s")
        vals.append(messages_json)
    if not parts:
        return
    parts.append("updated_at = NOW()")
    vals.append(session_id)
    sql = f"UPDATE sessions SET {', '.join(parts)} WHERE id = %s"
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(sql, vals)


def list_sessions(user_id: str) -> list[dict]:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, phase, turn_count, (flow_json IS NOT NULL) as has_flow, created_at, updated_at "
            "FROM sessions WHERE user_id = %s ORDER BY updated_at DESC",
            (str(user_id),),
        )
        return _rows_to_list(cur)


def delete_session(session_id: str, user_id: str) -> bool:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM sessions WHERE id = %s AND user_id = %s",
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
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO flows (user_id, session_id, name, description, flow_json) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING *",
            (str(user_id), session_id, name, description, flow_json),
        )
        return _row_to_dict(cur)


def list_flows(user_id: str) -> list[dict]:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, description, created_at, updated_at "
            "FROM flows WHERE user_id = %s ORDER BY created_at DESC",
            (str(user_id),),
        )
        return _rows_to_list(cur)


def get_flow(flow_id: int, user_id: str) -> dict | None:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM flows WHERE id = %s AND user_id = %s",
            (flow_id, str(user_id)),
        )
        return _row_to_dict(cur)


def delete_flow(flow_id: int, user_id: str) -> bool:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM flows WHERE id = %s AND user_id = %s",
            (flow_id, str(user_id)),
        )
        return cur.rowcount > 0
