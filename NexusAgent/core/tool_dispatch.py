"""Tool dispatch and registry for NexusAgent."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 180  # seconds


@dataclass
class ToolResult:
    """Result of a tool execution."""
    tool_name: str
    success: bool
    output: Any = None
    error: str | None = None
    duration_ms: float = 0.0


@dataclass
class ToolDef:
    """Definition of a tool available to the agent."""
    name: str
    description: str
    parameters_schema: dict[str, Any]
    handler: Callable[..., Coroutine[Any, Any, Any]]
    enabled: bool = True
    timeout: float = DEFAULT_TIMEOUT

    def to_openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }

    def to_anthropic_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters_schema,
        }


class ToolRegistry:
    """Registry for managing and executing tools."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDef] = {}

    def register(self, tool_def: ToolDef) -> None:
        """Register a tool. Overwrites if name already exists."""
        self._tools[tool_def.name] = tool_def
        logger.info("Registered tool: %s", tool_def.name)

    def get(self, name: str) -> ToolDef | None:
        """Get a tool by name, or None if not found."""
        return self._tools.get(name)

    def list_tools(self) -> list[ToolDef]:
        """Return all enabled tools."""
        return [t for t in self._tools.values() if t.enabled]

    def list_all(self) -> list[ToolDef]:
        """Return all registered tools regardless of enabled state."""
        return list(self._tools.values())

    def has(self, name: str) -> bool:
        return name in self._tools and self._tools[name].enabled

    async def execute(self, name: str, args: dict[str, Any]) -> ToolResult:
        """Execute a single tool by name with timeout and error handling."""
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(tool_name=name, success=False, error=f"Tool '{name}' not found")
        if not tool.enabled:
            return ToolResult(tool_name=name, success=False, error=f"Tool '{name}' is disabled")

        start = time.monotonic()
        try:
            result = await asyncio.wait_for(tool.handler(**args), timeout=tool.timeout)
            duration = (time.monotonic() - start) * 1000
            return ToolResult(tool_name=name, success=True, output=result, duration_ms=duration)
        except asyncio.TimeoutError:
            duration = (time.monotonic() - start) * 1000
            return ToolResult(
                tool_name=name, success=False,
                error=f"Tool timed out after {tool.timeout}s", duration_ms=duration,
            )
        except Exception as exc:
            duration = (time.monotonic() - start) * 1000
            logger.exception("Tool '%s' raised an exception", name)
            return ToolResult(
                tool_name=name, success=False,
                error=f"{type(exc).__name__}: {exc}", duration_ms=duration,
            )

    async def execute_parallel(
        self, tools_list: list[dict[str, Any]]
    ) -> list[ToolResult]:
        """Execute multiple tools in parallel.

        Args:
            tools_list: List of dicts with 'name' and 'args' keys.
        """
        if not tools_list:
            return []

        coros = [
            self.execute(item["name"], item.get("args", {}))
            for item in tools_list
        ]
        return await asyncio.gather(*coros)
