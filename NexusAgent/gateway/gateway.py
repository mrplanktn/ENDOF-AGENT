"""Gateway: manages platform adapters, routes messages to the agent with session/auth support."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class PlatformAdapter(Protocol):
    """Protocol that every platform adapter must implement."""

    platform_name: str

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def send_message(self, user_id: str, text: str, **kwargs: Any) -> None: ...
    async def send_media(self, user_id: str, file_path: str, caption: str = "", **kwargs: Any) -> None: ...


@dataclass
class Message:
    """Incoming message from any platform."""

    platform: str
    user_id: str
    channel_id: str
    text: str
    message_id: str = ""
    reply_to: str = ""
    attachments: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GatewayConfig:
    """Configuration for the gateway."""

    allowlist: list[str] = field(default_factory=list)
    require_auth: bool = False
    max_message_length: int = 4096
    session_timeout_minutes: int = 60


class MessageHandler(Protocol):
    """Protocol for the agent handler that processes incoming messages."""

    async def handle(self, message: Message, session_id: str) -> str: ...


class Gateway:
    """
    Central gateway that manages platform adapters, routes messages to the
    agent, maintains per-user sessions, and enforces authentication.
    """

    def __init__(
        self,
        config: GatewayConfig | None = None,
        handler: MessageHandler | None = None,
    ) -> None:
        self.config = config or GatewayConfig()
        self.handler = handler
        self._adapters: dict[str, PlatformAdapter] = {}
        self._sessions: dict[str, str] = {}  # user_key -> session_id
        self._running = False

    # ------------------------------------------------------------------
    # Adapter management
    # ------------------------------------------------------------------

    def register_adapter(self, adapter: PlatformAdapter) -> None:
        """Register a platform adapter with the gateway."""
        self._adapters[adapter.platform_name] = adapter
        logger.info("Registered adapter: %s", adapter.platform_name)

    def get_adapter(self, platform: str) -> PlatformAdapter | None:
        """Retrieve a registered adapter by platform name."""
        return self._adapters.get(platform)

    # ------------------------------------------------------------------
    # Auth / allowlist
    # ------------------------------------------------------------------

    def is_allowed(self, user_id: str) -> bool:
        """Check whether a user passes the allowlist gate."""
        if not self.config.allowlist:
            return True
        return user_id in self.config.allowlist

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def get_session_id(self, user_id: str, platform: str) -> str:
        """Get or create a session ID for a user on a given platform."""
        key = f"{platform}:{user_id}"
        if key not in self._sessions:
            import uuid
            self._sessions[key] = str(uuid.uuid4())
        return self._sessions[key]

    def reset_session(self, user_id: str, platform: str) -> str:
        """Reset the session for a user, returning the new session ID."""
        import uuid
        key = f"{platform}:{user_id}"
        self._sessions[key] = str(uuid.uuid4())
        return self._sessions[key]

    # ------------------------------------------------------------------
    # Message routing
    # ------------------------------------------------------------------

    async def route(self, message: Message) -> str:
        """
        Route an incoming message through auth checks and to the handler.

        Returns the response text, or an error/empty string on failure.
        """
        if not self.is_allowed(message.user_id):
            logger.warning("Blocked message from unauthorized user: %s", message.user_id)
            return "⛔ You are not authorized to use this service."

        session_id = self.get_session_id(message.user_id, message.platform)

        if self.handler is None:
            logger.error("No message handler registered")
            return "⚠️ No handler configured."

        try:
            response = await self.handler.handle(message, session_id)
        except Exception:
            logger.exception("Handler error for user %s", message.user_id)
            return "⚠️ An internal error occurred. Please try again."

        # Truncate if needed
        if len(response) > self.config.max_message_length:
            response = response[: self.config.max_message_length - 20] + "\n\n… _(truncated)_"

        return response

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start all registered adapters."""
        self._running = True
        tasks = [adapter.start() for adapter in self._adapters.values()]
        if tasks:
            await asyncio.gather(*tasks)
        logger.info("Gateway started with %d adapter(s)", len(self._adapters))

    async def stop(self) -> None:
        """Stop all registered adapters."""
        self._running = False
        for adapter in self._adapters.values():
            await adapter.stop()
        logger.info("Gateway stopped")
