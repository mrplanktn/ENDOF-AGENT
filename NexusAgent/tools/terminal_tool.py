"""Terminal tool — execute shell commands with background-process management.

Uses ``asyncio.create_subprocess_shell`` so callers can always ``await``
the result without blocking the event loop.  Background sessions are
tracked in-process and can be listed / polled / killed / logged.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from .registry import ToolRegistry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configurable security blocklist
# ---------------------------------------------------------------------------
DEFAULT_BLOCKLIST = [
    r"\brm\s+-rf\s+/\s*$",          # rm -rf /
    r"\bmkfs\b",                     # format disk
    r"\bdd\b.*\bof=/dev/",          # dd to raw device
    r"\bshutdown\b",
    r"\breboot\b",
    r"\b:(){ :\|:& };:",           # fork bomb
]

_blocklist: list[re.Pattern[str]] = [re.compile(p) for p in DEFAULT_BLOCKLIST]


def set_blocklist(patterns: list[str]) -> None:
    """Replace the command blocklist (list of regex strings)."""
    global _blocklist
    _blocklist = [re.compile(p) for p in patterns]


def _is_blocked(cmd: str) -> bool:
    return any(p.search(cmd) for p in _blocklist)


# ---------------------------------------------------------------------------
# Background session tracker
# ---------------------------------------------------------------------------
@dataclass
class _BackgroundSession:
    session_id: str
    cmd: str
    process: asyncio.subprocess.Process
    start_time: float = field(default_factory=time.time)
    output: str = ""
    finished: bool = False
    exit_code: Optional[int] = None


_sessions: dict[str, _BackgroundSession] = {}


# ---------------------------------------------------------------------------
# Core async helpers
# ---------------------------------------------------------------------------
async def execute_command(
    cmd: str,
    timeout: int = 180,
    cwd: str | None = None,
    background: bool = False,
) -> dict[str, Any]:
    """Run *cmd* in a shell and return ``{output, exit_code}``.

    If *background* is ``True`` the process is spawned and tracked; the
    returned dict includes a ``session_id`` for later polling.
    """
    if _is_blocked(cmd):
        return {"output": "BLOCKED: command matched security blocklist", "exit_code": -1}

    if background:
        return await _start_background(cmd, cwd)

    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=cwd,
    )

    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        output = stdout.decode(errors="replace") if stdout else ""
        return {"output": output, "exit_code": proc.returncode}
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return {"output": f"TIMEOUT after {timeout}s", "exit_code": -1}


async def _start_background(cmd: str, cwd: str | None) -> dict[str, Any]:
    session_id = secrets.token_hex(6)
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=cwd,
    )
    session = _BackgroundSession(session_id=session_id, cmd=cmd, process=proc)
    _sessions[session_id] = session
    logger.info("Background session %s started: %s", session_id, cmd)

    # Fire-and-forget reader so output doesn't fill the pipe buffer
    asyncio.create_task(_drain(session))

    return {
        "output": f"Background session started: {session_id}",
        "exit_code": None,
        "session_id": session_id,
    }


async def _drain(session: _BackgroundSession) -> None:
    """Continuously read stdout until process exits."""
    assert session.process.stdout is not None
    chunks: list[bytes] = []
    async for chunk in session.process.stdout:
        chunks.append(chunk)
    await session.process.wait()
    session.output = b"".join(chunks).decode(errors="replace")
    session.finished = True
    session.exit_code = session.process.returncode
    logger.info("Background session %s finished (code=%s)", session.session_id, session.exit_code)


# ---------------------------------------------------------------------------
# Background management
# ---------------------------------------------------------------------------
async def manage_background(action: str, session_id: str = "") -> dict[str, Any]:
    """Manage background sessions.

    *action* must be one of: ``list``, ``poll``, ``kill``, ``log``.
    """
    if action == "list":
        return {
            "sessions": [
                {
                    "session_id": s.session_id,
                    "cmd": s.cmd,
                    "running": not s.finished,
                    "elapsed": round(time.time() - s.start_time, 1),
                }
                for s in _sessions.values()
            ]
        }

    if not session_id:
        return {"error": "session_id required for action '{}'".format(action)}

    session = _sessions.get(session_id)
    if session is None:
        return {"error": f"No such session: {session_id}"}

    if action == "poll":
        return {
            "session_id": session_id,
            "finished": session.finished,
            "exit_code": session.exit_code,
            "output_tail": session.output[-2000:] if session.output else "",
        }

    if action == "kill":
        if not session.finished:
            session.process.kill()
            await session.process.wait()
            session.finished = True
            session.exit_code = session.process.returncode
        return {"session_id": session_id, "killed": True, "exit_code": session.exit_code}

    if action == "log":
        return {
            "session_id": session_id,
            "output": session.output,
            "finished": session.finished,
        }

    return {"error": f"Unknown action: {action}"}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
def _register(registry: ToolRegistry) -> None:
    @registry.register(
        name="execute_command",
        description="Execute a shell command and return its output. Set background=true for long-running commands.",
        parameters={
            "cmd": {"type": "string", "description": "Shell command to execute"},
            "timeout": {"type": "integer", "description": "Max seconds to wait (default 180)"},
            "cwd": {"type": "string", "description": "Working directory"},
            "background": {"type": "boolean", "description": "Run in background"},
        },
        required=["cmd"],
        category="terminal",
    )
    async def _execute_command(cmd: str, timeout: int = 180, cwd: str | None = None, background: bool = False) -> dict:
        return await execute_command(cmd, timeout=timeout, cwd=cwd, background=background)

    @registry.register(
        name="manage_background",
        description="Manage background sessions: list, poll, kill, or view log.",
        parameters={
            "action": {"type": "string", "enum": ["list", "poll", "kill", "log"], "description": "Action to perform"},
            "session_id": {"type": "string", "description": "Session ID (required for poll/kill/log)"},
        },
        required=["action"],
        category="terminal",
    )
    async def _manage_background(action: str, session_id: str = "") -> dict:
        return await manage_background(action, session_id)


# Auto-register on import when a registry is available
try:
    _register(ToolRegistry())
except Exception:
    pass
