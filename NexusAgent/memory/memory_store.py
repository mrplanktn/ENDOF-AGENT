"""MemoryStore: persistent memory with SQLite + FTS5 full-text search."""

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
class MemoryEntry:
    """A single memory entry."""

    id: str
    category: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    user_id: str = ""
    created_at: str = ""
    updated_at: str = ""


class MemoryStore:
    """
    SQLite-backed memory store with FTS5 full-text search.

    Supports saving arbitrary content by category, searching with FTS5,
    and managing per-user profiles.
    """

    def __init__(self, db_path: str | Path = "memory.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        """Get or create the SQLite connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def _init_db(self) -> None:
        """Create tables and FTS5 virtual table if they don't exist."""
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT DEFAULT '{}',
                user_id TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category);
            CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id);

            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                content, category, metadata,
                content='memories',
                content_rowid='rowid'
            );

            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id TEXT PRIMARY KEY,
                profile TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        # Triggers for FTS sync
        for event, timing in [("INSERT", "AFTER"), ("DELETE", "AFTER")]:
            conn.executescript(f"""
                CREATE TRIGGER IF NOT EXISTS memories_ai {timing} INSERT ON memories BEGIN
                    INSERT INTO memories_fts(rowid, content, category, metadata)
                    VALUES (new.rowid, new.content, new.category, new.metadata);
                END;
                CREATE TRIGGER IF NOT EXISTS memories_ad {timing} DELETE ON memories BEGIN
                    INSERT INTO memories_fts(memories_fts, rowid, content, category, metadata)
                    VALUES ('delete', old.rowid, old.content, old.category, old.metadata);
                END;
            """)
        conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def save(
        self,
        category: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        user_id: str = "",
    ) -> MemoryEntry:
        """
        Save a new memory entry.

        Args:
            category: Category label (e.g. 'conversation', 'fact', 'task').
            content: The text content to store.
            metadata: Optional JSON-serialisable metadata dict.
            user_id: Optional user identifier.

        Returns:
            The created MemoryEntry.
        """
        now = datetime.now(timezone.utc).isoformat()
        entry = MemoryEntry(
            id=str(uuid.uuid4()),
            category=category,
            content=content,
            metadata=metadata or {},
            user_id=user_id,
            created_at=now,
            updated_at=now,
        )
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO memories (id, category, content, metadata, user_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (entry.id, entry.category, entry.content, json.dumps(entry.metadata), entry.user_id, entry.created_at, entry.updated_at),
        )
        conn.commit()
        return entry

    def search(self, query: str, limit: int = 20, category: str | None = None) -> list[MemoryEntry]:
        """
        Full-text search across memories.

        Args:
            query: FTS5 search query.
            limit: Maximum results to return.
            category: Optional category filter.

        Returns:
            List of matching MemoryEntry objects.
        """
        conn = self._get_conn()
        if category:
            rows = conn.execute(
                "SELECT m.* FROM memories m "
                "JOIN memories_fts f ON m.rowid = f.rowid "
                "WHERE memories_fts MATCH ? AND m.category = ? "
                "ORDER BY rank LIMIT ?",
                (query, category, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT m.* FROM memories m "
                "JOIN memories_fts f ON m.rowid = f.rowid "
                "WHERE memories_fts MATCH ? "
                "ORDER BY rank LIMIT ?",
                (query, limit),
            ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def list_recent(self, limit: int = 50, category: str | None = None) -> list[MemoryEntry]:
        """List the most recent memories."""
        conn = self._get_conn()
        if category:
            rows = conn.execute(
                "SELECT * FROM memories WHERE category = ? ORDER BY created_at DESC LIMIT ?",
                (category, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM memories ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def delete(self, memory_id: str) -> bool:
        """Delete a memory entry by ID. Returns True if deleted."""
        conn = self._get_conn()
        cur = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        conn.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------------
    # User profiles
    # ------------------------------------------------------------------

    def get_user_profile(self, user_id: str) -> dict[str, Any]:
        """
        Get the stored profile for a user.

        Returns an empty dict if no profile exists.
        """
        conn = self._get_conn()
        row = conn.execute("SELECT profile FROM user_profiles WHERE user_id = ?", (user_id,)).fetchone()
        if row:
            return json.loads(row["profile"])  # type: ignore[index]
        return {}

    def update_user_profile(self, user_id: str, profile: dict[str, Any]) -> None:
        """
        Create or update a user profile.

        Merges the provided keys into any existing profile.
        """
        now = datetime.now(timezone.utc).isoformat()
        existing = self.get_user_profile(user_id)
        existing.update(profile)
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO user_profiles (user_id, profile, created_at, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET profile = excluded.profile, updated_at = excluded.updated_at",
            (user_id, json.dumps(existing), now, now),
        )
        conn.commit()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> MemoryEntry:
        """Convert a database row to a MemoryEntry."""
        return MemoryEntry(
            id=row["id"],  # type: ignore[index]
            category=row["category"],  # type: ignore[index]
            content=row["content"],  # type: ignore[index]
            metadata=json.loads(row["metadata"]),  # type: ignore[index]
            user_id=row["user_id"],  # type: ignore[index]
            created_at=row["created_at"],  # type: ignore[index]
            updated_at=row["updated_at"],  # type: ignore[index]
        )
