"""SessionStore: SQLite-backed session management with message history and FTS5 search."""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Session:
    """Represents a conversation session."""

    id: str
    user_id: str
    platform: str
    title: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


@dataclass
class SessionMessage:
    """A single message within a session."""

    id: str
    session_id: str
    role: str  # 'user', 'assistant', 'system', 'tool'
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""


class SessionStore:
    """
    SQLite-backed session store with full message history and FTS5 search.

    Each session tracks messages from a user on a specific platform.
    """

    def __init__(self, db_path: str | Path = "sessions.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                title TEXT DEFAULT '',
                metadata TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);

            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                content,
                content='messages',
                content_rowid='rowid'
            );
        """)
        # FTS sync triggers
        conn.executescript("""
            CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
                INSERT INTO messages_fts(rowid, content) VALUES (new.rowid, new.content);
            END;
            CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
                INSERT INTO messages_fts(messages_fts, rowid, content) VALUES ('delete', old.rowid, old.content);
            END;
        """)
        conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Session CRUD
    # ------------------------------------------------------------------

    def create(self, user_id: str, platform: str, title: str = "") -> Session:
        """Create a new session."""
        now = datetime.now(timezone.utc).isoformat()
        session = Session(
            id=str(uuid.uuid4()),
            user_id=user_id,
            platform=platform,
            title=title,
            created_at=now,
            updated_at=now,
        )
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO sessions (id, user_id, platform, title, metadata, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session.id, session.user_id, session.platform, session.title, json.dumps(session.metadata), session.created_at, session.updated_at),
        )
        conn.commit()
        return session

    def get(self, session_id: str) -> Session | None:
        """Get a session by ID."""
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return self._row_to_session(row) if row else None

    def resume(self, session_id: str) -> list[SessionMessage]:
        """
        Resume a session by returning its full message history.

        Returns:
            Ordered list of SessionMessage objects.
        """
        session = self.get(session_id)
        if not session:
            return []
        return self.get_messages(session_id)

    def list_sessions(self, user_id: str | None = None, limit: int = 50) -> list[Session]:
        """List sessions, optionally filtered by user_id."""
        conn = self._get_conn()
        if user_id:
            rows = conn.execute(
                "SELECT * FROM sessions WHERE user_id = ? ORDER BY updated_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_session(r) for r in rows]

    def delete(self, session_id: str) -> bool:
        """Delete a session and all its messages."""
        conn = self._get_conn()
        cur = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Message management
    # ------------------------------------------------------------------

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> SessionMessage:
        """Add a message to a session."""
        now = datetime.now(timezone.utc).isoformat()
        msg = SessionMessage(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role=role,
            content=content,
            metadata=metadata or {},
            created_at=now,
        )
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO messages (id, session_id, role, content, metadata, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (msg.id, msg.session_id, msg.role, msg.content, json.dumps(msg.metadata), msg.created_at),
        )
        conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
        conn.commit()
        return msg

    def get_messages(self, session_id: str, limit: int = 500) -> list[SessionMessage]:
        """Get all messages for a session, ordered by creation time."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at ASC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        return [self._row_to_message(r) for r in rows]

    def search_messages(self, query: str, limit: int = 20) -> list[SessionMessage]:
        """Full-text search across all session messages."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT m.* FROM messages m "
            "JOIN messages_fts f ON m.rowid = f.rowid "
            "WHERE messages_fts MATCH ? "
            "ORDER BY rank LIMIT ?",
            (query, limit),
        ).fetchall()
        return [self._row_to_message(r) for r in rows]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_session(row: sqlite3.Row) -> Session:
        return Session(
            id=row["id"],  # type: ignore[index]
            user_id=row["user_id"],  # type: ignore[index]
            platform=row["platform"],  # type: ignore[index]
            title=row["title"],  # type: ignore[index]
            metadata=json.loads(row["metadata"]),  # type: ignore[index]
            created_at=row["created_at"],  # type: ignore[index]
            updated_at=row["updated_at"],  # type: ignore[index]
        )

    @staticmethod
    def _row_to_message(row: sqlite3.Row) -> SessionMessage:
        return SessionMessage(
            id=row["id"],  # type: ignore[index]
            session_id=row["session_id"],  # type: ignore[index]
            role=row["role"],  # type: ignore[index]
            content=row["content"],  # type: ignore[index]
            metadata=json.loads(row["metadata"]),  # type: ignore[index]
            created_at=row["created_at"],  # type: ignore[index]
        )
