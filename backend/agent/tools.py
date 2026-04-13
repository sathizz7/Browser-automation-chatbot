"""
Browser Agent — ADK Tool Definitions (Playwright-Powered)

Each function here is an ADK FunctionTool that the agent can call.
Instead of relaying actions via WebSocket to a Chrome Extension,
tools now execute actions directly via Playwright.

Tools:
    - click_element: Click on a page element
    - type_text: Type text into an input field
    - select_option: Select an option from a dropdown
    - scroll_page: Scroll the page
    - navigate_to: Navigate to a URL
    - extract_text: Extract text from an element
    - wait_for_element: Wait for an element to appear
    - get_dom_snapshot: Scrape page DOM + take screenshot
"""

import asyncio
import logging

from browser.manager import get_browser_manager
from browser import action_handler
from browser.scraper import scrape_page, format_elements_for_llm

logger = logging.getLogger("browser-agent.tools")


# ─────────────────────────────────────────────
# WebSocket Manager (kept for status streaming only)
# ─────────────────────────────────────────────

_ws_manager = None
_current_ws_session: str | None = None


def set_ws_manager(manager):
    """Set the WebSocket manager reference (used for status streaming)."""
    global _ws_manager
    _ws_manager = manager


def set_current_ws_session(ws_session_id: str):
    """Set the current WebSocket session (used for status streaming)."""
    global _current_ws_session
    _current_ws_session = ws_session_id


# ─────────────────────────────────────────────
# Helper: Get the Playwright Page
# ─────────────────────────────────────────────

async def _get_page():
    """Get the active Playwright page from the browser manager."""
    manager = get_browser_manager()
    return await manager.get_page()


# ─────────────────────────────────────────────
# ADK Tool Functions (Playwright-Powered)
# ─────────────────────────────────────────────

async def click_element(selector: str) -> dict:
    """Click on a page element identified by its ref (e.g. B0, L3) or CSS selector.

    The page DOM snapshot assigns stable refs to interactive elements:
      B# = buttons, L# = links, I# = inputs, S# = selects.
    Use these refs for maximum reliability.

    Args:
        selector: Element ref like 'B0', 'L3', or a CSS selector.

    Returns:
        dict with success status and details
    """
    logger.info(f"🖱️ click_element: {selector}")
    page = await _get_page()
    return await action_handler.click(page, selector)


async def type_text(selector: str, value: str, clear_first: bool = True) -> dict:
    """Type text into an input field identified by its ref (e.g. I0, I3) or CSS selector.

    Args:
        selector: Element ref like 'I0', 'I3', or a CSS selector.
        value: The text to type into the field
        clear_first: Whether to clear the field before typing (default: True)

    Returns:
        dict with success status and details
    """
    logger.info(f"⌨️ type_text: '{value}' into {selector}")
    page = await _get_page()
    return await action_handler.type_text(page, selector, value, clear_first)


async def select_option(selector: str, value: str) -> dict:
    """Select an option from a dropdown by its ref (e.g. S0, S1).

    Args:
        selector: Element ref like 'S0' or CSS selector.
        value: The option value or visible text to select.

    Returns:
        dict with success status and selected value
    """
    logger.info(f"📋 select_option: '{value}' from {selector}")
    page = await _get_page()
    return await action_handler.select_option(page, selector, value)


async def scroll_page(direction: str = "down", amount: int = 500) -> dict:
    """Scroll the page in a given direction.

    Args:
        direction: Scroll direction - 'up', 'down', 'left', or 'right'
        amount: Number of pixels to scroll (default: 500)

    Returns:
        dict with success status
    """
    logger.info(f"📜 scroll_page: {direction} by {amount}px")
    page = await _get_page()
    return await action_handler.scroll(page, direction, amount)


async def navigate_to(url: str) -> dict:
    """Navigate the browser to a specific URL and wait for the page to fully load.
    After this tool returns, ALWAYS call get_dom_snapshot() to see the new page content.

    Args:
        url: The full URL to navigate to (e.g. 'https://example.com')

    Returns:
        dict with success status, final URL and title of loaded page
    """
    logger.info(f"🌐 navigate_to: {url}")
    page = await _get_page()
    return await action_handler.navigate(page, url)


async def extract_text(selector: str) -> dict:
    """Extract text content from a page element.

    Args:
        selector: Element ref (e.g. 'B0', 'L3') or CSS selector to extract text from

    Returns:
        dict with success status and extracted text
    """
    logger.info(f"📋 extract_text: {selector}")
    page = await _get_page()
    return await action_handler.extract_text(page, selector)


async def wait_for_element(selector: str, timeout_ms: int = 5000) -> dict:
    """Wait for a page element to appear in the DOM.

    Args:
        selector: Element ref (e.g. 'I0', 'B1') or CSS selector to wait for
        timeout_ms: Maximum time to wait in milliseconds (default: 5000)

    Returns:
        dict with success status
    """
    logger.info(f"⏳ wait_for_element: {selector} (timeout: {timeout_ms}ms)")
    page = await _get_page()
    return await action_handler.wait_for(page, selector, timeout_ms)


async def get_dom_snapshot() -> dict:
    """Request a fresh DOM snapshot from the current page.
    Use this to see the current state of the page after performing actions.

    Each interactive element in the snapshot has a stable ref:
      B# = buttons, L# = links, I# = input fields, S# = select dropdowns.
    Use these refs with click_element() and type_text() for reliable interaction.

    Returns:
        dict with page URL, title, headings, pageText, and list of ref-tagged elements
    """
    logger.info("📸 get_dom_snapshot requested")
    page = await _get_page()
    scraped = await scrape_page(page, take_screenshot=False)

    # Return the data in the format expected by the agent
    return {
        "success": True,
        "url": scraped.url,
        "title": scraped.title,
        "element_count": scraped.element_count,
        "elements": [
            {
                "ref": el.ref,
                "tag": el.tag,
                "text": el.text,
                "label": el.label,
                "type": el.type,
                "href": el.href,
                "placeholder": el.placeholder,
                "value": el.value,
                "disabled": el.disabled,
            }
            for el in scraped.elements
        ],
        "headings": scraped.headings,
        "page_text": scraped.page_text[:2000],
        "dom_summary": format_elements_for_llm(scraped),
    }


# ─────────────────────────────────────────────
# Export all tools as a list
# ─────────────────────────────────────────────

ALL_TOOLS = [
    click_element,
    type_text,
    select_option,
    scroll_page,
    navigate_to,
    extract_text,
    wait_for_element,
    get_dom_snapshot,
]
