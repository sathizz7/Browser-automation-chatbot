"""
Browser Agent — ADK Tool Definitions

Each function here is an ADK FunctionTool that the agent can call.
They receive actions from the LLM and relay them via WebSocket to the
Chrome Extension's content script for execution.

Tools:
    - click_element: Click on a page element
    - type_text: Type text into an input field
    - scroll_page: Scroll the page
    - navigate_to: Navigate to a URL
    - extract_text: Extract text from an element
    - wait_for_element: Wait for an element to appear
    - get_dom_snapshot: Request a fresh DOM snapshot
"""

import asyncio
import logging
import json

logger = logging.getLogger("browser-agent.tools")

# ─────────────────────────────────────────────
# Action Bridge: sends actions to extension via WebSocket
# ─────────────────────────────────────────────

# This dict maps session_id -> asyncio.Queue for receiving action results
_action_futures: dict[str, asyncio.Future] = {}

# Reference to the WS manager — set by runner.py at startup
_ws_manager = None
_session_ws_map: dict[str, str] = {}  # agent_session_id -> ws_session_id


def set_ws_manager(manager):
    """Set the WebSocket manager reference (called once at startup)."""
    global _ws_manager
    _ws_manager = manager


def register_session(agent_session_id: str, ws_session_id: str):
    """Map an ADK agent session to a WebSocket session."""
    _session_ws_map[agent_session_id] = ws_session_id


async def send_action_to_extension(ws_session_id: str, tool: str, args: dict) -> dict:
    """
    Send a tool action to the extension via WebSocket and wait for the result.
    Returns the action result dict from the content script.
    """
    if not _ws_manager:
        return {"success": False, "error": "WebSocket manager not initialized"}

    # Create a future to wait for the result
    future = asyncio.get_event_loop().create_future()
    _action_futures[ws_session_id] = future

    # Send the action command to the extension
    await _ws_manager.send_json(ws_session_id, {
        "type": "execute_action",
        "payload": {"tool": tool, "args": args},
    })

    try:
        # Wait for content script to execute and return result (timeout: 15s)
        result = await asyncio.wait_for(future, timeout=15.0)
        return result
    except asyncio.TimeoutError:
        return {"success": False, "error": f"Action '{tool}' timed out after 15s"}
    finally:
        _action_futures.pop(ws_session_id, None)


def resolve_action_result(ws_session_id: str, result: dict):
    """Called when an action_result message arrives from the extension."""
    future = _action_futures.get(ws_session_id)
    if future and not future.done():
        future.set_result(result)


async def request_dom_from_extension(ws_session_id: str) -> dict:
    """Request a fresh DOM snapshot from the extension."""
    if not _ws_manager:
        return {"success": False, "error": "WebSocket manager not initialized"}

    future = asyncio.get_event_loop().create_future()
    _action_futures[ws_session_id] = future

    await _ws_manager.send_json(ws_session_id, {
        "type": "request_dom_snapshot",
        "payload": {},
    })

    try:
        result = await asyncio.wait_for(future, timeout=10.0)
        return result
    except asyncio.TimeoutError:
        return {"success": False, "error": "DOM snapshot request timed out"}
    finally:
        _action_futures.pop(ws_session_id, None)


# ─────────────────────────────────────────────
# ADK Tool Functions
# ─────────────────────────────────────────────

# NOTE: These are plain functions registered as ADK tools.
# The ws_session_id is stored in the ADK session state and
# retrieved by the orchestrator. For Phase 3, we use a global
# "current session" approach which will be refined in Phase 4.

_current_ws_session: str | None = None


def set_current_ws_session(ws_session_id: str):
    global _current_ws_session
    _current_ws_session = ws_session_id


async def click_element(selector: str) -> dict:
    """Click on a page element identified by its CSS selector.

    Args:
        selector: CSS selector of the element to click (e.g. '#submit-btn', 'button.login')
    
    Returns:
        dict with success status and details
    """
    logger.info(f"🖱️ click_element: {selector}")
    return await send_action_to_extension(_current_ws_session, "click", {"selector": selector})


async def type_text(selector: str, value: str, clear_first: bool = True) -> dict:
    """Type text into an input field identified by its CSS selector.

    Args:
        selector: CSS selector of the input element
        value: The text to type into the field
        clear_first: Whether to clear the field before typing (default: True)
    
    Returns:
        dict with success status and details
    """
    logger.info(f"⌨️ type_text: '{value}' into {selector}")
    return await send_action_to_extension(_current_ws_session, "type", {
        "selector": selector,
        "value": value,
        "clear_first": clear_first,
    })


async def scroll_page(direction: str = "down", amount: int = 500) -> dict:
    """Scroll the page in a given direction.

    Args:
        direction: Scroll direction - 'up', 'down', 'left', or 'right'
        amount: Number of pixels to scroll (default: 500)
    
    Returns:
        dict with success status
    """
    logger.info(f"📜 scroll_page: {direction} by {amount}px")
    scroll_map = {
        "down": {"x": 0, "y": amount},
        "up": {"x": 0, "y": -amount},
        "right": {"x": amount, "y": 0},
        "left": {"x": -amount, "y": 0},
    }
    coords = scroll_map.get(direction, {"x": 0, "y": amount})
    return await send_action_to_extension(_current_ws_session, "scroll", coords)


async def navigate_to(url: str) -> dict:
    """Navigate the browser to a specific URL.

    Args:
        url: The full URL to navigate to (e.g. 'https://example.com')
    
    Returns:
        dict with success status
    """
    logger.info(f"🌐 navigate_to: {url}")
    return await send_action_to_extension(_current_ws_session, "navigate", {"url": url})


async def extract_text(selector: str) -> dict:
    """Extract text content from a page element.

    Args:
        selector: CSS selector of the element to extract text from
    
    Returns:
        dict with success status and extracted text
    """
    logger.info(f"📋 extract_text: {selector}")
    return await send_action_to_extension(_current_ws_session, "extract", {"selector": selector})


async def wait_for_element(selector: str, timeout_ms: int = 5000) -> dict:
    """Wait for a page element to appear in the DOM.

    Args:
        selector: CSS selector of the element to wait for
        timeout_ms: Maximum time to wait in milliseconds (default: 5000)
    
    Returns:
        dict with success status
    """
    logger.info(f"⏳ wait_for_element: {selector} (timeout: {timeout_ms}ms)")
    return await send_action_to_extension(_current_ws_session, "wait_for", {
        "selector": selector,
        "timeout_ms": timeout_ms,
    })


async def get_dom_snapshot() -> dict:
    """Request a fresh DOM snapshot from the current page.
    Use this to see the current state of the page after performing actions.
    
    Returns:
        dict with page URL, title, and list of visible elements
    """
    logger.info("📸 get_dom_snapshot requested")
    return await request_dom_from_extension(_current_ws_session)


# ─────────────────────────────────────────────
# Export all tools as a list
# ─────────────────────────────────────────────

ALL_TOOLS = [
    click_element,
    type_text,
    scroll_page,
    navigate_to,
    extract_text,
    wait_for_element,
    get_dom_snapshot,
]
