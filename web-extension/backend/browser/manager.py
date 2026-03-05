"""
Browser Manager — Playwright-Based Browser Control (Skyvern-Style)

This module manages the lifecycle of a Playwright browser instance.
It supports two modes of operation:

1. HEADLESS MODE — Launches a new invisible Chromium browser.
   Best for: API calls, background automation, production.
   Usage: await manager.launch_headless()

2. CDP MODE — Connects to an already-running Chrome browser via
   Chrome DevTools Protocol (Remote Debugging).
   Best for: Extension use, debugging, visual feedback.
   Usage: await manager.connect_cdp("http://localhost:9222")

The manager provides a single `get_page()` method that returns
the active Playwright Page object for scraping and action execution.
"""

import asyncio
import logging
import os
import platform
import subprocess
from dataclasses import dataclass, field
from typing import Optional

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    Playwright,
)

logger = logging.getLogger("browser-agent.browser-manager")


def _detect_wsl_host_ip() -> str | None:
    """
    If running inside WSL, detect the Windows host IP from /etc/resolv.conf.
    Returns the IP string (e.g. '172.28.80.1') or None if not in WSL.
    """
    # Quick check: are we on Linux?
    if platform.system() != "Linux":
        return None

    # Check for WSL indicator
    try:
        with open("/proc/version", "r") as f:
            if "microsoft" not in f.read().lower():
                return None
    except FileNotFoundError:
        return None

    # Read the Windows host IP from resolv.conf
    try:
        with open("/etc/resolv.conf", "r") as f:
            for line in f:
                if line.strip().startswith("nameserver"):
                    ip = line.strip().split()[1]
                    logger.info(f"🔍 Detected WSL environment — Windows host IP: {ip}")
                    return ip
    except Exception as e:
        logger.warning(f"⚠️ Could not read WSL host IP: {e}")

    return None


# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────

@dataclass
class BrowserConfig:
    """Configuration for the browser manager."""

    # Headless mode settings
    headless: bool = True                     # True = invisible, False = visible window
    viewport_width: int = 1280
    viewport_height: int = 900
    slow_mo: int = 0                          # ms delay between actions (for debugging)

    # CDP connection settings
    cdp_endpoint: Optional[str] = None        # e.g. "http://localhost:9222"

    # Timeouts
    navigation_timeout_ms: int = 30_000       # 30s for page loads
    action_timeout_ms: int = 10_000           # 10s for clicks/types
    
    # Browser args
    extra_args: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────
# Browser Manager
# ─────────────────────────────────────────────

