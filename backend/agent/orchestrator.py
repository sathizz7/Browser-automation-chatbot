"""
Browser Agent — Orchestration Loop (Playwright-Powered, Skyvern-Style)

Manages the Plan → Act → Verify cycle:
- Scrapes the page via Playwright before each LLM call
- Sends DOM summary (+ optional screenshot) to the LLM
- LLM returns tool calls → ADK executes them via Playwright
- Real-time status streaming to the extension panel via WebSocket
"""

import asyncio
import logging
import json

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agent.tools import set_current_ws_session, set_ws_manager
from browser.manager import get_browser_manager
from browser.scraper import scrape_page, format_elements_for_llm

logger = logging.getLogger("browser-agent.orchestrator")

# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────
APP_NAME = "browser_automation_agent"
MAX_TURNS = 20       # Safety: max total agent turns per user request
MAX_RETRIES = 2      # Max retries per failed action


class Orchestrator:
    """
    Manages the Plan → Act → Verify loop for browser automation.

    Skyvern-style flow:
    1. User sends a goal
    2. Orchestrator scrapes the current page (DOM + screenshot)
    3. Sends goal + page context to ADK agent
    4. Agent returns tool calls → Playwright executes them
    5. After actions complete, orchestrator can re-scrape if needed
    6. Final response sent back to user

    Real-time status updates are sent to the panel throughout.
    """

    def __init__(self, runner: Runner, session_service: InMemorySessionService, ws_manager):
        self.runner = runner
        self.session_service = session_service
        self.ws_manager = ws_manager

    async def run(
        self,
        ws_session_id: str,
        user_text: str,
        user_id: str = "default_user",
    ) -> str:
        """
        Run the full orchestration loop for a user request.

        Key difference from old version: we DON'T rely on the extension
        to send us a DOM snapshot. We scrape the page ourselves via Playwright.

        Args:
            ws_session_id: WebSocket session ID (for status streaming)
            user_text: User's goal text
            user_id: User identifier

        Returns:
            Final agent response text
        """
        # Set up WS session for tools
        set_current_ws_session(ws_session_id)
        session_id = await self._ensure_session(ws_session_id, user_id)

        # ──── Step 1: Scrape the current page ────
        await self._send_status(ws_session_id, "📸 Analyzing page...", "scraping")

        page_context_text = ""
        try:
            manager = get_browser_manager()
            if manager.is_connected:
                page = await manager.get_page()
                scraped = await scrape_page(page, take_screenshot=False)
                dom_text = format_elements_for_llm(scraped)
                page_context_text = (
                    f"\n\nCurrent page: {scraped.title} ({scraped.url})\n"
                    f"Page headings: {', '.join(scraped.headings[:5])}\n"
                    f"Interactive elements ({scraped.element_count} total):\n{dom_text}"
                )
                if scraped.page_text:
                    page_context_text += f"\n\nPage text (first 2000 chars):\n{scraped.page_text[:2000]}"
                logger.info(
                    f"[{ws_session_id}] Scraped {scraped.element_count} elements from {scraped.url}"
                )
            else:
                page_context_text = "\n\nNo browser connected. Use navigate_to() to go to a URL first."
                logger.warning(f"[{ws_session_id}] No browser connected")
        except Exception as e:
            logger.warning(f"[{ws_session_id}] Scrape failed: {e}")
            page_context_text = f"\n\nFailed to scrape page: {e}. Try calling get_dom_snapshot()."

        # ──── Step 2: Build the message ────
        await self._send_status(ws_session_id, "📋 Planning...", "planning")

        full_message = f"User goal: {user_text}{page_context_text}"
        logger.info(f"[{ws_session_id}] Orchestrator starting: {user_text[:100]}")

        content = types.Content(
            role="user",
            parts=[types.Part(text=full_message)],
        )

        # ──── Step 3: Run the ADK agent loop ────
        final_response = ""
        turn_count = 0
        tool_calls_made = []

        try:
            events = self.runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=content,
            )

            async for event in events:
                turn_count += 1

                # Safety: max turns
                if turn_count > MAX_TURNS:
                    logger.warning(f"[{ws_session_id}] Max turns reached ({MAX_TURNS})")
                    await self._send_status(ws_session_id, "⚠️ Reached maximum steps", "warning")
                    break

                # ── Handle tool calls ──
                if self._is_tool_call(event):
                    tool_info = self._extract_tool_info(event)
                    if tool_info:
                        tool_name, tool_args = tool_info
                        tool_calls_made.append(tool_name)
                        status_emoji = self._get_tool_emoji(tool_name)
                        status_text = self._get_tool_status(tool_name, tool_args)
                        await self._send_status(ws_session_id, f"{status_emoji} {status_text}", "acting")

                # ── Handle tool results ──
                if self._is_tool_result(event):
                    result_info = self._extract_tool_result(event)
                    if result_info:
                        tool_name, success = result_info
                        if success:
                            step_num = len([t for t in tool_calls_made if t != "get_dom_snapshot"])
                            if tool_name != "get_dom_snapshot":
                                await self._send_status(
                                    ws_session_id, f"✅ Step {step_num} done: {tool_name}", "evaluating"
                                )
                        else:
                            await self._send_status(
                                ws_session_id, f"❌ {tool_name} failed — retrying", "retrying"
                            )

                # ── Final response ──
                if event.is_final_response():
                    if event.content and event.content.parts:
                        final_response = event.content.parts[0].text
                        logger.info(f"[{ws_session_id}] Agent done: {final_response[:200]}")
                    break

        except Exception as e:
            logger.error(f"[{ws_session_id}] Orchestrator error: {e}", exc_info=True)
            final_response = f"❌ Agent error: {str(e)}"

        # ──── Summary ────
        action_count = len([t for t in tool_calls_made if t != "get_dom_snapshot"])
        verify_count = tool_calls_made.count("get_dom_snapshot")
        logger.info(
            f"[{ws_session_id}] Complete: {action_count} actions, "
            f"{verify_count} verifications, {turn_count} turns"
        )

        return final_response or "🤔 Agent produced no response."

    # ─────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────

    async def _ensure_session(self, ws_session_id: str, user_id: str) -> str:
        """Create or retrieve an ADK session."""
        session_id = f"session_{ws_session_id}"
        try:
            session = await self.session_service.get_session(
                app_name=APP_NAME, user_id=user_id, session_id=session_id,
            )
            if session:
                return session_id
        except Exception:
            pass

        await self.session_service.create_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id,
        )
        logger.info(f"Created ADK session: {session_id}")
        return session_id

    async def _send_status(self, ws_session_id: str, text: str, status: str):
        """Send a real-time status update to the extension panel."""
        try:
            await self.ws_manager.send_json(ws_session_id, {
                "type": "agent_status",
                "payload": {"text": text, "status": status},
            })
        except Exception:
            pass  # WS might not be connected in headless/API mode

    # ─────────────────────────────────────────────
    # Event inspection helpers
    # ─────────────────────────────────────────────

    def _is_tool_call(self, event) -> bool:
        try:
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if hasattr(part, "function_call") and part.function_call:
                        return True
        except Exception:
            pass
        return False

    def _is_tool_result(self, event) -> bool:
        try:
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if hasattr(part, "function_response") and part.function_response:
                        return True
        except Exception:
            pass
        return False

    def _extract_tool_info(self, event) -> tuple[str, dict] | None:
        try:
            for part in event.content.parts:
                if hasattr(part, "function_call") and part.function_call:
                    fc = part.function_call
                    name = fc.name if hasattr(fc, "name") else str(fc)
                    args = fc.args if hasattr(fc, "args") else {}
                    if isinstance(args, str):
                        try: args = json.loads(args)
                        except: args = {}
                    return (name, dict(args) if args else {})
        except Exception as e:
            logger.debug(f"Could not extract tool info: {e}")
        return None

    def _extract_tool_result(self, event) -> tuple[str, bool] | None:
        try:
            for part in event.content.parts:
                if hasattr(part, "function_response") and part.function_response:
                    fr = part.function_response
                    name = fr.name if hasattr(fr, "name") else "unknown"
                    response = fr.response if hasattr(fr, "response") else {}
                    success = response.get("success", True) if isinstance(response, dict) else True
                    return (name, success)
        except Exception as e:
            logger.debug(f"Could not extract tool result: {e}")
        return None

    def _get_tool_emoji(self, tool_name: str) -> str:
        return {
            "click_element": "🖱️", "type_text": "⌨️", "select_option": "📋",
            "scroll_page": "📜", "navigate_to": "🌐", "extract_text": "📋",
            "wait_for_element": "⏳", "get_dom_snapshot": "📸",
        }.get(tool_name, "⚡")

    def _get_tool_status(self, tool_name: str, args: dict) -> str:
        if tool_name == "click_element":
            return f"Clicking {args.get('selector', '...')}"
        elif tool_name == "type_text":
            val = args.get('value', '')[:30]
            return f"Typing \"{val}\" into {args.get('selector', '...')}"
        elif tool_name == "select_option":
            return f"Selecting '{args.get('value', '')}' from {args.get('selector', '...')}"
        elif tool_name == "scroll_page":
            return f"Scrolling {args.get('direction', 'down')}"
        elif tool_name == "navigate_to":
            return f"Navigating to {args.get('url', '...')[:50]}"
        elif tool_name == "get_dom_snapshot":
            return "Analyzing page..."
        else:
            return f"Executing {tool_name}"
