"""Planning and reflection engine for NexusAgent."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

PLAN_SYSTEM_PROMPT = """You are a planning module for an AI agent. Given a goal and context, produce a clear, actionable plan as a JSON list of steps.

Each step must be an object with:
- "action": what to do (string)
- "tool": which tool to use, if any (string or null)
- "depends_on": indices of steps that must complete first (list of ints)

Output ONLY valid JSON: a list of step objects. No markdown fences."""

REFLECT_SYSTEM_PROMPT = """You are a reflection module for an AI agent. Given a step that was executed and its result, assess the outcome.

Respond with a JSON object:
- "success": boolean
- "quality": "excellent" | "good" | "acceptable" | "poor" | "failed"
- "summary": brief summary of what happened
- "issues": list of any problems encountered
- "suggestion": what to do next, if anything (string or null)

Output ONLY valid JSON."""

REPLAN_SYSTEM_PROMPT = """You are a replanning module for an AI agent. The original plan failed at a step. Given the original plan, which step failed, and the error, produce an adjusted plan.

Output ONLY a JSON list of remaining steps (same format as planning)."""


@dataclass
class PlanStep:
    """A single step in an execution plan."""
    index: int
    action: str
    tool: str | None = None
    depends_on: list[int] = field(default_factory=list)
    status: str = "pending"  # pending | running | done | failed | skipped
    result: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "action": self.action,
            "tool": self.tool,
            "depends_on": self.depends_on,
            "status": self.status,
        }


@dataclass
class Plan:
    """An execution plan consisting of ordered steps."""
    goal: str
    steps: list[PlanStep] = field(default_factory=list)

    def next_runnable(self) -> PlanStep | None:
        """Return the next step whose dependencies are all satisfied."""
        for step in self.steps:
            if step.status != "pending":
                continue
            deps_met = all(
                self.steps[d].status == "done"
                for d in step.depends_on
                if d < len(self.steps)
            )
            if deps_met:
                return step
        return None

    def mark(self, index: int, status: str, result: Any = None) -> None:
        if 0 <= index < len(self.steps):
            self.steps[index].status = status
            self.steps[index].result = result

    def is_complete(self) -> bool:
        return all(s.status in ("done", "skipped") for s in self.steps)

    def has_failures(self) -> bool:
        return any(s.status == "failed" for s in self.steps)


@dataclass
class Reflection:
    """Assessment of a step execution."""
    success: bool
    quality: str
    summary: str
    issues: list[str] = field(default_factory=list)
    suggestion: str | None = None


class Planner:
    """Plans, reflects, and replans using an LLM."""

    def __init__(
        self,
        llm_caller: Any = None,
        max_plan_steps: int = 15,
    ) -> None:
        """
        Args:
            llm_caller: An async callable (messages, system) -> str that calls the LLM.
                        If None, uses a simple heuristic planner.
            max_plan_steps: Maximum number of steps in a plan.
        """
        self._llm = llm_caller
        self._max_steps = max_plan_steps

    async def plan(self, goal: str, context: str = "") -> Plan:
        """Generate an execution plan for the given goal."""
        if self._llm is None:
            return self._heuristic_plan(goal)

        prompt = f"Goal: {goal}"
        if context:
            prompt += f"\n\nContext:\n{context}"

        raw = await self._llm(prompt, PLAN_SYSTEM_PROMPT)
        steps = self._parse_steps(raw)
        plan = Plan(goal=goal, steps=steps[: self._max_steps])
        logger.info("Generated plan with %d steps for goal: %s", len(plan.steps), goal[:80])
        return plan

    async def reflect(self, step: PlanStep, result: Any = None) -> Reflection:
        """Reflect on the outcome of a step execution."""
        if self._llm is None:
            return self._heuristic_reflect(step, result)

        prompt = (
            f"Step: {step.action}\n"
            f"Tool used: {step.tool or 'none'}\n"
            f"Result:\n{json.dumps(result, default=str)[:3000]}"
        )
        raw = await self._llm(prompt, REFLECT_SYSTEM_PROMPT)
        return self._parse_reflection(raw)

    async def replan(self, original_plan: Plan, failed_step: PlanStep, error: str) -> Plan:
        """Generate an adjusted plan after a failure."""
        if self._llm is None:
            return self._heuristic_replan(original_plan, failed_step)

        completed = [s.to_dict() for s in original_plan.steps if s.status == "done"]
        remaining = [s.to_dict() for s in original_plan.steps if s.status == "pending"]
        prompt = (
            f"Original plan:\n{json.dumps([s.to_dict() for s in original_plan.steps], indent=2)}\n\n"
            f"Failed step ({failed_step.index}): {failed_step.action}\n"
            f"Error: {error}\n\n"
            f"Completed steps: {json.dumps(completed)}\n"
            f"Remaining steps: {json.dumps(remaining)}"
        )
        raw = await self._llm(prompt, REPLAN_SYSTEM_PROMPT)
        new_steps = self._parse_steps(raw)

        # Keep completed steps, append new plan
        kept = [s for s in original_plan.steps if s.status == "done"]
        offset = len(kept)
        adjusted_steps = []
        for s in kept:
            adjusted_steps.append(s)
        for i, ns in enumerate(new_steps):
            ns.index = offset + i
            ns.depends_on = [d - (failed_step.index + 1) + offset for d in ns.depends_on if d >= 0]
            # Clamp deps to valid range
            ns.depends_on = [max(0, min(d, offset + len(new_steps) - 1)) for d in ns.depends_on]
            adjusted_steps.append(ns)

        plan = Plan(goal=original_plan.goal, steps=adjusted_steps[: self._max_steps])
        logger.info("Replanned: %d kept + %d new steps", len(kept), len(new_steps))
        return plan

    # ── Parsing ─────────────────────────────────────────────────

    def _parse_steps(self, raw: str) -> list[PlanStep]:
        """Parse LLM output into PlanStep objects."""
        text = raw.strip()
        # Strip markdown fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Failed to parse plan as JSON, treating as single step")
            return [PlanStep(index=0, action=text[:500])]

        if isinstance(data, dict):
            data = data.get("steps", [data])
        if not isinstance(data, list):
            return [PlanStep(index=0, action=str(data)[:500])]

        steps = []
        for i, item in enumerate(data):
            if isinstance(item, str):
                steps.append(PlanStep(index=i, action=item))
            elif isinstance(item, dict):
                steps.append(PlanStep(
                    index=i,
                    action=item.get("action", item.get("step", str(item))),
                    tool=item.get("tool"),
                    depends_on=item.get("depends_on", []),
                ))
        return steps

    def _parse_reflection(self, raw: str) -> Reflection:
        """Parse LLM reflection output."""
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)
        try:
            data = json.loads(text)
            return Reflection(
                success=data.get("success", True),
                quality=data.get("quality", "acceptable"),
                summary=data.get("summary", ""),
                issues=data.get("issues", []),
                suggestion=data.get("suggestion"),
            )
        except (json.JSONDecodeError, TypeError):
            return Reflection(success=True, quality="acceptable", summary=raw[:500])

    # ── Heuristic fallbacks ─────────────────────────────────────

    def _heuristic_plan(self, goal: str) -> Plan:
        """Simple single-step plan when no LLM is available."""
        return Plan(goal=goal, steps=[PlanStep(index=0, action=goal)])

    def _heuristic_reflect(self, step: PlanStep, result: Any = None) -> Reflection:
        """Simple reflection based on whether the step errored."""
        if step.status == "failed":
            return Reflection(success=False, quality="failed", summary=str(result)[:500], issues=["Step failed"])
        return Reflection(success=True, quality="good", summary="Step completed successfully")

    def _heuristic_replan(self, original_plan: Plan, failed_step: PlanStep) -> Plan:
        """Skip the failed step and continue with remaining."""
        for step in original_plan.steps:
            if step.status == "pending":
                step.depends_on = [d for d in step.depends_on if d != failed_step.index]
        return original_plan
