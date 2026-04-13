"""
Browser Agent — ADK Runner and Session Management

Sets up InMemorySessionService, Runner, and provides helpers
to run the agent for a given user message.
"""

import logging

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

from agent.agent import create_browser_agent
from agent.tools import set_ws_manager

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

    Returns:
        Tuple of (Runner, InMemorySessionService) for the orchestrator
    """
    global _session_service, _runner, _agent

    # Set the WS manager reference for status streaming
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
    return _runner, _session_service
