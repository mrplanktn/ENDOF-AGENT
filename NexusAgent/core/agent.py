"""Main agent loop for NexusAgent — orchestrates LLM calls, tool execution, planning, and reflection."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Coroutine

from .context import ContextManager
from .model_router import ModelRouter, estimate_tokens
from .planner import Plan, Planner, PlanStep, Reflection
from .tool_dispatch import ToolRegistry, ToolResult

logger = logging.getLogger(__name__)

# ── Hook types ──────────────────────────────────────────────────

ToolStartHook = Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]
ToolEndHook = Callable[[ToolResult], Coroutine[Any, Any, None]]
LLMResponseHook = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]
ErrorHook = Callable[[Exception, str], Coroutine[Any, Any, None]]


@dataclass
class AgentHooks:
    """Event hooks for the agent lifecycle."""
    on_tool_start: ToolStartHook | None = None
    on_tool_end: ToolEndHook | None = None
    on_llm_response: LLMResponseHook | None = None
    on_error: ErrorHook | None = None


@dataclass
class AgentConfig:
    """Configuration for the agent loop."""
    model: str = "gpt-4o"
    max_turns: int = 25
    max_retries: int = 3
    enable_planning: bool = True
    enable_reflection: bool = True
    stream: bool = False


class AgentLoop:
    """
    Core agent loop: receives a user message, iteratively calls the LLM,
    executes tool calls, reflects on results, and returns a final response.
    """

    def __init__(
        self,
        router: ModelRouter,
        context: ContextManager,
        tools: ToolRegistry,
        config: AgentConfig | None = None,
        hooks: AgentHooks | None = None,
    ) -> None:
        self.router = router
        self.context = context
        self.tools = tools
        self.config = config or AgentConfig()
        self.hooks = hooks or AgentHooks()
        self._planner = Planner(llm_caller=self._llm_plan_call)

    # ── Public API ──────────────────────────────────────────────

    async def run(
        self,
        user_message: str,
        tools: list[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Run the agent loop and return the final text response.

        Args:
            user_message: The user's input message.
            tools: Optional list of tool names to restrict to (None = all).
            context: Optional additional context dict.
        """
        self.context.add_message("user", user_message)

        # Compression check before starting
        await self.context.compress(threshold=0.8)

        # Planning phase
        plan: Plan | None = None
        if self.config.enable_planning:
            goal_context = json.dumps(context, default=str)[:2000] if context else ""
            plan = await self._planner.plan(user_message, goal_context)
            logger.info("Plan created with %d steps", len(plan.steps))

        final_response = ""
        for turn in range(self.config.max_turns):
            logger.debug("Turn %d/%d", turn + 1, self.config.max_turns)

            # Build messages and tool schemas
            messages = self.context.get_messages()
            active_tools = self._get_tool_schemas(tools)

            # Call LLM with retry
            response = await self._call_llm_with_retry(messages, active_tools)
            if self.hooks.on_llm_response:
                await self.hooks.on_llm_response(response)

            content = response.get("content", "")
            tool_calls = response.get("tool_calls", [])

            if not tool_calls:
                # No tool calls — agent is done
                final_response = content or ""
                self.context.add_message("assistant", final_response)
                break

            # Add assistant message (with tool calls) to context
            assistant_msg: dict[str, Any] = {"role": "assistant", "content": content or ""}
            assistant_msg["tool_calls"] = tool_calls
            self.context.add_message(
                "assistant",
                content or "",
                tool_calls=tool_calls,
            )

            # Execute tool calls in parallel
            tool_results = await self._execute_tool_calls(tool_calls, plan)

            # Add tool results to context
            for tc, result in zip(tool_calls, tool_results):
                fn = tc.get("function", {})
                tool_content = json.dumps(result.output if result.success else {"error": result.error}, default=str)
                self.context.add_message("tool", tool_content, tool_call_id=tc.get("id", ""))

                # Update plan status
                if plan and fn.get("name"):
                    for step in plan.steps:
                        if step.tool == fn["name"] and step.status == "pending":
                            plan.mark(step.index, "done" if result.success else "failed", result.output)
                            break

            # Reflection phase
            if self.config.enable_reflection and plan:
                await self._reflect_on_results(plan, tool_results)

        else:
            # Max turns exhausted
            final_response = content or "I've reached the maximum number of reasoning steps. Here's what I have so far."
            self.context.add_message("assistant", final_response)

        return final_response

    async def run_streaming(
        self,
        user_message: str,
        tools: list[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        """Run the agent loop with streaming support, yielding text chunks."""
        self.context.add_message("user", user_message)
        await self.context.compress(threshold=0.8)

        active_tools = self._get_tool_schemas(tools)
        full_response = ""

        for turn in range(self.config.max_turns):
            messages = self.context.get_messages()
            response = await self._call_llm_with_retry(messages, active_tools, stream=True)

            # If we got an async iterator back, stream it
            if hasattr(response, "__aiter__"):
                async for chunk in response:
                    full_response += chunk
                    yield chunk
                # Build a proper response dict for context
                response = {"role": "assistant", "content": full_response, "tool_calls": []}

            content = response.get("content", "")
            tool_calls = response.get("tool_calls", [])

            if not tool_calls:
                if not full_response:
                    full_response = content or ""
                    self.context.add_message("assistant", full_response)
                break

            self.context.add_message("assistant", content or "", tool_calls=tool_calls)
            tool_results = await self._execute_tool_calls(tool_calls)

            for tc, result in zip(tool_calls, tool_results):
                tool_content = json.dumps(result.output if result.success else {"error": result.error}, default=str)
                self.context.add_message("tool", tool_content, tool_call_id=tc.get("id", ""))

            # Reset for next iteration's streaming
            full_response = ""

        if not full_response:
            yield ""

    # ── Internal helpers ────────────────────────────────────────

    async def _call_llm_with_retry(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        stream: bool = False,
    ) -> dict[str, Any]:
        """Call the LLM with retry on transient errors."""
        last_error: Exception | None = None
        for attempt in range(self.config.max_retries):
            try:
                return await self.router.call(
                    model=self.config.model,
                    messages=messages,
                    tools=tools if tools else None,
                    stream=stream,
                )
            except Exception as exc:
                last_error = exc
                logger.warning("LLM call attempt %d failed: %s", attempt + 1, exc)
                if self.hooks.on_error:
                    await self.hooks.on_error(exc, "llm_call")
                if attempt < self.config.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)

        raise RuntimeError(f"LLM call failed after {self.config.max_retries} attempts: {last_error}")

    async def _execute_tool_calls(
        self,
        tool_calls: list[dict[str, Any]],
        plan: Plan | None = None,
    ) -> list[ToolResult]:
        """Execute tool calls in parallel with hooks."""
        dispatch_items: list[dict[str, Any]] = []
        for tc in tool_calls:
            fn = tc.get("function", {})
            name = fn.get("name", "unknown")
            try:
                args = json.loads(fn.get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {}

            dispatch_items.append({"name": name, "args": args})

            # Fire hook
            if self.hooks.on_tool_start:
                await self.hooks.on_tool_start(name, args)

        results = await self.tools.execute_parallel(dispatch_items)

        # Fire end hooks
        if self.hooks.on_tool_end:
            for result in results:
                await self.hooks.on_tool_end(result)

        return results

    async def _reflect_on_results(self, plan: Plan, results: list[ToolResult]) -> None:
        """Run reflection on tool results and potentially trigger replanning."""
        for result in results:
            if not result.success:
                # Find the corresponding plan step
                for step in plan.steps:
                    if step.tool == result.tool_name and step.status == "failed":
                        reflection = await self._planner.reflect(step, result.error)
                        logger.info("Reflection: %s — %s", reflection.quality, reflection.summary)

                        if reflection.quality in ("poor", "failed"):
                            # Replan
                            new_plan = await self._planner.replan(plan, step, result.error or "unknown error")
                            plan.steps.clear()
                            plan.steps.extend(new_plan.steps)
                            logger.info("Replanned: now %d steps", len(plan.steps))
                        break

    async def _llm_plan_call(self, prompt: str, system: str) -> str:
        """LLM caller for the planner — uses the router directly."""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        response = await self.router.call(
            model=self.config.model,
            messages=messages,
            tools=None,
            stream=False,
        )
        return response.get("content", "")

    def _get_tool_schemas(self, tool_names: list[str] | None = None) -> list[dict[str, Any]]:
        """Get OpenAI-format tool schemas from the registry."""
        all_tools = self.tools.list_tools()
        if tool_names:
            all_tools = [t for t in all_tools if t.name in tool_names]
        return [t.to_openai_schema() for t in all_tools]
