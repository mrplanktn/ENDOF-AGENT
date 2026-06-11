"""Telegram platform adapter using python-telegram-bot."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from telegram import BotCommand, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

if TYPE_CHECKING:
    from gateway.gateway import Gateway, Message

logger = logging.getLogger(__name__)


class TelegramAdapter:
    """
    Telegram adapter that handles text, photos, documents, and voice messages.
    Supports /start, /help, and /reset commands.
    """

    platform_name = "telegram"

    def __init__(
        self,
        token: str,
        gateway: "Gateway | None" = None,
        download_dir: str | None = None,
    ) -> None:
        self.token = token
        self.gateway = gateway
        self.download_dir = Path(download_dir or tempfile.mkdtemp(prefix="nexus_tg_"))
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self._app: Application | None = None

    # ------------------------------------------------------------------
    # Adapter protocol
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Build and start the Telegram bot application."""
        self._app = (
            Application.builder()
            .token(self.token)
            .build()
        )

        # Commands
        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(CommandHandler("help", self._cmd_help))
        self._app.add_handler(CommandHandler("reset", self._cmd_reset))

        # Messages
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_text))
        self._app.add_handler(MessageHandler(filters.PHOTO, self._on_photo))
        self._app.add_handler(MessageHandler(filters.Document.ALL, self._on_document))
        self._app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, self._on_voice))

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)

        # Set bot commands menu
        await self._app.bot.set_my_commands([
            BotCommand("start", "Start the bot"),
            BotCommand("help", "Show help"),
            BotCommand("reset", "Reset your session"),
        ])
        logger.info("Telegram adapter started")

    async def stop(self) -> None:
        """Gracefully stop the Telegram bot."""
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
        logger.info("Telegram adapter stopped")

    async def send_message(self, user_id: str, text: str, **kwargs: Any) -> None:
        """Send a text message to a user."""
        if self._app:
            await self._app.bot.send_message(
                chat_id=int(user_id),
                text=text,
                parse_mode="Markdown",
                **kwargs,
            )

    async def send_media(self, user_id: str, file_path: str, caption: str = "", **kwargs: Any) -> None:
        """Send a media file to a user."""
        if not self._app:
            return
        path = Path(file_path)
        chat_id = int(user_id)
        if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
            await self._app.bot.send_photo(chat_id=chat_id, photo=open(path, "rb"), caption=caption)
        elif path.suffix.lower() in {".mp3", ".ogg", ".wav", ".m4a"}:
            await self._app.bot.send_audio(chat_id=chat_id, audio=open(path, "rb"), caption=caption)
        else:
            await self._app.bot.send_document(chat_id=chat_id, document=open(path, "rb"), caption=caption)

    # ------------------------------------------------------------------
    # Internal: file download helper
    # ------------------------------------------------------------------

    async def _download_file(self, file_obj: Any, filename: str) -> Path:
        """Download a Telegram file object to the local download directory."""
        dest = self.download_dir / filename
        tg_file = await file_obj.get_file()
        await tg_file.download_to_drive(dest)
        return dest

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command."""
        if update.message:
            await update.message.reply_text(
                "👋 Welcome to **NexusAgent**!\n\n"
                "I'm your AI assistant. Send me a message to get started.\n"
                "Use /help to see available commands.",
                parse_mode="Markdown",
            )

    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command."""
        if update.message:
            await update.message.reply_text(
                "📖 **Commands**\n\n"
                "/start — Welcome message\n"
                "/help — This help text\n"
                "/reset — Reset your session\n\n"
                "You can send text, photos, documents, and voice messages.",
                parse_mode="Markdown",
            )

    async def _cmd_reset(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /reset command — resets the user session."""
        if update.message and update.effective_user and self.gateway:
            self.gateway.reset_session(str(update.effective_user.id), self.platform_name)
            await update.message.reply_text("🔄 Session reset!")

    # ------------------------------------------------------------------
    # Message handlers
    # ------------------------------------------------------------------

    async def _on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle plain text messages."""
        if not update.message or not update.effective_user or not self.gateway:
            return
        msg = Message(
            platform=self.platform_name,
            user_id=str(update.effective_user.id),
            channel_id=str(update.message.chat_id),
            text=update.message.text or "",
            message_id=str(update.message.message_id),
            reply_to=str(update.message.reply_to_message.message_id) if update.message.reply_to_message else "",
        )
        response = await self.gateway.route(msg)
        if response:
            await update.message.reply_text(response, parse_mode="Markdown")

    async def _on_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle photo messages — downloads the largest photo."""
        if not update.message or not update.effective_user or not self.gateway:
            return
        photo = update.message.photo[-1] if update.message.photo else None
        attachments: list[dict[str, Any]] = []
        if photo:
            path = await self._download_file(photo, f"{photo.file_unique_id}.jpg")
            attachments.append({"type": "photo", "path": str(path)})
        caption = update.message.caption or "[photo]"
        msg = Message(
            platform=self.platform_name,
            user_id=str(update.effective_user.id),
            channel_id=str(update.message.chat_id),
            text=caption,
            message_id=str(update.message.message_id),
            attachments=attachments,
        )
        response = await self.gateway.route(msg)
        if response:
            await update.message.reply_text(response, parse_mode="Markdown")

    async def _on_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle document/file uploads."""
        if not update.message or not update.effective_user or not self.gateway:
            return
        doc = update.message.document
        attachments: list[dict[str, Any]] = []
        if doc:
            fname = doc.file_name or f"{doc.file_unique_id}.bin"
            path = await self._download_file(doc, fname)
            attachments.append({"type": "document", "path": str(path), "filename": fname})
        caption = update.message.caption or f"[document: {doc.file_name if doc else 'unknown'}]"
        msg = Message(
            platform=self.platform_name,
            user_id=str(update.effective_user.id),
            channel_id=str(update.message.chat_id),
            text=caption,
            message_id=str(update.message.message_id),
            attachments=attachments,
        )
        response = await self.gateway.route(msg)
        if response:
            await update.message.reply_text(response, parse_mode="Markdown")

    async def _on_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle voice and audio messages."""
        if not update.message or not update.effective_user or not self.gateway:
            return
        voice = update.message.voice or update.message.audio
        attachments: list[dict[str, Any]] = []
        if voice:
            path = await self._download_file(voice, f"{voice.file_unique_id}.ogg")
            attachments.append({"type": "voice", "path": str(path)})
        msg = Message(
            platform=self.platform_name,
            user_id=str(update.effective_user.id),
            channel_id=str(update.message.chat_id),
            text="[voice message]",
            message_id=str(update.message.message_id),
            attachments=attachments,
        )
        response = await self.gateway.route(msg)
        if response:
            await update.message.reply_text(response, parse_mode="Markdown")
