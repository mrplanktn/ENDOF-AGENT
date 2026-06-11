"""Tests for the core agent components."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest


class TestMemoryStore:
    """Tests for MemoryStore."""

    def test_save_and_search(self) -> None:
        """Test saving and searching memories."""
        from memory.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(Path(tmpdir) / "test.db")
            entry = store.save("fact", "Python is a programming language", user_id="user1")
            assert entry.content == "Python is a programming language"
            assert entry.category == "fact"
            assert entry.id

            results = store.search("Python")
            assert len(results) >= 1
            assert results[0].content == "Python is a programming language"
            store.close()

    def test_user_profile(self) -> None:
        """Test user profile CRUD."""
        from memory.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(Path(tmpdir) / "test.db")
            store.update_user_profile("user1", {"name": "Alice", "lang": "en"})
            profile = store.get_user_profile("user1")
            assert profile["name"] == "Alice"
            assert profile["lang"] == "en"

            # Merge update
            store.update_user_profile("user1", {"theme": "dark"})
            profile = store.get_user_profile("user1")
            assert profile["name"] == "Alice"
            assert profile["theme"] == "dark"
            store.close()

    def test_delete(self) -> None:
        """Test deleting a memory."""
        from memory.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(Path(tmpdir) / "test.db")
            entry = store.save("test", "delete me")
            assert store.delete(entry.id)
            assert not store.delete("nonexistent")
            store.close()

    def test_list_recent(self) -> None:
        """Test listing recent memories."""
        from memory.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(Path(tmpdir) / "test.db")
            for i in range(5):
                store.save("test", f"Memory {i}")
            recent = store.list_recent(limit=3)
            assert len(recent) == 3
            store.close()


class TestSessionStore:
    """Tests for SessionStore."""

    def test_create_and_resume(self) -> None:
        """Test session creation and message history."""
        from sessions.session_store import SessionStore

        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(Path(tmpdir) / "test.db")
            session = store.create("user1", "telegram")
            assert session.user_id == "user1"
            assert session.platform == "telegram"

            store.add_message(session.id, "user", "Hello!")
            store.add_message(session.id, "assistant", "Hi there!")
            messages = store.resume(session.id)
            assert len(messages) == 2
            assert messages[0].content == "Hello!"
            assert messages[1].content == "Hi there!"
            store.close()

    def test_list_sessions(self) -> None:
        """Test listing sessions."""
        from sessions.session_store import SessionStore

        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(Path(tmpdir) / "test.db")
            store.create("user1", "telegram")
            store.create("user1", "discord")
            store.create("user2", "telegram")

            all_sessions = store.list_sessions()
            assert len(all_sessions) == 3

            user1_sessions = store.list_sessions(user_id="user1")
            assert len(user1_sessions) == 2
            store.close()

    def test_delete_session(self) -> None:
        """Test deleting a session cascades to messages."""
        from sessions.session_store import SessionStore

        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(Path(tmpdir) / "test.db")
            session = store.create("user1", "telegram")
            store.add_message(session.id, "user", "test")
            assert store.delete(session.id)
            assert store.get(session.id) is None
            store.close()

    def test_search_messages(self) -> None:
        """Test FTS5 message search."""
        from sessions.session_store import SessionStore

        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(Path(tmpdir) / "test.db")
            session = store.create("user1", "telegram")
            store.add_message(session.id, "user", "Tell me about Python programming")
            store.add_message(session.id, "assistant", "Python is a versatile language")

            results = store.search_messages("Python")
            assert len(results) >= 1
            store.close()


class TestSkillManager:
    """Tests for SkillManager."""

    def test_create_and_search(self) -> None:
        """Test skill creation and search."""
        from skills.skill_manager import SkillManager

        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = SkillManager(tmpdir)
            skill = mgr.create("Test Skill", "This is about Python", description="Python basics", tags=["python"])
            assert skill.name == "Test Skill"

            results = mgr.search("Python")
            assert len(results) >= 1
            assert results[0].name == "Test Skill"

    def test_update_and_delete(self) -> None:
        """Test skill update and deletion."""
        from skills.skill_manager import SkillManager

        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = SkillManager(tmpdir)
            skill = mgr.create("Temp", "content")
            updated = mgr.update(skill.id, description="Updated desc")
            assert updated is not None
            assert updated.description == "Updated desc"

            assert mgr.delete(skill.id)
            assert mgr.get(skill.id) is None

    def test_inject_context(self) -> None:
        """Test context injection."""
        from skills.skill_manager import SkillManager

        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = SkillManager(tmpdir)
            mgr.create("Skill1", "Content 1")
            mgr.create("Skill2", "Content 2")
            ctx = mgr.inject_context()
            assert "Skill1" in ctx
            assert "Skill2" in ctx
