"""
Action Handler — Playwright-Based Action Execution (Skyvern-Style)

Replaces the old content_script.js executeAction() function.
Instead of relaying click/type/scroll commands over WebSocket to a
content script, we execute them directly via Playwright's API.

Key advantages over the old content script approach:
- page.click() auto-scrolls, waits for element, handles overlays
- page.fill() works with React/Angular (uses native input events)
- page.goto() waits for network idle — no guessing with timeouts
- No content script death on navigation
- Built-in retry and error handling

Each action function:
1. Resolves the element ref (B0, I2, L5) to a Playwright selector
2. Executes the action via Playwright API
3. Returns a result dict with success/error
"""

import asyncio
import logging
from typing import Optional

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

logger = logging.getLogger("browser-agent.action-handler")


# ─────────────────────────────────────────────
# Ref → Playwright Selector Resolver
# ─────────────────────────────────────────────

def ref_to_selector(ref: str) -> str:
    """
    Convert an element ref (B0, I3, L12) to a Playwright CSS selector.

    The scraper stamps elements with [data-agent-ref="B0"], so we can
    target them directly. If the ref looks like a CSS selector already
    (contains . # [ >), we pass it through unchanged.
    """
    ref = ref.strip()

    # Already a CSS selector?
    if any(c in ref for c in ".#[>:"):
        return ref

    # Our ref system
    return f'[data-agent-ref="{ref}"]'


# ─────────────────────────────────────────────
# Action Functions
# ─────────────────────────────────────────────

async def click(page: Page, selector: str) -> dict:
    """
    Click an element on the page.

    Uses Playwright's page.click() which automatically:
    - Waits for the element to be visible
    - Scrolls it into view
    - Waits for it to be stable (no animations)
    - Handles overlay/intercept detection
    - Retries if the element is temporarily detached

    Args:
        page: Playwright Page object.
        selector: Element ref (e.g. "B0") or CSS selector.

    Returns:
        dict with success status.
    """
    css = ref_to_selector(selector)
    logger.info(f"🖱️ Clicking: {selector} → {css}")

    try:
        # Check if element exists first
        element = await page.query_selector(css)
        if not element:
            return {"success": False, "error": f"Element not found: {selector}"}

        # If it's a link with target="_blank", remove it
        tag = await element.evaluate("el => el.tagName")
        if tag == "A":
            target = await element.evaluate("el => el.getAttribute('target')")
            if target == "_blank":
                await element.evaluate("el => el.removeAttribute('target')")
                logger.info("ℹ️ Removed target=_blank to keep navigation in same tab")

        # Perform the click with Playwright's built-in waits
        await page.click(css, timeout=8000)

        # Small delay for any post-click animations/transitions
        await asyncio.sleep(0.5)

        logger.info(f"✅ Clicked: {selector}")
        return {"success": True, "action": "click", "selector": selector}

    except PlaywrightTimeout:
        # Fallback: force click (bypasses visibility/intercept checks)
        try:
            logger.warning(f"⚠️ Standard click timed out, trying force click: {selector}")
            await page.click(css, force=True, timeout=5000)
            await asyncio.sleep(0.5)
            return {"success": True, "action": "click", "selector": selector, "forced": True}
        except Exception as e2:
            return {"success": False, "error": f"Click failed (even force): {e2}"}

    except Exception as e:
        return {"success": False, "error": f"Click error: {str(e)}"}


async def type_text(page: Page, selector: str, value: str, clear_first: bool = True) -> dict:
    """
    Type text into an input field.

    Uses Playwright's page.fill() which:
    - Focuses the element
    - Clears existing value
    - Sets the value using native input events (React/Angular compatible!)
    - Fires input, change, and blur events automatically

    Falls back to page.type() (character-by-character) for stubborn elements.

    Args:
        page: Playwright Page object.
        selector: Element ref (e.g. "I0") or CSS selector.
        value: Text to type.
        clear_first: Whether to clear the field first.

    Returns:
        dict with success status.
    """
    css = ref_to_selector(selector)
    logger.info(f"⌨️ Typing into {selector}: \"{value[:30]}...\"")

    try:
        element = await page.query_selector(css)
        if not element:
            return {"success": False, "error": f"Element not found: {selector}"}

        # Method 1: page.fill() — cleanest, works with most frameworks
        try:
            if clear_first:
                await page.fill(css, "", timeout=3000)
            await page.fill(css, value, timeout=5000)
            logger.info(f"✅ Typed via fill(): {selector}")
            return {"success": True, "action": "type", "selector": selector, "value": value}
        except Exception as fill_err:
            logger.warning(f"⚠️ fill() failed ({fill_err}), trying type()...")

        # Method 2: page.type() — character-by-character, fires keyboard events
        try:
            await page.click(css, timeout=3000)  # focus the element
            if clear_first:
                await page.keyboard.press("Control+a")
                await page.keyboard.press("Backspace")
            await page.type(css, value, delay=30, timeout=10000)
            logger.info(f"✅ Typed via type(): {selector}")
            return {"success": True, "action": "type", "selector": selector, "value": value, "method": "type"}
        except Exception as type_err:
            return {"success": False, "error": f"Type failed (both fill and type): {type_err}"}

    except Exception as e:
        return {"success": False, "error": f"Type error: {str(e)}"}


