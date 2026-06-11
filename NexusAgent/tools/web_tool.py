"""Web tool — search the web and extract page content as markdown.

Uses ``httpx`` for HTTP requests, ``BeautifulSoup`` for HTML parsing,
``readability-lxml`` for article extraction, and ``html2text`` for
markdown conversion.
"""

from __future__ import annotations

import asyncio
import logging
import re
import urllib.parse
from typing import Any, Optional

from .registry import ToolRegistry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy imports (these may not be installed at bootstrap time)
# ---------------------------------------------------------------------------
_httpx: Any = None
_bs4: Any = None
_html2text: Any = None
_readability: Any = None


def _ensure_deps() -> None:
    """Import heavy dependencies on first use."""
    global _httpx, _bs4, _html2text, _readability
    if _httpx is None:
        import httpx as _h
        _httpx = _h
    if _bs4 is None:
        from bs4 import BeautifulSoup as _bs
        _bs4 = _bs
    if _html2text is None:
        import html2text as _ht
        _html2text = _ht
    if _readability is None:
        from readability import Document as _Doc
        _readability = _Doc


# ---------------------------------------------------------------------------
# DuckDuckGo search
# ---------------------------------------------------------------------------
_DDG_URL = "https://html.duckduckgo.com/html/"
_DDG_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


async def _search_duckduckgo(query: str, limit: int = 5) -> list[dict[str, str]]:
    """Scrape DuckDuckGo HTML results."""
    _ensure_deps()
    async with _httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
        resp = await client.post(
            _DDG_URL,
            data={"q": query, "b": ""},
            headers=_DDG_HEADERS,
        )
        resp.raise_for_status()

    soup = _bs4(resp.text, "html.parser")
    results: list[dict[str, str]] = []

    for result in soup.select(".result"):
        title_tag = result.select_one(".result__a")
        snippet_tag = result.select_one(".result__snippet")
        if not title_tag:
            continue

        href = title_tag.get("href", "")
        # DuckDuckGo wraps URLs in a redirect; extract the real URL
        if "uddg=" in href:
            parsed = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
            href = parsed.get("uddg", [href])[0]

        results.append({
            "title": title_tag.get_text(strip=True),
            "url": href,
            "snippet": snippet_tag.get_text(strip=True) if snippet_tag else "",
        })
        if len(results) >= limit:
            break

    return results


# ---------------------------------------------------------------------------
# Generic search dispatcher
# ---------------------------------------------------------------------------
async def web_search(query: str, engine: str = "duckduckgo", limit: int = 5) -> dict[str, Any]:
    """Search the web and return structured results.

    Currently supports ``duckduckgo``.  Extensible via the *engine* arg.
    """
    try:
        if engine == "duckduckgo":
            results = await _search_duckduckgo(query, limit=limit)
        else:
            return {"error": f"Unsupported search engine: {engine}"}
        return {"results": results, "engine": engine, "query": query}
    except Exception as exc:
        logger.exception("web_search failed")
        return {"error": str(exc), "engine": engine, "query": query}


# ---------------------------------------------------------------------------
# Web content extraction
# ---------------------------------------------------------------------------
async def web_extract(urls: str | list[str], timeout: int = 15) -> dict[str, Any]:
    """Fetch one or more URLs and extract readable article content as markdown.

    Returns ``{url: markdown}`` mapping.
    """
    _ensure_deps()

    if isinstance(urls, str):
        urls = [urls]

    md_converter = _html2text.HTML2Text()
    md_converter.ignore_links = False
    md_converter.ignore_images = True
    md_converter.body_width = 0  # no wrapping

    results: dict[str, Any] = {}

    async with _httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        for url in urls:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                html = resp.text

                # Use readability to extract main content
                doc = _readability(html, url=url)
                article_html = doc.summary()
                title = doc.title()

                markdown = md_converter.handle(article_html).strip()

                results[url] = {
                    "title": title,
                    "content": markdown[:20_000],  # cap for very long pages
                }
            except Exception as exc:
                results[url] = {"error": str(exc)}

    return {"pages": results}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
def _register(registry: ToolRegistry) -> None:
    @registry.register(
        name="web_search",
        description="Search the web using DuckDuckGo. Returns title, URL, and snippet for each result.",
        parameters={
            "query": {"type": "string", "description": "Search query"},
            "engine": {"type": "string", "description": "Search engine (default: duckduckgo)"},
            "limit": {"type": "integer", "description": "Max results (default 5)"},
        },
        required=["query"],
        category="web",
    )
    async def _search(query: str, engine: str = "duckduckgo", limit: int = 5) -> dict:
        return await web_search(query, engine=engine, limit=limit)

    @registry.register(
        name="web_extract",
        description="Fetch URLs and extract readable article content as markdown.",
        parameters={
            "urls": {
                "oneOf": [
                    {"type": "string", "description": "Single URL"},
                    {"type": "array", "items": {"type": "string"}, "description": "List of URLs"},
                ],
                "description": "URL(s) to extract content from",
            },
            "timeout": {"type": "integer", "description": "Request timeout in seconds"},
        },
        required=["urls"],
        category="web",
    )
    async def _extract(urls: str | list[str], timeout: int = 15) -> dict:
        return await web_extract(urls, timeout=timeout)


try:
    _register(ToolRegistry())
except Exception:
    pass
