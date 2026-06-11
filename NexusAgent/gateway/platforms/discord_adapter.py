"""Discord platform adapter using discord.py."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands

if TYPE_CHECKING:
    from gateway.gateway import Gateway, Message

logger = logging.getLogger(__name__)


class DiscordAdapter:
    """
    Discord adapter supporting channel messages, DMs, attachments,
    and slash commands (/start, /help, /reset).
    """

    platform_name = "discord"

    def __init__(
        self,
        token: str,
        gateway: "Gateway | None" = None,
        download_dir: str | None = None,
        intents: discord.Intents | None = None,
    ) -> None:
        self.token = token
        self.gateway = gateway
        self.download_dir = Path(download_dir or tempfile.mkdtemp(prefix="nexus_dc_"))
        self.download_dir.mkdir(parents=True, exist_ok=True)

        _intents = intents or discord.Intents.default()
        _intents.message_content = True
        _intents.dm_messages = True

        self.client = discord.Client(intents=_intents)
        self.tree = app_commands.CommandTree(self.client)

        self._setup_events()
        self._setup_commands()

    # ------------------------------------------------------------------
    # Adapter protocol
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the Discord client (non-blocking background task)."""
        asyncio_create = __import__("asyncio").ensure_future
        asyncio_create(self.client.start(self.token))
        logger.info("Discord adapter started")

    async def stop(self) -> None:
        """Gracefully close the Discord client."""
        await self.client.close()
        logger.info("Discord adapter stopped")

    async def send_message(self, user_id: str, text: str, **kwargs: Any) -> None:
        """Send a DM to a user by ID."""
        try:
            user = await self.client.fetch_user(int(user_id))
            dm = await user.create_dm()
            # Discord has a 2000-char limit
            for i in range(0, len(text), 2000):
                await dm.send(text[i : i + 2000])
        except (discord.NotFound, discord.HTTPException) as exc:
            logger.error("Failed to send DM to %s: %s", user_id, exc)

    async def send_media(self, user_id: str, file_path: str, caption: str = "", **kwargs: Any) -> None:
        """Send a media file as a DM."""
        try:
            user = await self.client.fetch_user(int(user_id))
            dm = await user.create_dm()
            await dm.send(content=caption or None, file=discord.File(file_path))
        except (discord.NotFound, discord.HTTPException) as exc:
            logger.error("Failed to send media to %s: %s", user_id, exc)

    # ------------------------------------------------------------------
    # Event wiring
    # ------------------------------------------------------------------

    def _setup_events(self) -> None:
        """Register Discord client event handlers."""

        @self.client.event
        async def on_ready() -> None:
            assert self.client.user is not None
            logger.info("Discord bot logged in as %s", self.client.user)
            await self.tree.sync()

        @self.client.event
        async def on_message(message: discord.Message) -> None:
            if message.author == self.client.user:
                return
            if message.author.bot:
                return

            if self.gateway is None:
                return

            # Build attachment list
            attachments: list[dict[str, Any]] = []
            for att in message.attachments:
                dest = self.download_dir / att.filename
                await att.save(dest)
                attachments.append({
                    "type": "file",
                    "path": str(dest),
                    "filename": att.filename,
                    "size": att.size,
                })

            ctx = Message(
                platform=self.platform_name,
                user_id=str(message.author.id),
                channel_id=str(message.channel.id),
                text=message.content,
                message_id=str(message.id),
                reply_to=str(message.reference.message_id) if message.reference else "",
                attachments=attachments,
            )

            response = await self.gateway.route(ctx)
            if response:
                # Split for Discord 2000-char limit
                for i in range(0, len(response), 2000):
                    await message.channel.send(response[i : i + 2000])

    # ------------------------------------------------------------------
    # Slash commands
    # ------------------------------------------------------------------

    def _setup_commands(self) -> None:
        """Register slash commands."""

        @self.tree.command(name="start", description="Start NexusAgent")
        async def cmd_start(interaction: discord.Interaction) -> None:
            await interaction.response.send_message(
                "👋 Welcome to **NexusAgent**! Send me a message to get started.",
            )

        @self.tree.command(name="help", description="Show available commands")
        async def cmd_help(interaction: discord.Interaction) -> None:
            await interaction.response.send_message(
                "📖 **Commands**\n"
                "/start — Welcome message\n"
                "/help — This help text\n"
                "/reset — Reset your session\n\n"
                "Send text, files, images, or voice messages.",
            )

        @self.tree.command(name="reset", description="Reset your session")
        async def cmd_reset(interaction: discord.Interaction) -> None:
            if self.gateway:
                self.gateway.reset_session(str(interaction.user.id), self.platform_name)
            await interaction.response.send_message("🔄 Session reset!")
