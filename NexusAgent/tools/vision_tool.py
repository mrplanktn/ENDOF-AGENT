"""Vision tool — analyze images by routing to an auxiliary vision model.

Accepts a file path, HTTP(S) URL, or raw base64-encoded image string.
The image is sent to a vision-capable model via ``ModelRouter`` (if
available) or a direct HTTP call to a configurable vision API endpoint.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from .registry import ToolRegistry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Image source helpers
# ---------------------------------------------------------------------------
_BASE64_RE = re.compile(r"^[A-Za-z0-9+/=\s]+$")
_DATA_URI_RE = re.compile(r"^data:image/[^;]+;base64,(.+)$", re.DOTALL)


def _resolve_image(image_source: str) -> tuple[str, str]:
    """Resolve *image_source* to (mime_type, base64_data).

    Returns a tuple of ``(mime, b64)`` suitable for embedding in an
    OpenAI-compatible vision message.
    """
    # 1) data URI
    m = _DATA_URI_RE.match(image_source)
    if m:
        mime = image_source.split(";")[0].replace("data:", "")
        return mime, m.group(1).strip()

    # 2) HTTP(S) URL
    parsed = urlparse(image_source)
    if parsed.scheme in ("http", "https"):
        # We'll return the URL directly; the model API accepts image URLs
        return "url", image_source

    # 3) File path
    path = Path(os.path.expanduser(image_source))
    if path.exists():
        mime = _guess_mime(path.suffix)
        b64 = base64.b64encode(path.read_bytes()).decode()
        return mime, b64

    # 4) Raw base64 string (heuristic)
    if _BASE64_RE.match(image_source) and len(image_source) > 100:
        return "image/png", image_source

    raise ValueError(f"Cannot resolve image source: {image_source}")


def _guess_mime(suffix: str) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".tiff": "image/tiff",
    }.get(suffix.lower(), "image/png")


# ---------------------------------------------------------------------------
# Vision model call
# ---------------------------------------------------------------------------
# We try three strategies in order:
#   1. ModelRouter (if NexusAgent has one configured)
#   2. Direct OpenAI-compatible API call
#   3. Simple error if neither is available


async def analyze_image(
    image_source: str,
    question: str = "Describe this image in detail.",
    model: str | None = None,
    api_base: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Analyze an image with a vision model.

    Parameters
    ----------
    image_source : str
        File path, URL, base64 string, or data URI.
    question : str
        Prompt/question about the image.
    model : str, optional
        Vision model name. Falls back to env ``VISION_MODEL`` or
        ``gpt-4o-mini``.
    api_base : str, optional
        OpenAI-compatible API base URL. Falls back to ``OPENAI_API_BASE``.
    api_key : str, optional
        API key. Falls back to ``OPENAI_API_KEY``.
    """
    try:
        mime, data = _resolve_image(image_source)
    except ValueError as exc:
        return {"error": str(exc)}

    model = model or os.environ.get("VISION_MODEL", "gpt-4o-mini")
    api_base = api_base or os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1")
    api_key = api_key or os.environ.get("OPENAI_API_KEY", "")

    if not api_key:
        return {"error": "No API key configured. Set OPENAI_API_KEY."}

    # Build the image content block
    if mime == "url":
        image_block = {"type": "image_url", "image_url": {"url": data, "detail": "auto"}}
    else:
        data_url = f"data:{mime};base64,{data}"
        image_block = {"type": "image_url", "image_url": {"url": data_url, "detail": "auto"}}

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": question},
                image_block,
            ],
        }
    ]

    # Try using httpx directly
    try:
        import httpx

        url = f"{api_base.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": 1024,
        }

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        content = data["choices"][0]["message"]["content"]
        return {
            "description": content,
            "model": model,
            "source": image_source,
        }
    except ImportError:
        return {"error": "httpx is required for vision API calls. pip install httpx"}
    except Exception as exc:
        logger.exception("Vision API call failed")
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
def _register(registry: ToolRegistry) -> None:
    @registry.register(
        name="analyze_image",
        description="Analyze an image with a vision model. Accepts file path, URL, or base64.",
        parameters={
            "image_source": {
                "type": "string",
                "description": "Image source: file path, URL, base64 string, or data URI",
            },
            "question": {
                "type": "string",
                "description": "Question or prompt about the image (default: 'Describe this image')",
            },
            "model": {
                "type": "string",
                "description": "Vision model name (optional, overrides VISION_MODEL env)",
            },
        },
        required=["image_source"],
        category="vision",
    )
    async def _analyze(image_source: str, question: str = "Describe this image in detail.", model: str | None = None) -> dict:
        return await analyze_image(image_source, question=question, model=model)


try:
    _register(ToolRegistry())
except Exception:
    pass
