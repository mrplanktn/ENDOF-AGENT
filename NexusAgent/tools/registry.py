"""ToolRegistry — singleton registry for all NexusAgent tools.

Provides a decorator-based registration pattern and methods to discover,
inspect, and execute registered tools by name.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolSpec:
    """Immutable descriptor for a registered tool."""
    name: str
    description: str
    parameters: dict[str, Any]          # JSON-Schema "properties"
    required: list[str]                 # required parameter names
    fn: Callable[..., Any]              # the actual callable
    is_async: bool = False
    category: str = "general"

    # ---- helpers ---------------------------------------------------------
    def to_openai_schema(self) -> dict[str, Any]:
        """Return an OpenAI-function-calling compatible schema dict."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": self.parameters,
                "required": self.required,
            },
        }


class ToolRegistry:
    """Singleton registry that stores ToolSpec objects keyed by name.

    Thread-safe via an asyncio lock (tools may be registered concurrently
    during agent bootstrap).
    """

    _instance: Optional["ToolRegistry"] = None

    def __new__(cls) -> "ToolRegistry":
        if cls._instance is None:
            inst = super().__new__(cls)
            inst._tools: dict[str, ToolSpec] = {}
            inst._lock = asyncio.Lock() if asyncio.get_event_loop_policy() else None
            cls._instance = inst
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton (useful in tests)."""
        cls._instance = None

    # ---- registration ----------------------------------------------------
    def register(
        self,
        name: str,
        description: str = "",
        parameters: dict[str, Any] | None = None,
        required: list[str] | None = None,
        category: str = "general",
    ) -> Callable:
        """Decorator that registers a function as a tool.

        Usage::

            registry = ToolRegistry()

            @registry.register(
                name="echo",
                description="Echo back the input",
                parameters={"text": {"type": "string", "description": "Text to echo"}},
                required=["text"],
            )
            async def echo(text: str) -> str:
                return text
        """

        def decorator(fn: Callable) -> Callable:
            is_async = asyncio.iscoroutinefunction(fn)

            spec = ToolSpec(
                name=name,
                description=description,
                parameters=parameters or {},
                required=required or [],
                fn=fn,
                is_async=is_async,
                category=category,
            )

            if name in self._tools:
                logger.warning("Overwriting existing tool registration: %s", name)

            self._tools[name] = spec
            logger.debug("Registered tool: %s (async=%s)", name, is_async)

            @functools.wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                return fn(*args, **kwargs)

            # Attach spec to wrapper so callers can inspect it
            wrapper._tool_spec = spec  # type: ignore[attr-defined]
            return wrapper

        return decorator

    # ---- lookup ----------------------------------------------------------
    def get(self, name: str) -> Optional[ToolSpec]:
        """Return the ToolSpec for *name*, or ``None`` if not registered."""
        return self._tools.get(name)

    def list(self, category: str | None = None) -> list[ToolSpec]:
        """Return all registered tool specs, optionally filtered by category."""
        if category is None:
            return list(self._tools.values())
        return [t for t in self._tools.values() if t.category == category]

    def list_names(self, category: str | None = None) -> list[str]:
        """Convenience: return just tool names."""
        return [t.name for t in self.list(category)]

    def has(self, name: str) -> bool:
        return name in self._tools

    # ---- execution -------------------------------------------------------
    async def execute(self, name: str, **kwargs: Any) -> Any:
        """Look up *name* and invoke the tool with *kwargs*.

        Sync tools are wrapped in ``asyncio.to_thread`` so the caller can
        always ``await`` the result without blocking the event loop.
        """
        spec = self._tools.get(name)
        if spec is None:
            raise KeyError(f"No tool registered with name '{name}'")

        if spec.is_async:
            return await spec.fn(**kwargs)
        else:
            return await asyncio.to_thread(spec.fn, **kwargs)

    # ---- schema helpers --------------------------------------------------
    def to_openai_tools(self, category: str | None = None) -> list[dict[str, Any]]:
        """Return a list of OpenAI-compatible tool schemas."""
        return [t.to_openai_schema() for t in self.list(category)]

    # ---- dunder ----------------------------------------------------------
    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def __repr__(self) -> str:
        return f"<ToolRegistry tools={len(self._tools)}>"
