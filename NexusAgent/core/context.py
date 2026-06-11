"""Context and conversation management for NexusAgent."""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

DEFAULT_MAX_TOKENS = 128_000
COMPRESSION_PROTECT_RECENT = 10


def estimate_tokens(text: str) -> int:
    """Rough token estimation."""
    return max(1, len(text) // 4)


def estimate_message_tokens(msg: dict[str, Any]) -> int:
    """Estimate tokens for a single message."""
    total = 4  # role/overhead
    content = msg.get("content", "")
    if isinstance(content, str):
        total += estimate_tokens(content)
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and "text" in part:
                total += estimate_tokens(part["text"])
    if msg.get("tool_calls"):
        import json
        total += estimate_tokens(json.dumps(msg["tool_calls"]))
    return total


@dataclass
class ContextManager:
    """Manages conversation history, system prompt, and context compression."""

    max_tokens: int = DEFAULT_MAX_TOKENS
    protect_recent: int = COMPRESSION_PROTECT_RECENT
    model: str = "gpt-4o"
    messages: list[dict[str, Any]] = field(default_factory=list)
    _system_prompt: str = ""
    _compressor: Callable[[list[dict[str, Any]]], Coroutine[Any, Any, str]] | None = None

    def set_compressor(self, fn: Callable[[list[dict[str, Any]]], Coroutine[Any, Any, str]]) -> None:
        """Set an async function that summarizes a list of messages into a string."""
        self._compressor = fn

    # ── System prompt ───────────────────────────────────────────

    def build_system_prompt(
        self,
        tools: list[dict[str, Any]] | None = None,
        memory: str | None = None,
        skills: list[str] | None = None,
        env_info: dict[str, str] | None = None,
    ) -> str:
        """Build a comprehensive system prompt from components."""
        sections: list[str] = []

        sections.append("You are NexusAgent, a capable AI assistant.")
        sections.append(
            "You have access to tools and should use them when they help accomplish the user's goal. "
            "Think step-by-step before acting. If a tool fails, analyze the error and try alternatives."
        )

        if env_info:
            env_lines = [f"- {k}: {v}" for k, v in env_info.items()]
            sections.append("## Environment\n" + "\n".join(env_lines))

        if tools:
            tool_lines = []
            for t in tools:
                fn = t.get("function", t)
                tool_lines.append(f"- **{fn.get('name', 'unknown')}**: {fn.get('description', '')}")
            sections.append("## Available Tools\n" + "\n".join(tool_lines))

        if skills:
            sections.append("## Active Skills\n" + "\n".join(f"- {s}" for s in skills))

        if memory:
            sections.append("## Memory\n" + memory)

        self._system_prompt = "\n\n".join(sections)
        return self._system_prompt

    # ── Message management ──────────────────────────────────────

    def add_message(self, role: str, content: str | list[Any] | None, **kwargs: Any) -> None:
        """Add a message to the conversation history."""
        msg: dict[str, Any] = {"role": role}
        if content is not None:
            msg["content"] = content
        msg.update(kwargs)
        self.messages.append(msg)

    def get_messages(self) -> list[dict[str, Any]]:
        """Return all messages, with system prompt prepended if set."""
        out: list[dict[str, Any]] = []
        if self._system_prompt:
            out.append({"role": "system", "content": self._system_prompt})
        out.extend(self.messages)
        return out

    def get_raw_messages(self) -> list[dict[str, Any]]:
        """Return messages without system prompt."""
        return list(self.messages)

    def clear(self) -> None:
        """Clear conversation history (keeps system prompt)."""
        self.messages.clear()

    def total_tokens(self) -> int:
        """Estimate total tokens in current context."""
        total = estimate_tokens(self._system_prompt) if self._system_prompt else 0
        total += sum(estimate_message_tokens(m) for m in self.messages)
        return total

    def token_usage_ratio(self) -> float:
        """Return fraction of max_tokens currently used."""
        if self.max_tokens <= 0:
            return 0.0
        return self.total_tokens() / self.max_tokens

    # ── Compression ─────────────────────────────────────────────

    async def compress(self, threshold: float = 0.5) -> int:
        """Compress old messages if token usage exceeds threshold.

        Protects the most recent `protect_recent` messages from compression.

        Returns number of messages compressed.
        """
        if self.token_usage_ratio() < threshold:
            return 0
        if self._compressor is None:
            logger.warning("No compressor set; cannot compress context")
            return 0

        if len(self.messages) <= self.protect_recent:
            return 0

        compressible = self.messages[: -self.protect_recent]
        protected = self.messages[-self.protect_recent :]

        summary = await self._compressor(compressible)
        compressed_count = len(compressible)

        self.messages = [
            {"role": "system", "content": f"[Conversation summary of {compressed_count} messages]\n{summary}"},
            *protected,
        ]
        logger.info("Compressed %d messages into summary", compressed_count)
        return compressed_count

    def trim_to_fit(self, new_message_tokens: int = 0) -> int:
        """Hard-trim oldest unprotected messages to fit within max_tokens.

        Returns number of messages removed.
        """
        removed = 0
        while (
            self.total_tokens() + new_message_tokens > self.max_tokens
            and len(self.messages) > self.protect_recent
        ):
            self.messages.pop(0)
            removed += 1
        return removed
