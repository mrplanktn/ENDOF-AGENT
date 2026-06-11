"""Multi-provider LLM routing with failover and credential pooling."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator

import httpx

logger = logging.getLogger(__name__)


class Provider(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    CUSTOM = "custom"


@dataclass
class Credential:
    """A single API credential."""
    api_key: str
    base_url: str | None = None


@dataclass
class ProviderConfig:
    """Configuration for a provider with one or more credentials."""
    provider: Provider
    model: str
    credentials: list[Credential]
    base_url: str | None = None
    priority: int = 0  # lower = preferred
    _cred_index: int = field(default=0, init=False, repr=False)

    def next_credential(self) -> Credential:
        """Round-robin credential rotation."""
        cred = self.credentials[self._cred_index % len(self.credentials)]
        self._cred_index += 1
        return cred


def estimate_tokens(text: str) -> int:
    """Rough token estimation: ~4 chars per token."""
    return max(1, len(text) // 4)


class ModelRouter:
    """Routes LLM calls across multiple providers with failover."""

    def __init__(
        self,
        providers: list[ProviderConfig],
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
    ) -> None:
        self._providers = sorted(providers, key=lambda p: p.priority)
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(120.0))
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ── Public API ──────────────────────────────────────────────

    async def call(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any] | AsyncIterator[str]:
        """Call an LLM, auto-failing over across providers."""
        errors: list[str] = []

        for provider_cfg in self._providers:
            if provider_cfg.model != model:
                continue
            for attempt in range(self._max_retries):
                try:
                    return await self._dispatch(provider_cfg, messages, tools, stream, **kwargs)
                except Exception as exc:
                    err_msg = f"[{provider_cfg.provider.value}] attempt {attempt+1}: {exc}"
                    logger.warning(err_msg)
                    errors.append(err_msg)
                    if attempt < self._max_retries - 1:
                        delay = self._retry_base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                        await asyncio.sleep(delay)

        # Try custom endpoints / fallback with any provider
        for provider_cfg in self._providers:
            if provider_cfg.model == model:
                continue  # already tried
            # Only try if model string looks compatible (loose matching)
            for attempt in range(self._max_retries):
                try:
                    return await self._dispatch(provider_cfg, messages, tools, stream, **kwargs)
                except Exception as exc:
                    errors.append(f"[{provider_cfg.provider.value}] fallback attempt {attempt+1}: {exc}")
                    if attempt < self._max_retries - 1:
                        delay = self._retry_base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                        await asyncio.sleep(delay)

        raise RuntimeError(f"All providers failed for model '{model}':\n" + "\n".join(errors))

    # ── Dispatch per provider ───────────────────────────────────

    async def _dispatch(
        self,
        cfg: ProviderConfig,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        stream: bool,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if cfg.provider == Provider.OPENAI or cfg.provider == Provider.CUSTOM:
            return await self._call_openai_compatible(cfg, messages, tools, stream, **kwargs)
        elif cfg.provider == Provider.ANTHROPIC:
            return await self._call_anthropic(cfg, messages, tools, stream, **kwargs)
        elif cfg.provider == Provider.GEMINI:
            return await self._call_gemini(cfg, messages, tools, stream, **kwargs)
        else:
            raise ValueError(f"Unknown provider: {cfg.provider}")

    # ── OpenAI-compatible ───────────────────────────────────────

    async def _call_openai_compatible(
        self,
        cfg: ProviderConfig,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        stream: bool,
        **kwargs: Any,
    ) -> dict[str, Any]:
        cred = cfg.next_credential()
        base = cred.base_url or cfg.base_url or "https://api.openai.com/v1"
        url = f"{base.rstrip('/')}/chat/completions"

        body: dict[str, Any] = {"model": cfg.model, "messages": messages, "stream": stream}
        if tools:
            body["tools"] = tools
        body.update(kwargs)

        client = await self._get_client()
        resp = await client.post(
            url,
            json=body,
            headers={"Authorization": f"Bearer {cred.api_key}", "Content-Type": "application/json"},
        )
        resp.raise_for_status()

        if stream:
            return self._stream_openai(resp)

        data = resp.json()
        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})
        result: dict[str, Any] = {
            "role": "assistant",
            "content": message.get("content"),
        }
        if message.get("tool_calls"):
            result["tool_calls"] = message["tool_calls"]
        result["usage"] = data.get("usage", {})
        return result

    async def _stream_openai(self, resp: httpx.Response) -> AsyncIterator[str]:
        async for line in resp.aiter_lines():
            if not line.startswith("data: "):
                continue
            payload = line[6:]
            if payload.strip() == "[DONE]":
                break
            try:
                chunk = json.loads(payload)
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                if delta.get("content"):
                    yield delta["content"]
            except json.JSONDecodeError:
                continue

    # ── Anthropic ───────────────────────────────────────────────

    async def _call_anthropic(
        self,
        cfg: ProviderConfig,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        stream: bool,
        **kwargs: Any,
    ) -> dict[str, Any]:
        cred = cfg.next_credential()
        base = cred.base_url or cfg.base_url or "https://api.anthropic.com"
        url = f"{base.rstrip('/')}/v1/messages"

        # Extract system message
        system_text = ""
        api_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_text += msg.get("content", "") + "\n"
            else:
                api_messages.append(msg)

        body: dict[str, Any] = {
            "model": cfg.model,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "messages": api_messages,
        }
        if system_text.strip():
            body["system"] = system_text.strip()
        if tools:
            anthropic_tools = []
            for t in tools:
                if "function" in t:
                    fn = t["function"]
                    anthropic_tools.append({"name": fn["name"], "description": fn["description"], "input_schema": fn.get("parameters", {})})
                else:
                    anthropic_tools.append(t)
            body["tools"] = anthropic_tools

        client = await self._get_client()
        resp = await client.post(
            url,
            json=body,
            headers={
                "x-api-key": cred.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        data = resp.json()

        result: dict[str, Any] = {"role": "assistant", "content": "", "tool_calls": []}
        for block in data.get("content", []):
            if block.get("type") == "text":
                result["content"] += block["text"]
            elif block.get("type") == "tool_use":
                result["tool_calls"].append({
                    "id": block["id"],
                    "type": "function",
                    "function": {"name": block["name"], "arguments": json.dumps(block["input"])},
                })
        if not result["tool_calls"]:
            result.pop("tool_calls", None)
        result["usage"] = data.get("usage", {})
        return result

    # ── Google Gemini ───────────────────────────────────────────

    async def _call_gemini(
        self,
        cfg: ProviderConfig,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        stream: bool,
        **kwargs: Any,
    ) -> dict[str, Any]:
        cred = cfg.next_credential()
        base = cred.base_url or cfg.base_url or "https://generativelanguage.googleapis.com/v1beta"
        endpoint = "streamGenerateContent" if stream else "generateContent"
        url = f"{base.rstrip('/')}/models/{cfg.model}:{endpoint}?key={cred.api_key}"

        # Convert messages to Gemini format
        contents = []
        for msg in messages:
            role = "user" if msg["role"] in ("user", "system") else "model"
            contents.append({"role": role, "parts": [{"text": msg.get("content", "")}]})

        body: dict[str, Any] = {"contents": contents}
        if tools:
            gemini_tools = []
            for t in tools:
                fn = t.get("function", t)
                gemini_tools.append({
                    "name": fn["name"],
                    "description": fn.get("description", ""),
                    "parameters": fn.get("parameters", {}),
                })
            body["tools"] = [{"functionDeclarations": gemini_tools}]

        client = await self._get_client()
        resp = await client.post(url, json=body, headers={"Content-Type": "application/json"})
        resp.raise_for_status()
        data = resp.json()

        # Parse Gemini response
        candidates = data.get("candidates", [{}])
        parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
        result: dict[str, Any] = {"role": "assistant", "content": "", "tool_calls": []}
        for part in parts:
            if "text" in part:
                result["content"] += part["text"]
            elif "functionCall" in part:
                fc = part["functionCall"]
                result["tool_calls"].append({
                    "id": f"call_{fc.get('name', 'unknown')}_{id(fc)}",
                    "type": "function",
                    "function": {"name": fc["name"], "arguments": json.dumps(fc.get("args", {}))},
                })
        if not result["tool_calls"]:
            result.pop("tool_calls", None)
        result["usage"] = data.get("usageMetadata", {})
        return result