class BrowserManager:
    """
    Manages a single Playwright browser instance.

    Lifecycle:
        1. Create:   manager = BrowserManager(config)
        2. Start:    await manager.launch()    OR   await manager.connect_cdp(endpoint)
        3. Use:      page = await manager.get_page()
        4. Cleanup:  await manager.close()

    In a FastAPI app, call launch() in the lifespan startup
    and close() in the lifespan shutdown.
    """

    def __init__(self, config: Optional[BrowserConfig] = None):
        self.config = config or BrowserConfig()
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._mode: str = "none"  # "headless", "cdp", or "none"

    # ─── Properties ───────────────────────────────

    @property
    def is_connected(self) -> bool:
        """Is the browser currently active?"""
        return self._browser is not None and self._browser.is_connected()

    @property
    def mode(self) -> str:
        """Current connection mode: 'headless', 'cdp', or 'none'."""
        return self._mode

    # ─── Launch Modes ─────────────────────────────

    async def launch_headless(self) -> Page:
        """
        Launch a NEW Chromium browser in headless mode.

        This creates a fresh browser that the backend fully controls.
        No existing Chrome needed — Playwright launches its own.

        Returns:
            The active Page object.
        """
        if self.is_connected:
            logger.warning("Browser already connected — closing existing first")
            await self.close()

        logger.info("🚀 Launching headless Chromium browser...")
        self._playwright = await async_playwright().start()

        launch_args = [
            "--disable-blink-features=AutomationControlled",  # avoid bot detection
            "--no-first-run",
            "--no-default-browser-check",
            *self.config.extra_args,
        ]

        self._browser = await self._playwright.chromium.launch(
            headless=self.config.headless,
            slow_mo=self.config.slow_mo,
            args=launch_args,
        )

        self._context = await self._browser.new_context(
            viewport={
                "width": self.config.viewport_width,
                "height": self.config.viewport_height,
            },
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )

        # Set default timeouts
        self._context.set_default_timeout(self.config.action_timeout_ms)
        self._context.set_default_navigation_timeout(self.config.navigation_timeout_ms)

        self._page = await self._context.new_page()
        self._mode = "headless"

        logger.info(
            f"✅ Headless browser launched "
            f"(viewport: {self.config.viewport_width}x{self.config.viewport_height})"
        )
        return self._page

    async def connect_cdp(self, endpoint: Optional[str] = None) -> Page:
        """
        Connect to an already-running Chrome browser via CDP.

        The user must start Chrome with:
            chrome.exe --remote-debugging-port=9222

        This lets the backend control the user's visible browser —
        they can watch every click and type in real time.

        Args:
            endpoint: CDP WebSocket URL, e.g. "http://localhost:9222"
                      Defaults to config.cdp_endpoint.

        Returns:
            The active Page object (the user's current tab).
        """
        if self.is_connected:
            logger.warning("Browser already connected — closing existing first")
            await self.close()

        cdp_url = endpoint or self.config.cdp_endpoint
        if not cdp_url:
            raise ValueError(
                "No CDP endpoint provided. Start Chrome with:\n"
                '  chrome.exe --remote-debugging-port=9222\n'
                "Then pass endpoint='http://localhost:9222'"
            )

        # WSL fix: replace 'localhost' with Windows host IP
        wsl_ip = _detect_wsl_host_ip()
        if wsl_ip and "localhost" in cdp_url:
            cdp_url = cdp_url.replace("localhost", wsl_ip)
            logger.info(f"🔄 WSL detected — rewriting CDP URL to: {cdp_url}")

        logger.info(f"🔌 Connecting to Chrome via CDP: {cdp_url}")
        self._playwright = await async_playwright().start()

        self._browser = await self._playwright.chromium.connect_over_cdp(cdp_url)

        # Get existing contexts (the user's open browser windows)
        contexts = self._browser.contexts
        if contexts:
            self._context = contexts[0]
            pages = self._context.pages
            if pages:
                # Use the last active tab
                self._page = pages[-1]
                logger.info(f"📄 Attached to existing tab: {self._page.url}")
            else:
                self._page = await self._context.new_page()
                logger.info("📄 No tabs found — created a new one")
        else:
            self._context = await self._browser.new_context()
            self._page = await self._context.new_page()
            logger.info("📄 No browser context found — created new context + page")

        # Set timeouts
        self._context.set_default_timeout(self.config.action_timeout_ms)
        self._context.set_default_navigation_timeout(self.config.navigation_timeout_ms)

        self._mode = "cdp"
        logger.info(f"✅ Connected to Chrome via CDP at {cdp_url}")
        return self._page

    # ─── Page Access ──────────────────────────────

    async def get_page(self) -> Page:
        """
        Get the active Playwright Page.

        In CDP mode, this returns the last active tab (refreshes the reference
        in case user switched tabs or a navigation happened).

        Returns:
            Active Playwright Page object.

        Raises:
            RuntimeError if no browser is connected.
        """
        if not self.is_connected:
            raise RuntimeError(
                "No browser connected. Call launch_headless() or connect_cdp() first."
            )

        # In CDP mode, re-check which page is active
        if self._mode == "cdp" and self._context:
            pages = self._context.pages
            if pages:
                self._page = pages[-1]

        if not self._page:
            raise RuntimeError("No active page available.")

        return self._page

    async def navigate(self, url: str) -> dict:
        """
        Navigate the current page to a URL and wait for it to fully load.

        Uses Playwright's built-in network-idle detection — no more
        guessing with fixed timeouts.

        Args:
            url: The URL to navigate to.

        Returns:
            dict with success, url, and title.
        """
        page = await self.get_page()
        logger.info(f"🌐 Navigating to: {url}")

        try:
            response = await page.goto(url, wait_until="domcontentloaded")
            # Wait for network to settle (no requests for 500ms)
            await page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception as e:
            logger.warning(f"⚠️ Navigation partial load: {e}")
            # Even if networkidle times out, domcontentloaded was successful

        final_url = page.url
        title = await page.title()
        logger.info(f"✅ Navigated to: {title} ({final_url})")

        return {
            "success": True,
            "url": final_url,
            "title": title,
        }

    async def take_screenshot(self, full_page: bool = False) -> bytes:
        """
        Capture a screenshot of the current page.

        Args:
            full_page: If True, capture the entire scrollable page.
                       If False (default), capture only the viewport.

        Returns:
            PNG screenshot as bytes.
        """
        page = await self.get_page()
        screenshot = await page.screenshot(full_page=full_page, type="png")
        logger.info(f"📸 Screenshot captured ({len(screenshot)} bytes)")
        return screenshot

    # ─── Cleanup ──────────────────────────────────

    async def close(self):
        """Close the browser and clean up Playwright resources."""
        logger.info(f"🔒 Closing browser (mode: {self._mode})...")

        try:
            if self._mode == "headless":
                # In headless mode, we own the browser — close everything
                if self._context:
                    await self._context.close()
                if self._browser:
                    await self._browser.close()
            elif self._mode == "cdp":
                # In CDP mode, disconnect but DON'T close the user's browser
                if self._browser:
                    self._browser.close()
        except Exception as e:
            logger.warning(f"⚠️ Error during browser cleanup: {e}")

        try:
            if self._playwright:
                await self._playwright.stop()
        except Exception as e:
            logger.warning(f"⚠️ Error stopping Playwright: {e}")

        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        self._mode = "none"

        logger.info("✅ Browser closed and resources cleaned up")

    # ─── Context Manager ──────────────────────────

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


# ─────────────────────────────────────────────
# Module-level singleton
# ─────────────────────────────────────────────

# Shared instance used by the FastAPI app.
# Created in main.py lifespan, accessed by tools/orchestrator.
_manager: Optional[BrowserManager] = None


def get_browser_manager() -> BrowserManager:
    """Get the global BrowserManager instance."""
    global _manager
    if _manager is None:
        _manager = BrowserManager()
    return _manager


def set_browser_manager(manager: BrowserManager):
    """Set the global BrowserManager instance (called during app startup)."""
    global _manager
    _manager = manager
