"""Browser tool — headless browser automation via Playwright.

Provides a ``BrowserController`` class and exposes its actions as
registered tools for the agent.  Manages a single persistent browser
context per controller instance.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from typing import Any, Optional
from pathlib import Path

from .registry import ToolRegistry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# BrowserController
# ---------------------------------------------------------------------------
class BrowserController:
    """Headless Chromium browser controller using Playwright async API.

    Usage::

        bc = BrowserController()
        await bc.start()
        result = await bc.navigate("https://example.com")
        text = await bc.get_text()
        await bc.stop()
    """

    def __init__(self, headless: bool = True, screenshot_dir: str = "/tmp/nexus_browser"):
        self.headless = headless
        self.screenshot_dir = Path(screenshot_dir)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None

    async def start(self) -> dict[str, Any]:
        """Launch headless Chromium."""
        if self._browser is not None:
            return {"status": "already_running"}

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return {"error": "playwright is not installed. Run: pip install playwright && playwright install chromium"}

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        self._page = await self._context.new_page()
        logger.info("Browser started (headless=%s)", self.headless)
        return {"status": "started"}

    async def stop(self) -> dict[str, Any]:
        """Close browser and clean up."""
        if self._browser:
            await self._browser.close()
            self._browser = None
            self._context = None
            self._page = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        return {"status": "stopped"}

    def _require_page(self) -> Any:
        if self._page is None:
            raise RuntimeError("Browser not started. Call start() first.")
        return self._page

    # ---- actions ---------------------------------------------------------
    async def navigate(self, url: str) -> dict[str, Any]:
        """Navigate to *url* and return status info."""
        page = self._require_page()
        try:
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            status = resp.status if resp else None
            return {
                "url": page.url,
                "status": status,
                "title": await page.title(),
            }
        except Exception as exc:
            return {"error": str(exc), "url": url}

    async def click(self, selector: str) -> dict[str, Any]:
        """Click an element matching *selector*."""
        page = self._require_page()
        try:
            await page.click(selector, timeout=10_000)
            return {"clicked": selector, "url": page.url}
        except Exception as exc:
            return {"error": str(exc), "selector": selector}

    async def type_text(self, selector: str, text: str) -> dict[str, Any]:
        """Type *text* into the element matching *selector*."""
        page = self._require_page()
        try:
            await page.fill(selector, text, timeout=10_000)
            return {"typed": True, "selector": selector, "length": len(text)}
        except Exception as exc:
            return {"error": str(exc), "selector": selector}

    async def screenshot(self, name: str = "screenshot") -> dict[str, Any]:
        """Take a screenshot and return the file path + base64."""
        page = self._require_page()
        path = self.screenshot_dir / f"{name}.png"
        await page.screenshot(path=str(path), full_page=False)
        b64 = base64.b64encode(path.read_bytes()).decode()
        return {"path": str(path), "base64": b64[:100] + "...", "size_bytes": path.stat().st_size}

    async def get_text(self, selector: str = "body") -> dict[str, Any]:
        """Extract visible text from the page (or a specific element)."""
        page = self._require_page()
        try:
            element = page.locator(selector)
            text = await element.inner_text(timeout=10_000)
            # Truncate very long pages
            return {"text": text[:50_000], "length": len(text), "selector": selector}
        except Exception as exc:
            return {"error": str(exc), "selector": selector}

    async def get_html(self, selector: str = "body") -> dict[str, Any]:
        """Get inner HTML of the page or a specific element."""
        page = self._require_page()
        try:
            element = page.locator(selector)
            html = await element.inner_html(timeout=10_000)
            return {"html": html[:100_000], "selector": selector}
        except Exception as exc:
            return {"error": str(exc), "selector": selector}

    async def scroll(self, direction: str = "down", amount: int = 500) -> dict[str, Any]:
        """Scroll the page."""
        page = self._require_page()
        delta = amount if direction == "down" else -amount
        await page.mouse.wheel(0, delta)
        return {"scrolled": direction, "amount": amount, "url": page.url}

    async def wait_for(self, selector: str, timeout: int = 10_000) -> dict[str, Any]:
        """Wait for an element to appear."""
        page = self._require_page()
        try:
            await page.wait_for_selector(selector, timeout=timeout)
            return {"found": True, "selector": selector}
        except Exception as exc:
            return {"error": str(exc), "selector": selector}


# ---------------------------------------------------------------------------
# Singleton instance used by registered tools
# ---------------------------------------------------------------------------
_controller: Optional[BrowserController] = None


async def _get_controller() -> BrowserController:
    global _controller
    if _controller is None:
        _controller = BrowserController()
        await _controller.start()
    return _controller


# ---------------------------------------------------------------------------
# Tool wrappers
# ---------------------------------------------------------------------------
async def browser_navigate(url: str) -> dict[str, Any]:
    """Navigate to a URL."""
    ctrl = await _get_controller()
    return await ctrl.navigate(url)


async def browser_click(selector: str) -> dict[str, Any]:
    """Click an element by CSS selector."""
    ctrl = await _get_controller()
    return await ctrl.click(selector)


async def browser_type(selector: str, text: str) -> dict[str, Any]:
    """Type text into an input element."""
    ctrl = await _get_controller()
    return await ctrl.type_text(selector, text)


async def browser_screenshot(name: str = "screenshot") -> dict[str, Any]:
    """Take a screenshot of the current page."""
    ctrl = await _get_controller()
    return await ctrl.screenshot(name)


async def browser_get_text(selector: str = "body") -> dict[str, Any]:
    """Extract visible text from the page."""
    ctrl = await _get_controller()
    return await ctrl.get_text(selector)


async def browser_close() -> dict[str, Any]:
    """Close the browser and free resources."""
    global _controller
    if _controller:
        result = await _controller.stop()
        _controller = None
        return result
    return {"status": "no_browser_running"}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
def _register(registry: ToolRegistry) -> None:
    @registry.register(
        name="browser_navigate",
        description="Open a URL in the headless browser. Auto-starts browser if needed.",
        parameters={
            "url": {"type": "string", "description": "URL to navigate to"},
        },
        required=["url"],
        category="browser",
    )
    async def _nav(url: str) -> dict:
        return await browser_navigate(url)

    @registry.register(
        name="browser_click",
        description="Click an element on the current page by CSS selector.",
        parameters={
            "selector": {"type": "string", "description": "CSS selector of the element to click"},
        },
        required=["selector"],
        category="browser",
    )
    async def _click(selector: str) -> dict:
        return await browser_click(selector)

    @registry.register(
        name="browser_type",
        description="Type text into an input element by CSS selector.",
        parameters={
            "selector": {"type": "string", "description": "CSS selector of the input"},
            "text": {"type": "string", "description": "Text to type"},
        },
        required=["selector", "text"],
        category="browser",
    )
    async def _type(selector: str, text: str) -> dict:
        return await browser_type(selector, text)

    @registry.register(
        name="browser_screenshot",
        description="Take a screenshot of the current browser page.",
        parameters={
            "name": {"type": "string", "description": "Filename for the screenshot"},
        },
        required=[],
        category="browser",
    )
    async def _screenshot(name: str = "screenshot") -> dict:
        return await browser_screenshot(name)

    @registry.register(
        name="browser_get_text",
        description="Extract visible text from the current browser page.",
        parameters={
            "selector": {"type": "string", "description": "CSS selector (default: body)"},
        },
        required=[],
        category="browser",
    )
    async def _get_text(selector: str = "body") -> dict:
        return await browser_get_text(selector)

    @registry.register(
        name="browser_close",
        description="Close the headless browser and free resources.",
        parameters={},
        required=[],
        category="browser",
    )
    async def _close() -> dict:
        return await browser_close()


try:
    _register(ToolRegistry())
except Exception:
    pass
