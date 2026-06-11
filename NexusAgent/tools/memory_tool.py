"""Memory tool — persistent agent memory backed by SQLite + FTS5.

Provides ``save_memory`` and ``search_memory`` operations.  Memories are
stored in a SQLite database with FTS5 full-text search enabled for fast
retrieval.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, Optional

from .registry import ToolRegistry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Database singleton
# ---------------------------------------------------------------------------
_DEFAULT_DB_PATH = os.environ.get(
    "NEXUS_MEMORY_DB",
    os.path.expanduser("~/.nexus/memory.db"),
)

_db: Optional[sqlite3.Connection] = None


def _get_db(db_path: str | None = None) -> sqlite3.Connection:
    """Return (or create) the module-level SQLite connection."""
    global _db
    if _db is not None:
        return _db

    path = Path(db_path or _DEFAULT_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # Main table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            content     TEXT NOT NULL,
            category    TEXT NOT NULL DEFAULT 'general',
            metadata    TEXT DEFAULT '{}',
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    # FTS5 virtual table for full-text search
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
            content,
            category,
            content='memories',
            content_rowid='id'
        )
    """)

    # Triggers to keep FTS in sync
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
            INSERT INTO memories_fts(rowid, content, category)
            VALUES (new.id, new.content, new.category);
        END
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
            INSERT INTO memories_fts(memories_fts, rowid, content, category)
            VALUES ('delete', old.id, old.content, old.category);
        END
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
            INSERT INTO memories_fts(memories_fts, rowid, content, category)
            VALUES ('delete', old.id, old.content, old.category);
            INSERT INTO memories_fts(rowid, content, category)
            VALUES (new.id, new.content, new.category);
        END
    """)

    conn.commit()
    _db = conn
    logger.info("Memory database initialized at %s", path)
    return conn


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def save_memory(
    content: str,
    category: str = "general",
    metadata: dict[str, Any] | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Store a memory entry in the database.

    Parameters
    ----------
    content : str
        The memory content to store.
    category : str
        Category label (e.g. "code", "conversation", "fact").
    metadata : dict, optional
        Arbitrary JSON metadata.
    db_path : str, optional
        Custom database path.

    Returns
    -------
    dict
        ``{"id": int, "category": str, "created_at": str}``
    """
    db = _get_db(db_path)
    meta_json = json.dumps(metadata or {})

    cursor = db.execute(
        "INSERT INTO memories (content, category, metadata) VALUES (?, ?, ?)",
        (content, category, meta_json),
    )
    db.commit()

    row = db.execute(
        "SELECT id, created_at FROM memories WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()

    logger.info("Saved memory #%s [%s]", row["id"], category)
    return {
        "id": row["id"],
        "category": category,
        "created_at": row["created_at"],
    }


def search_memory(
    query: str,
    limit: int = 10,
    category: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Full-text search over stored memories.

    Parameters
    ----------
    query : str
        FTS5 search query (supports AND, OR, NOT, phrase matching).
    limit : int
        Max results to return.
    category : str, optional
        Filter by category.
    db_path : str, optional
        Custom database path.

    Returns
    -------
    dict
        ``{"results": [...], "total": int}``
    """
    db = _get_db(db_path)

    # Sanitize query for FTS5: wrap bare terms in quotes to avoid syntax errors
    safe_query = query.replace('"', '""')

    if category:
        rows = db.execute(
            """
            SELECT m.id, m.content, m.category, m.metadata, m.created_at,
                   rank
            FROM memories_fts fts
            JOIN memories m ON m.id = fts.rowid
            WHERE memories_fts MATCH ? AND m.category = ?
            ORDER BY rank
            LIMIT ?
            """,
            (safe_query, category, limit),
        ).fetchall()
    else:
        rows = db.execute(
            """
            SELECT m.id, m.content, m.category, m.metadata, m.created_at,
                   rank
            FROM memories_fts fts
            JOIN memories m ON m.id = fts.rowid
            WHERE memories_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (safe_query, limit),
        ).fetchall()

    results = []
    for r in rows:
        meta = {}
        try:
            meta = json.loads(r["metadata"]) if r["metadata"] else {}
        except json.JSONDecodeError:
            pass
        results.append({
            "id": r["id"],
            "content": r["content"],
            "category": r["category"],
            "metadata": meta,
            "created_at": r["created_at"],
        })

    return {"results": results, "total": len(results)}


def list_memories(
    category: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db_path: str | None = None,
) -> dict[str, Any]:
    """List recent memories (non-FTS browse)."""
    db = _get_db(db_path)
    if category:
        rows = db.execute(
            "SELECT * FROM memories WHERE category = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (category, limit, offset),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM memories ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()

    results = []
    for r in rows:
        results.append({
            "id": r["id"],
            "content": r["content"][:500],
            "category": r["category"],
            "created_at": r["created_at"],
        })

    return {"results": results, "total": len(results)}


def delete_memory(memory_id: int, db_path: str | None = None) -> dict[str, Any]:
    """Delete a memory by ID."""
    db = _get_db(db_path)
    db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
    db.commit()
    return {"deleted": memory_id}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
def _register(registry: ToolRegistry) -> None:
    @registry.register(
        name="save_memory",
        description="Save a memory entry to persistent storage (SQLite + FTS5).",
        parameters={
            "content": {"type": "string", "description": "Memory content to store"},
            "category": {"type": "string", "description": "Category label (default: general)"},
            "metadata": {"type": "object", "description": "Optional JSON metadata"},
        },
        required=["content"],
        category="memory",
    )
    async def _save(content: str, category: str = "general", metadata: dict | None = None) -> dict:
        return save_memory(content, category=category, metadata=metadata)

    @registry.register(
        name="search_memory",
        description="Full-text search over stored memories using FTS5.",
        parameters={
            "query": {"type": "string", "description": "FTS5 search query"},
            "limit": {"type": "integer", "description": "Max results (default 10)"},
            "category": {"type": "string", "description": "Filter by category"},
        },
        required=["query"],
        category="memory",
    )
    async def _search(query: str, limit: int = 10, category: str | None = None) -> dict:
        return search_memory(query, limit=limit, category=category)

    @registry.register(
        name="list_memories",
        description="List recent memories, optionally filtered by category.",
        parameters={
            "category": {"type": "string", "description": "Filter by category"},
            "limit": {"type": "integer", "description": "Max results (default 50)"},
        },
        required=[],
        category="memory",
    )
    async def _list(category: str | None = None, limit: int = 50) -> dict:
        return list_memories(category=category, limit=limit)

    @registry.register(
        name="delete_memory",
        description="Delete a memory by its ID.",
        parameters={
            "memory_id": {"type": "integer", "description": "ID of the memory to delete"},
        },
        required=["memory_id"],
        category="memory",
    )
    async def _delete(memory_id: int) -> dict:
        return delete_memory(memory_id)


try:
    _register(ToolRegistry())
except Exception:
    pass
