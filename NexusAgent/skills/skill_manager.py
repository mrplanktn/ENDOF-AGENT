"""SkillManager: load, search, create, update, and inject skills from SKILL.md files."""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Skill:
    """Represents a loaded skill."""

    id: str
    name: str
    description: str
    content: str
    tags: list[str] = field(default_factory=list)
    source_path: str = ""
    enabled: bool = True


class SkillManager:
    """
    Manages skills loaded from SKILL.md files or created programmatically.

    Skills are markdown documents that describe capabilities, instructions,
    or reference material the agent can use in its context.
    """

    def __init__(self, skills_dir: str | Path = "skills") -> None:
        self.skills_dir = Path(skills_dir)
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self._skills: dict[str, Skill] = {}

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load_from_directory(self, directory: str | Path | None = None) -> int:
        """
        Recursively scan a directory for SKILL.md files and load them.

        Args:
            directory: Directory to scan. Defaults to self.skills_dir.

        Returns:
            Number of skills loaded.
        """
        base = Path(directory) if directory else self.skills_dir
        count = 0
        for path in base.rglob("SKILL.md"):
            skill = self._parse_skill_file(path)
            if skill:
                self._skills[skill.id] = skill
                count += 1
                logger.info("Loaded skill '%s' from %s", skill.name, path)
        return count

    def _parse_skill_file(self, path: Path) -> Skill | None:
        """Parse a SKILL.md file into a Skill object."""
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            logger.warning("Cannot read %s", path)
            return None

        # Extract front matter between --- markers
        name = path.parent.name
        description = ""
        tags: list[str] = []
        content = text

        fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
        if fm_match:
            front_matter = fm_match.group(1)
            content = fm_match.group(2).strip()
            for line in front_matter.splitlines():
                key, _, val = line.partition(":")
                key = key.strip().lower()
                val = val.strip().strip('"').strip("'")
                if key == "name":
                    name = val
                elif key == "description":
                    description = val
                elif key == "tags":
                    tags = [t.strip() for t in val.split(",") if t.strip()]

        return Skill(
            id=str(uuid.uuid4()),
            name=name,
            description=description,
            content=content,
            tags=tags,
            source_path=str(path),
        )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def search(self, query: str) -> list[Skill]:
        """
        Search skills by name, description, tags, or content (case-insensitive).

        Args:
            query: Search term.

        Returns:
            List of matching skills.
        """
        q = query.lower()
        results: list[Skill] = []
        for skill in self._skills.values():
            if not skill.enabled:
                continue
            searchable = f"{skill.name} {skill.description} {' '.join(skill.tags)} {skill.content}".lower()
            if q in searchable:
                results.append(skill)
        return results

    def create(self, name: str, content: str, description: str = "", tags: list[str] | None = None) -> Skill:
        """
        Create a new skill programmatically and persist it to disk.

        Args:
            name: Skill name.
            content: Markdown content.
            description: Short description.
            tags: Optional tag list.

        Returns:
            The created Skill.
        """
        skill = Skill(
            id=str(uuid.uuid4()),
            name=name,
            description=description,
            content=content,
            tags=tags or [],
        )
        skill_dir = self.skills_dir / name.lower().replace(" ", "_")
        skill_dir.mkdir(parents=True, exist_ok=True)

        fm = f"---\nname: {name}\ndescription: {description}\ntags: {', '.join(skill.tags)}\n---\n\n"
        md_path = skill_dir / "SKILL.md"
        md_path.write_text(fm + content, encoding="utf-8")
        skill.source_path = str(md_path)

        self._skills[skill.id] = skill
        logger.info("Created skill '%s'", name)
        return skill

    def update(self, skill_id: str, **kwargs: Any) -> Skill | None:
        """
        Update a skill's fields and persist changes.

        Args:
            skill_id: ID of the skill to update.
            **kwargs: Fields to update (name, description, content, tags, enabled).

        Returns:
            The updated Skill, or None if not found.
        """
        skill = self._skills.get(skill_id)
        if not skill:
            return None
        for key, val in kwargs.items():
            if hasattr(skill, key):
                setattr(skill, key, val)
        # Persist if the source file exists
        if skill.source_path:
            p = Path(skill.source_path)
            fm = f"---\nname: {skill.name}\ndescription: {skill.description}\ntags: {', '.join(skill.tags)}\n---\n\n"
            p.write_text(fm + skill.content, encoding="utf-8")
        return skill

    def delete(self, skill_id: str) -> bool:
        """
        Delete a skill. Removes from memory and optionally from disk.

        Returns:
            True if the skill was found and removed.
        """
        skill = self._skills.pop(skill_id, None)
        if skill is None:
            return False
        if skill.source_path:
            p = Path(skill.source_path)
            if p.exists():
                p.unlink()
        logger.info("Deleted skill '%s'", skill.name)
        return True

    def get(self, skill_id: str) -> Skill | None:
        """Get a skill by ID."""
        return self._skills.get(skill_id)

    def list_skills(self, enabled_only: bool = True) -> list[Skill]:
        """List all loaded skills."""
        skills = list(self._skills.values())
        if enabled_only:
            skills = [s for s in skills if s.enabled]
        return skills

    # ------------------------------------------------------------------
    # Context injection
    # ------------------------------------------------------------------

    def inject_context(self, skill_ids: list[str] | None = None, max_chars: int = 8000) -> str:
        """
        Build a context string from selected skills for injection into the agent prompt.

        Args:
            skill_ids: Specific skill IDs to include. None = all enabled skills.
            max_chars: Maximum total characters for the context block.

        Returns:
            Formatted context string.
        """
        skills = []
        if skill_ids:
            skills = [self._skills[sid] for sid in skill_ids if sid in self._skills]
        else:
            skills = [s for s in self._skills.values() if s.enabled]

        parts: list[str] = []
        total = 0
        for skill in skills:
            block = f"### Skill: {skill.name}\n{skill.content}"
            if total + len(block) > max_chars:
                break
            parts.append(block)
            total += len(block)

        return "\n\n---\n\n".join(parts)
