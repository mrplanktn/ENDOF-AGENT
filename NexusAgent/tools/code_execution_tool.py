"""Code execution tool — sandboxed code execution in a subprocess.

Supports Python, JavaScript (Node.js), and Bash.  Runs code in an
isolated subprocess with configurable timeout and optional resource
limits.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import textwrap
from pathlib import Path
from typing import Any, Optional

from .registry import ToolRegistry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Language configurations
# ---------------------------------------------------------------------------
_LANGUAGES: dict[str, dict[str, Any]] = {
    "python": {
        "extension": ".py",
        "command": ["python3", "-u"],   # -u for unbuffered output
        "shebang": "#!/usr/bin/env python3\n",
    },
    "python3": {
        "extension": ".py",
        "command": ["python3", "-u"],
        "shebang": "#!/usr/bin/env python3\n",
    },
    "javascript": {
        "extension": ".js",
        "command": ["node"],
        "shebang": "#!/usr/bin/env node\n",
    },
    "node": {
        "extension": ".js",
        "command": ["node"],
        "shebang": "#!/usr/bin/env node\n",
    },
    "bash": {
        "extension": ".sh",
        "command": ["bash"],
        "shebang": "#!/usr/bin/env bash\nset -euo pipefail\n",
    },
    "shell": {
        "extension": ".sh",
        "command": ["bash"],
        "shebang": "#!/usr/bin/env bash\nset -euo pipefail\n",
    },
}


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------
async def execute_code(
    code: str,
    language: str = "python",
    timeout: int = 30,
    stdin_data: str | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Execute *code* in a sandboxed subprocess.

    Parameters
    ----------
    code : str
        The source code to execute.
    language : str
        Language identifier (python, javascript, bash, …).
    timeout : int
        Max seconds before the process is killed.
    stdin_data : str, optional
        Data to write to the process's stdin.
    env : dict, optional
        Extra environment variables.

    Returns
    -------
    dict
        ``{output, exit_code, language, timed_out}``
    """
    lang_key = language.lower().strip()
    lang_cfg = _LANGUAGES.get(lang_key)
    if lang_cfg is None:
        supported = ", ".join(sorted(_LANGUAGES.keys()))
        return {"error": f"Unsupported language: '{language}'. Supported: {supported}"}

    # Write code to a temporary file
    suffix = lang_cfg["extension"]
    tmpdir = tempfile.mkdtemp(prefix="nexus_exec_")
    code_path = Path(tmpdir) / f"code{suffix}"

    code_path.write_text(lang_cfg["shebang"] + code)
    code_path.chmod(0o755)

    # Build command
    cmd = lang_cfg["command"] + [str(code_path)]

    # Environment: start with a clean base + user additions
    exec_env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": tmpdir,              # sandboxed home
        "LANG": "en_US.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "TMPDIR": tmpdir,
    }
    if env:
        exec_env.update(env)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE if stdin_data else asyncio.subprocess.DEVNULL,
            env=exec_env,
            cwd=tmpdir,
            # Resource limits via preexec_fn (Linux only)
            preexec_fn=_make_preexec(),
        )

        try:
            stdin_bytes = stdin_data.encode() if stdin_data else None
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=stdin_bytes),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {
                "output": f"TIMEOUT after {timeout}s",
                "exit_code": -1,
                "language": language,
                "timed_out": True,
            }

        out = stdout.decode(errors="replace") if stdout else ""
        err = stderr.decode(errors="replace") if stderr else ""
        combined = out
        if err:
            combined += ("\n--- STDERR ---\n" + err) if out else err

        return {
            "output": combined,
            "exit_code": proc.returncode,
            "language": language,
            "timed_out": False,
        }
    except Exception as exc:
        logger.exception("Code execution failed")
        return {"output": str(exc), "exit_code": -1, "language": language, "timed_out": False}
    finally:
        # Cleanup temp files
        try:
            code_path.unlink(missing_ok=True)
            Path(tmpdir).rmdir()
        except OSError:
            pass


def _make_preexec():
    """Create a preexec_fn with resource limits (Linux only)."""
    try:
        import resource

        def _limits():
            # Limit CPU time: 60 seconds
            resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
            # Limit memory: 512 MB
            mem_limit = 512 * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (mem_limit, mem_limit))
            # Limit file size: 50 MB
            resource.setrlimit(resource.RLIMIT_FSIZE, (50 * 1024 * 1024, 50 * 1024 * 1024))
            # No core dumps
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

        return _limits
    except (ImportError, OSError):
        return None  # Not on Linux or resource module unavailable


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
def _register(registry: ToolRegistry) -> None:
    @registry.register(
        name="execute_code",
        description="Execute code in a sandboxed subprocess. Supports python, javascript/node, bash/shell.",
        parameters={
            "code": {
                "type": "string",
                "description": "Source code to execute",
            },
            "language": {
                "type": "string",
                "description": "Language: python, javascript, bash (default: python)",
            },
            "timeout": {
                "type": "integer",
                "description": "Max seconds before kill (default: 30)",
            },
            "stdin_data": {
                "type": "string",
                "description": "Optional data to pipe to stdin",
            },
        },
        required=["code"],
        category="code_execution",
    )
    async def _execute(
        code: str,
        language: str = "python",
        timeout: int = 30,
        stdin_data: str | None = None,
    ) -> dict:
        return await execute_code(code, language=language, timeout=timeout, stdin_data=stdin_data)


try:
    _register(ToolRegistry())
except Exception:
    pass
