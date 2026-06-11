"""File tool — read, write, patch, and search files.

Provides safe file operations with line-number display, fuzzy diff
patching (via ``difflib``), and content/filename search powered by
``ripgrep`` (fallback to pure-Python grep).
"""

from __future__ import annotations

import asyncio
import difflib
import fnmatch
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Optional

from .registry import ToolRegistry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _safe_path(path: str) -> Path:
    """Expand ``~`` and resolve to absolute path."""
    return Path(os.path.expanduser(path)).resolve()


def _read_with_numbers(path: Path, offset: int = 1, limit: int = 500) -> str:
    """Return file contents prefixed with line numbers (1-indexed)."""
    with open(path, "r", errors="replace") as fh:
        lines = fh.readlines()
    # Slice: offset is 1-indexed
    start = max(offset - 1, 0)
    end = start + limit
    selected = lines[start:end]
    numbered = [f"{i + start + 1:6d}| {line.rstrip()}" for i, line in enumerate(selected)]
    total = len(lines)
    header = f"--- {path} (lines {start+1}–{min(end, total)} of {total}) ---"
    return header + "\n" + "\n".join(numbered)


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------
def read_file(path: str, offset: int = 1, limit: int = 500) -> dict[str, Any]:
    """Read a file and return content with line numbers."""
    fp = _safe_path(path)
    if not fp.exists():
        # Suggest similar filenames
        parent = fp.parent
        if parent.exists():
            candidates = [f.name for f in parent.iterdir()]
            close = difflib.get_close_matches(fp.name, candidates, n=5)
            return {"error": f"File not found: {path}", "suggestions": close}
        return {"error": f"File not found: {path}"}
    if fp.is_dir():
        return {"error": f"Path is a directory: {path}"}
    try:
        content = _read_with_numbers(fp, offset, limit)
        return {"content": content, "path": str(fp)}
    except Exception as exc:
        return {"error": str(exc)}


def write_file(path: str, content: str) -> dict[str, Any]:
    """Write *content* to *path*, creating parent dirs as needed."""
    fp = _safe_path(path)
    try:
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return {"success": True, "path": str(fp), "bytes": len(content)}
    except Exception as exc:
        return {"error": str(exc)}