async def select_option(page: Page, selector: str, value: str) -> dict:
    """
    Select an option from a <select> dropdown.

    Playwright's select_option() handles both value and label matching.

    Args:
        page: Playwright Page object.
        selector: Element ref (e.g. "S0") or CSS selector.
        value: The option value or visible text to select.

    Returns:
        dict with success status.
    """
    css = ref_to_selector(selector)
    logger.info(f"📋 Selecting '{value}' from {selector}")

    try:
        element = await page.query_selector(css)
        if not element:
            return {"success": False, "error": f"Element not found: {selector}"}

        # Try selecting by value first, then by label
        try:
            await page.select_option(css, value=value, timeout=5000)
        except Exception:
            await page.select_option(css, label=value, timeout=5000)

        logger.info(f"✅ Selected: {value}")
        return {"success": True, "action": "select", "selector": selector, "selected": value}

    except Exception as e:
        return {"success": False, "error": f"Select error: {str(e)}"}


async def scroll(page: Page, direction: str = "down", amount: int = 500) -> dict:
    """
    Scroll the page in a given direction.

    Args:
        page: Playwright Page object.
        direction: "up", "down", "left", "right"
        amount: Pixels to scroll.

    Returns:
        dict with success status.
    """
    logger.info(f"📜 Scrolling {direction} by {amount}px")

    scroll_map = {
        "down":  f"window.scrollBy(0, {amount})",
        "up":    f"window.scrollBy(0, -{amount})",
        "right": f"window.scrollBy({amount}, 0)",
        "left":  f"window.scrollBy(-{amount}, 0)",
    }

    js = scroll_map.get(direction, scroll_map["down"])

    try:
        await page.evaluate(js)
        await asyncio.sleep(0.3)  # let scroll animation settle
        return {"success": True, "action": "scroll", "direction": direction, "amount": amount}
    except Exception as e:
        return {"success": False, "error": f"Scroll error: {str(e)}"}


async def navigate(page: Page, url: str) -> dict:
    """
    Navigate to a URL and wait for the page to fully load.

    Uses Playwright's network-idle detection — reliably waits
    until the page stops making requests (no more fixed timeouts).

    Args:
        page: Playwright Page object.
        url: URL to navigate to.

    Returns:
        dict with success status, final URL, and title.
    """
    logger.info(f"🌐 Navigating to: {url}")

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # Wait for network to settle
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except PlaywrightTimeout:
            logger.warning("⚠️ Network idle timeout — page may still be loading")

        final_url = page.url
        title = await page.title()
        logger.info(f"✅ Navigated to: {title} ({final_url})")
        return {"success": True, "action": "navigate", "url": final_url, "title": title}

    except Exception as e:
        return {"success": False, "error": f"Navigation error: {str(e)}"}


async def extract_text(page: Page, selector: str) -> dict:
    """
    Extract text content from an element.

    Args:
        page: Playwright Page object.
        selector: Element ref (e.g. "B0") or CSS selector.

    Returns:
        dict with success status and extracted text.
    """
    css = ref_to_selector(selector)
    logger.info(f"📋 Extracting text from: {selector}")

    try:
        element = await page.query_selector(css)
        if not element:
            return {"success": False, "error": f"Element not found: {selector}"}

        text = await element.text_content()
        inner_html = await element.inner_html()

        return {
            "success": True,
            "action": "extract",
            "selector": selector,
            "text": (text or "").strip()[:2000],
            "html": (inner_html or "")[:2000],
        }
    except Exception as e:
        return {"success": False, "error": f"Extract error: {str(e)}"}


async def wait_for(page: Page, selector: str, timeout_ms: int = 5000) -> dict:
    """
    Wait for an element to appear on the page.

    Args:
        page: Playwright Page object.
        selector: Element ref or CSS selector to wait for.
        timeout_ms: Maximum wait time in milliseconds.

    Returns:
        dict with success status.
    """
    css = ref_to_selector(selector)
    logger.info(f"⏳ Waiting for: {selector} (timeout: {timeout_ms}ms)")

    try:
        await page.wait_for_selector(css, timeout=timeout_ms)
        return {"success": True, "action": "wait_for", "selector": selector}
    except PlaywrightTimeout:
        return {"success": False, "error": f"Timeout waiting for: {selector}"}
    except Exception as e:
        return {"success": False, "error": f"Wait error: {str(e)}"}


# ─────────────────────────────────────────────
# Dispatcher
# ─────────────────────────────────────────────

async def execute_action(page: Page, tool: str, args: dict) -> dict:
    """
    Execute a browser action by tool name.

    This is the single entry point used by the orchestrator.

    Args:
        page: Playwright Page object.
        tool: Tool name ("click", "type", "scroll", etc.)
        args: Tool arguments dict.

    Returns:
        dict with success status and details.
    """
    handlers = {
        "click":        lambda: click(page, args.get("selector", "")),
        "type":         lambda: type_text(page, args.get("selector", ""), args.get("value", ""), args.get("clear_first", True)),
        "select":       lambda: select_option(page, args.get("selector", ""), args.get("value", "")),
        "scroll":       lambda: scroll(page, args.get("direction", "down"), args.get("amount", 500)),
        "navigate":     lambda: navigate(page, args.get("url", "")),
        "extract":      lambda: extract_text(page, args.get("selector", "")),
        "wait_for":     lambda: wait_for(page, args.get("selector", ""), args.get("timeout_ms", 5000)),
    }

    handler = handlers.get(tool)
    if not handler:
        return {"success": False, "error": f"Unknown action: {tool}"}

    return await handler()
