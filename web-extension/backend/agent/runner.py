"""
Browser Agent — ADK Runner and Session Management

Sets up InMemorySessionService, Runner, and provides helpers
to run the agent for a given user message + DOM context.
"""

import asyncio
import logging
import json

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agent.agent import create_browser_agent
from agent.tools import set_ws_manager, set_current_ws_session, register_session

logger = logging.getLogger("browser-agent.runner")

# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────
APP_NAME = "browser_automation_agent"

# ─────────────────────────────────────────────
# Singleton instances
# ─────────────────────────────────────────────
_session_service: InMemorySessionService | None = None
_runner: Runner | None = None
_agent = None


def initialize(ws_manager):
    """
    Initialize the ADK agent, session service, and runner.
    Called once at FastAPI startup.
    """
    global _session_service, _runner, _agent

    # Set the WS manager reference for tools
    set_ws_manager(ws_manager)

    # Create agent
    _agent = create_browser_agent()

    # Create session service and runner
    _session_service = InMemorySessionService()
    _runner = Runner(
        agent=_agent,
        app_name=APP_NAME,
        session_service=_session_service,
    )

    logger.info("ADK Runner initialized successfully")


async def ensure_session(ws_session_id: str, user_id: str = "default_user"):
    """
    Create or get an ADK session for a WebSocket connection.
    """
    # Use ws_session_id as the ADK session_id for simplicity
    session_id = f"session_{ws_session_id}"
    
    try:
        session = await _session_service.get_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=session_id,
        )
        if session:
            return session_id
    except Exception:
        pass

    # Create new session
    await _session_service.create_session(
        app_name=APP_NAME,
        user_id=user_id,
        session_id=session_id,
    )
    register_session(session_id, ws_session_id)
    logger.info(f"Created ADK session: {session_id} for WS: {ws_session_id}")
    return session_id


async def run_agent(
    ws_session_id: str,
    user_text: str,
    page_context: dict | None = None,
    user_id: str = "default_user",
) -> str:
    """
    Run the ADK agent with a user message and optional page context.
    
    Args:
        ws_session_id: WebSocket session ID for sending actions to extension
        user_text: The user's message/goal
        page_context: DOM snapshot from the extension (optional)
        user_id: User identifier
    
    Returns:
        The agent's final text response
    """
    if not _runner:
        return "❌ Agent not initialized. Check backend logs."

    # Set the current WS session for tools to use
    set_current_ws_session(ws_session_id)

    # Ensure ADK session exists
    session_id = await ensure_session(ws_session_id, user_id)

    # Build the message content
    # Include DOM context in the message so the agent can see the page
    message_parts = [f"User goal: {user_text}"]

    if page_context and page_context.get("elements"):
        url = page_context.get("url", "unknown")
        title = page_context.get("title", "untitled")
        elements = page_context["elements"]
        
        # Summarize DOM for the LLM (keep it concise to save tokens)
        dom_summary = format_dom_for_llm(elements)
        message_parts.append(
            f"\n\nCurrent page: {title} ({url})\n"
            f"Visible elements ({len(elements)} total):\n{dom_summary}"
        )
    else:
        message_parts.append("\n\nNo DOM snapshot available for the current page.")

    full_message = "\n".join(message_parts)
    logger.info(f"Sending to agent: {full_message[:200]}...")

    # Create ADK content message
    content = types.Content(
        role="user",
        parts=[types.Part(text=full_message)],
    )

    # Run the agent and collect the final response
    final_response = ""
    try:
        events = _runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=content,
        )

        async for event in events:
            if event.is_final_response():
                if event.content and event.content.parts:
                    final_response = event.content.parts[0].text
                    logger.info(f"Agent final response: {final_response[:200]}...")
                break

    except Exception as e:
        logger.error(f"Agent execution error: {e}", exc_info=True)
        final_response = f"❌ Agent error: {str(e)}"

    return final_response or "🤔 Agent produced no response."


def format_dom_for_llm(elements: list, max_elements: int = 50) -> str:
    """
    Format DOM elements into a concise text representation for the LLM.
    Prioritizes interactive elements and limits size to save tokens.
    """
    # Separate interactive and non-interactive
    interactive = [e for e in elements if e.get("clickable")]
    non_interactive = [e for e in elements if not e.get("clickable")]

    # Take interactive first, then fill with non-interactive
    selected = interactive[:max_elements]
    remaining = max_elements - len(selected)
    if remaining > 0:
        selected.extend(non_interactive[:remaining])

    lines = []
    for i, el in enumerate(selected):
        tag = el.get("tag", "?")
        text = el.get("text", "")[:80]
        selector = el.get("selector", "")
        clickable = "🔘" if el.get("clickable") else "📝"
        attrs = el.get("attributes", {})

        # Build a compact one-line description
        parts = [f"{clickable} <{tag}>"]
        if text:
            parts.append(f'"{text}"')
        if attrs.get("type"):
            parts.append(f"[type={attrs['type']}]")
        if attrs.get("placeholder"):
            parts.append(f"[placeholder=\"{attrs['placeholder']}\"]")
        if attrs.get("href"):
            parts.append(f"[href={attrs['href'][:60]}]")
        parts.append(f"→ {selector}")

        lines.append(f"  {i+1}. {' '.join(parts)}")

    return "\n".join(lines)