def patch_file(path: str, old_string: str, new_string: str) -> dict[str, Any]:
    """Replace *old_string* with *new_string* in file using fuzzy matching.

    Returns a unified diff showing the change.  Raises an error if no
    sufficiently close match is found.
    """
    fp = _safe_path(path)
    if not fp.exists():
        return {"error": f"File not found: {path}"}

    text = fp.read_text(errors="replace")

    if old_string not in text:
        # Fuzzy match: find the best substring match
        matcher = difflib.SequenceMatcher(None, old_string, text)
        best_ratio = 0.0
        best_pos = -1
        chunk_len = len(old_string)
        # Slide window over text
        step = max(1, chunk_len // 4)
        for i in range(0, len(text) - chunk_len + 1, step):
            candidate = text[i : i + chunk_len]
            ratio = difflib.SequenceMatcher(None, old_string, candidate).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_pos = i

        if best_ratio < 0.6 or best_pos < 0:
            return {
                "error": "old_string not found in file (best fuzzy match < 60%)",
                "best_ratio": round(best_ratio, 3),
            }

        # Use the best-matching window as replacement target
        old_string = text[best_pos : best_pos + chunk_len]

    new_text = text.replace(old_string, new_string, 1)

    diff = difflib.unified_diff(
        text.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile=f"a/{fp.name}",
        tofile=f"b/{fp.name}",
    )
    diff_str = "".join(diff)

    fp.write_text(new_text)
    return {"success": True, "diff": diff_str, "path": str(fp)}


def search_files(
    pattern: str,
    path: str = ".",
    target: str = "content",
    limit: int = 50,
) -> dict[str, Any]:
    """Search files matching *pattern*.

    *target* = ``"content"`` → grep inside files (uses ``rg`` if available).
    *target* = ``"files"``   → find files by glob pattern.
    """
    root = _safe_path(path)

    if target == "files":
        matches: list[str] = []
        for dirpath, dirnames, filenames in os.walk(root):
            # Skip hidden dirs
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for fname in filenames:
                if fnmatch.fnmatch(fname, pattern):
                    full = os.path.join(dirpath, fname)
                    matches.append(full)
                    if len(matches) >= limit:
                        return {"matches": matches, "truncated": True}
        return {"matches": matches, "truncated": False}

    # Content search
    # Try ripgrep first
    try:
        result = subprocess.run(
            ["rg", "--no-heading", "-n", "--max-count", str(limit), pattern, str(root)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        lines = [l for l in result.stdout.strip().splitlines() if l]
        return {"matches": lines[:limit], "engine": "ripgrep", "truncated": len(lines) >= limit}
    except FileNotFoundError:
        pass  # rg not installed — fall through to Python fallback
    except subprocess.TimeoutExpired:
        return {"error": "Search timed out"}

    # Pure-Python fallback
    regex = re.compile(pattern)
    results: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fname in filenames:
            fpath = os.path.join(dirpath, fname)
            try:
                with open(fpath, "r", errors="ignore") as fh:
                    for lineno, line in enumerate(fh, 1):
                        if regex.search(line):
                            results.append(f"{fpath}:{lineno}: {line.rstrip()}")
                            if len(results) >= limit:
                                return {"matches": results, "engine": "python", "truncated": True}
            except (PermissionError, OSError):
                continue
    return {"matches": results, "engine": "python", "truncated": False}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
def _register(registry: ToolRegistry) -> None:
    @registry.register(
        name="read_file",
        description="Read a file with line numbers. Use offset/limit for large files.",
        parameters={
            "path": {"type": "string", "description": "File path to read"},
            "offset": {"type": "integer", "description": "Starting line number (1-indexed, default 1)"},
            "limit": {"type": "integer", "description": "Max lines to read (default 500)"},
        },
        required=["path"],
        category="file",
    )
    async def _read(path: str, offset: int = 1, limit: int = 500) -> dict:
        return read_file(path, offset=offset, limit=limit)

    @registry.register(
        name="write_file",
        description="Write content to a file. Creates parent directories automatically.",
        parameters={
            "path": {"type": "string", "description": "File path to write"},
            "content": {"type": "string", "description": "Content to write"},
        },
        required=["path", "content"],
        category="file",
    )
    async def _write(path: str, content: str) -> dict:
        return write_file(path, content)

    @registry.register(
        name="patch_file",
        description="Replace old_string with new_string in a file using fuzzy matching. Returns unified diff.",
        parameters={
            "path": {"type": "string", "description": "File path"},
            "old_string": {"type": "string", "description": "String to find (fuzzy)"},
            "new_string": {"type": "string", "description": "Replacement string"},
        },
        required=["path", "old_string", "new_string"],
        category="file",
    )
    async def _patch(path: str, old_string: str, new_string: str) -> dict:
        return patch_file(path, old_string, new_string)

    @registry.register(
        name="search_files",
        description="Search files by content (regex grep) or by name (glob). Uses ripgrep if available.",
        parameters={
            "pattern": {"type": "string", "description": "Regex pattern (content) or glob (files)"},
            "path": {"type": "string", "description": "Root directory to search"},
            "target": {"type": "string", "enum": ["content", "files"], "description": "Search mode"},
            "limit": {"type": "integer", "description": "Max results to return"},
        },
        required=["pattern"],
        category="file",
    )
    async def _search(pattern: str, path: str = ".", target: str = "content", limit: int = 50) -> dict:
        return search_files(pattern, path=path, target=target, limit=limit)


try:
    _register(ToolRegistry())
except Exception:
    pass
