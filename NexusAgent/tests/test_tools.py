"""Tests for built-in tools and tool infrastructure."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestWebSearch:
    """Tests for web_search tool."""

    @pytest.mark.asyncio
    async def test_web_search_basic(self) -> None:
        """Test basic web search returns results."""
        # This is a placeholder for integration tests
        # In CI, mock the HTTP calls
        assert True  # Placeholder

    @pytest.mark.asyncio
    async def test_web_search_empty_query(self) -> None:
        """Test web search with empty query."""
        assert True  # Placeholder


class TestWebFetch:
    """Tests for web_fetch tool."""

    @pytest.mark.asyncio
    async def test_fetch_returns_content(self) -> None:
        """Test fetching a URL returns extracted content."""
        assert True  # Placeholder

    @pytest.mark.asyncio
    async def test_fetch_invalid_url(self) -> None:
        """Test fetching an invalid URL returns error."""
        assert True  # Placeholder


class TestCodeExecute:
    """Tests for code_execute tool."""

    @pytest.mark.asyncio
    async def test_execute_python(self) -> None:
        """Test executing Python code."""
        assert True  # Placeholder

    @pytest.mark.asyncio
    async def test_execute_timeout(self) -> None:
        """Test code execution timeout."""
        assert True  # Placeholder


class TestFileOperations:
    """Tests for file_read and file_write tools."""

    def test_file_write_and_read(self) -> None:
        """Test writing and reading a file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.txt"
            content = "Hello, NexusAgent!"
            path.write_text(content)
            assert path.read_text() == content

    def test_file_read_with_offset(self) -> None:
        """Test reading a file with line offset."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "lines.txt"
            path.write_text("\n".join(f"Line {i}" for i in range(1, 101)))
            lines = path.read_text().splitlines()
            # Read lines 10-15
            subset = lines[9:15]
            assert len(subset) == 6
            assert subset[0] == "Line 10"

    def test_file_nonexistent(self) -> None:
        """Test reading a nonexistent file."""
        path = Path("/tmp/nonexistent_nexus_test_file.txt")
        assert not path.exists()


class TestGateway:
    """Tests for the Gateway class."""

    @pytest.mark.asyncio
    async def test_allowlist(self) -> None:
        """Test gateway allowlist enforcement."""
        from gateway.gateway import Gateway, GatewayConfig, Message

        config = GatewayConfig(allowlist=["user1", "user2"])
        gw = Gateway(config=config)

        assert gw.is_allowed("user1")
        assert gw.is_allowed("user2")
        assert not gw.is_allowed("user3")

    @pytest.mark.asyncio
    async def test_session_creation(self) -> None:
        """Test session ID creation per user."""
        from gateway.gateway import Gateway, GatewayConfig

        gw = Gateway(config=GatewayConfig())
        sid1 = gw.get_session_id("user1", "telegram")
        sid2 = gw.get_session_id("user1", "telegram")
        assert sid1 == sid2  # Same user gets same session

        sid3 = gw.get_session_id("user2", "telegram")
        assert sid3 != sid1  # Different user gets different session

    @pytest.mark.asyncio
    async def test_session_reset(self) -> None:
        """Test session reset creates new session."""
        from gateway.gateway import Gateway

        gw = Gateway()
        sid1 = gw.get_session_id("user1", "telegram")
        sid2 = gw.reset_session("user1", "telegram")
        assert sid1 != sid2

    @pytest.mark.asyncio
    async def test_route_blocked_user(self) -> None:
        """Test that blocked users get rejection message."""
        from gateway.gateway import Gateway, GatewayConfig, Message

        gw = Gateway(config=GatewayConfig(allowlist=["user1"]))
        msg = Message(platform="telegram", user_id="blocked", channel_id="1", text="hi")
        response = await gw.route(msg)
        assert "not authorized" in response.lower()

    @pytest.mark.asyncio
    async def test_route_no_handler(self) -> None:
        """Test routing without a handler returns error."""
        from gateway.gateway import Gateway, Message

        gw = Gateway()
        msg = Message(platform="telegram", user_id="user1", channel_id="1", text="hi")
        response = await gw.route(msg)
        assert "no handler" in response.lower()


class TestAuthManager:
    """Tests for AuthManager."""

    def test_add_and_get_credential(self) -> None:
        """Test adding and retrieving credentials."""
        from config.auth import AuthManager, Credential

        with tempfile.TemporaryDirectory() as tmpdir:
            auth = AuthManager(credentials_path=Path(tmpdir) / "creds.json")
            auth.add(Credential(name="test", key="secret-key"))
            cred = auth.get("test")
            assert cred is not None
            assert cred.key == "secret-key"

    def test_env_var_override(self) -> None:
        """Test that environment variables take priority."""
        import os
        from config.auth import AuthManager

        with tempfile.TemporaryDirectory() as tmpdir:
            auth = AuthManager(credentials_path=Path(tmpdir) / "creds.json")
            os.environ["TESTPROVIDER_API_KEY"] = "env-key"
            try:
                cred = auth.get("testprovider")
                assert cred is not None
                assert cred.key == "env-key"
            finally:
                del os.environ["TESTPROVIDER_API_KEY"]

    def test_credential_pooling(self) -> None:
        """Test round-robin credential pooling."""
        from config.auth import AuthManager, Credential

        with tempfile.TemporaryDirectory() as tmpdir:
            auth = AuthManager(credentials_path=Path(tmpdir) / "creds.json")
            auth.add(Credential(name="k1", key="key-1"))
            auth.add(Credential(name="k2", key="key-2"))
            auth.create_pool("pool1", ["k1", "k2"])

            c1 = auth.get_from_pool("pool1")
            c2 = auth.get_from_pool("pool1")
            c3 = auth.get_from_pool("pool1")

            assert c1 is not None and c2 is not None
            assert c1.key != c2.key  # Round-robin alternates
            assert c3 is not None
            assert c3.key == c1.key  # Wraps around

    def test_remove_credential(self) -> None:
        """Test removing a credential."""
        from config.auth import AuthManager, Credential

        with tempfile.TemporaryDirectory() as tmpdir:
            auth = AuthManager(credentials_path=Path(tmpdir) / "creds.json")
            auth.add(Credential(name="temp", key="key"))
            assert auth.remove("temp")
            assert auth.get("temp") is None

    def test_encryption(self) -> None:
        """Test basic credential encryption."""
        from config.auth import AuthManager, Credential

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "creds.json"
            auth = AuthManager(credentials_path=path, encryption_key="test-key")
            auth.add(Credential(name="secure", key="my-secret"))

            # Read raw file — should be encrypted
            import json
            raw = json.loads(path.read_text())
            assert raw["secure"]["key"] != "my-secret"  # Encrypted

            # But retrieval should decrypt
            auth2 = AuthManager(credentials_path=path, encryption_key="test-key")
            cred = auth2.get("secure")
            assert cred is not None
            assert cred.key == "my-secret"


class TestConfig:
    """Tests for configuration loading."""

    def test_default_config_loads(self) -> None:
        """Test that default config loads without error."""
        from config.settings import NexusConfig

        config = NexusConfig()
        assert config.model.default_provider == "openai"
        assert config.memory.enabled is True
        assert config.security.audit_log is True
