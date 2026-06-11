"""AuthManager: API key management, OAuth token storage, and credential pooling."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Credential:
    """A stored credential (API key or OAuth token)."""

    name: str
    key: str
    secret: str = ""
    token: str = ""
    refresh_token: str = ""
    expires_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        """Check whether this credential's token has expired."""
        if self.expires_at <= 0:
            return False
        return time.time() >= self.expires_at

    @property
    def is_valid(self) -> bool:
        """Check whether this credential has a non-empty key or token."""
        return bool(self.key or self.token)


class AuthManager:
    """
    Manages API keys, OAuth tokens, and credential pooling.

    Credentials are stored encrypted on disk (or as JSON if encryption
    is unavailable) and can be loaded from environment variables.
    """

    def __init__(self, credentials_path: str | Path | None = None, encryption_key: str = "") -> None:
        self.credentials_path = Path(credentials_path or "~/.nexusagent/credentials.json").expanduser()
        self.credentials_path.parent.mkdir(parents=True, exist_ok=True)
        self._encryption_key = encryption_key
        self._credentials: dict[str, Credential] = {}
        self._pools: dict[str, list[str]] = {}  # pool_name -> [credential_names]
        self._pool_index: dict[str, int] = {}   # pool_name -> current index (round-robin)
        self._load()

    # ------------------------------------------------------------------
    # Credential CRUD
    # ------------------------------------------------------------------

    def add(self, credential: Credential) -> None:
        """
        Add or update a credential.

        Args:
            credential: The Credential to store.
        """
        self._credentials[credential.name] = credential
        self._save()
        logger.info("Stored credential: %s", credential.name)

    def get(self, name: str) -> Credential | None:
        """
        Get a credential by name.

        Checks environment variables first (e.g. OPENAI_API_KEY),
        then falls back to stored credentials.

        Args:
            name: Credential name (e.g. 'openai', 'anthropic').

        Returns:
            The Credential, or None if not found.
        """
        # Check environment first
        env_key = f"{name.upper()}_API_KEY"
        env_val = os.environ.get(env_key)
        if env_val:
            return Credential(name=name, key=env_val)
        return self._credentials.get(name)

    def remove(self, name: str) -> bool:
        """Remove a credential by name. Returns True if removed."""
        removed = self._credentials.pop(name, None)
        if removed:
            self._save()
        return removed is not None

    def list_credentials(self) -> list[Credential]:
        """List all stored credentials (without exposing secrets)."""
        return list(self._credentials.values())

    # ------------------------------------------------------------------
    # Credential pooling (round-robin)
    # ------------------------------------------------------------------

    def create_pool(self, pool_name: str, credential_names: list[str]) -> None:
        """
        Create a named pool of credentials for round-robin usage.

        Args:
            pool_name: Name for the pool.
            credential_names: List of credential names to include.
        """
        self._pools[pool_name] = credential_names
        self._pool_index[pool_name] = 0

    def get_from_pool(self, pool_name: str) -> Credential | None:
        """
        Get the next credential from a pool (round-robin).

        Skips expired credentials automatically.

        Returns:
            The next valid Credential, or None if pool is empty/exhausted.
        """
        names = self._pools.get(pool_name, [])
        if not names:
            return None
        start = self._pool_index.get(pool_name, 0)
        for i in range(len(names)):
            idx = (start + i) % len(names)
            cred = self.get(names[idx])
            if cred and cred.is_valid and not cred.is_expired:
                self._pool_index[pool_name] = (idx + 1) % len(names)
                return cred
        return None

    # ------------------------------------------------------------------
    # OAuth helpers
    # ------------------------------------------------------------------

    def store_oauth_token(
        self,
        name: str,
        access_token: str,
        refresh_token: str = "",
        expires_in: int = 0,
    ) -> None:
        """
        Store an OAuth token.

        Args:
            name: Credential name.
            access_token: The access token.
            refresh_token: Optional refresh token.
            expires_in: Token lifetime in seconds (0 = no expiry).
        """
        cred = Credential(
            name=name,
            key="",
            token=access_token,
            refresh_token=refresh_token,
            expires_at=time.time() + expires_in if expires_in > 0 else 0,
        )
        self.add(cred)

    def refresh_oauth(self, name: str, refresh_fn: Any) -> Credential | None:
        """
        Refresh an OAuth token using the provided refresh function.

        Args:
            name: Credential name.
            refresh_fn: Async callable(refresh_token) -> (access_token, refresh_token, expires_in).

        Returns:
            Updated Credential or None.
        """
        cred = self._credentials.get(name)
        if not cred or not cred.refresh_token:
            return None
        try:
            access_token, new_refresh, expires_in = refresh_fn(cred.refresh_token)
            cred.token = access_token
            cred.refresh_token = new_refresh
            cred.expires_at = time.time() + expires_in if expires_in > 0 else 0
            self._save()
            return cred
        except Exception:
            logger.exception("Failed to refresh OAuth token for %s", name)
            return None

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save(self) -> None:
        """Persist credentials to disk."""
        data = {}
        for name, cred in self._credentials.items():
            data[name] = {
                "name": cred.name,
                "key": self._encrypt(cred.key),
                "secret": self._encrypt(cred.secret),
                "token": self._encrypt(cred.token),
                "refresh_token": self._encrypt(cred.refresh_token),
                "expires_at": cred.expires_at,
                "metadata": cred.metadata,
            }
        self.credentials_path.write_text(json.dumps(data, indent=2))

    def _load(self) -> None:
        """Load credentials from disk."""
        if not self.credentials_path.exists():
            return
        try:
            data = json.loads(self.credentials_path.read_text())
            for name, d in data.items():
                self._credentials[name] = Credential(
                    name=d["name"],
                    key=self._decrypt(d.get("key", "")),
                    secret=self._decrypt(d.get("secret", "")),
                    token=self._decrypt(d.get("token", "")),
                    refresh_token=self._decrypt(d.get("refresh_token", "")),
                    expires_at=d.get("expires_at", 0),
                    metadata=d.get("metadata", {}),
                )
        except (json.JSONDecodeError, KeyError):
            logger.warning("Failed to load credentials from %s", self.credentials_path)

    def _encrypt(self, value: str) -> str:
        """Encrypt a value. Uses XOR with key for basic obfuscation (not production crypto)."""
        if not value or not self._encryption_key:
            return value
        key_bytes = self._encryption_key.encode()
        encrypted = bytes(b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(value.encode()))
        return encrypted.hex()

    def _decrypt(self, value: str) -> str:
        """Decrypt a value encrypted by _encrypt."""
        if not value or not self._encryption_key:
            return value
        try:
            encrypted = bytes.fromhex(value)
            key_bytes = self._encryption_key.encode()
            decrypted = bytes(b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(encrypted))
            return decrypted.decode()
        except (ValueError, UnicodeDecodeError):
            return value
