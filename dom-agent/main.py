"""FastAPI server for the DOM-agent backend.

Provides the /plan endpoint for the Chrome extension's visible automation.
Runs on port 8001, separate from the browser-use backend (port 8000).

Run with: uvicorn main:app --reload --port 8001
"""
from __future__ import annotations

import os
os.environ["LITELLM_TELEMETRY"] = "false"
os.environ["ARIZE_PHOENIX_OTLP_ENDPOINT"] = ""

import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from planner import plan_actions, clear_session, list_sessions
from schemas import PlanRequest, PlanResponse

# ── Logging ────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-8s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ── App ────────────────────────────────────────────────────

app = FastAPI(
    title="DOM Agent — Visible Browser Automation",
    description="LLM-powered action planner for Chrome extension DOM interaction",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Extension and localhost
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Endpoints ──────────────────────────────────────────────

@app.get("/health")
async def health():
    """Health check."""
    return {"status": "ok", "service": "dom-agent", "port": settings.port}


@app.get("/config")
async def get_config():
    """Return current agent configuration (for debugging / extension display)."""
    return {
        "max_elements": settings.max_elements,
        "max_actions_per_batch": settings.max_actions_per_batch,
        "type_delay_min_ms": settings.type_delay_min_ms,
        "type_delay_max_ms": settings.type_delay_max_ms,
        "dom_settle_timeout_ms": settings.dom_settle_timeout_ms,
        "network_idle_ms": settings.network_idle_ms,
        "mutation_settle_ms": settings.mutation_settle_ms,
        "loop_detection_window": settings.loop_detection_window,
        "loop_abort_threshold": settings.loop_abort_threshold,
        "llm_model": settings.llm_model,
    }


@app.post("/plan", response_model=PlanResponse)
async def plan_endpoint(req: PlanRequest):
    """Generate an action plan from DOM snapshot + user instruction.

    The extension sends interactive elements + user message.
    The LLM returns a batch of DOM actions to execute visibly.
    """
    logger.info(
        f"POST /plan — message='{req.message[:80]}', "
        f"elements={len(req.elements)}, page={req.page_url}"
    )

    if len(req.elements) > settings.max_elements:
        logger.warning(
            f"Element count {len(req.elements)} exceeds max {settings.max_elements}, "
            f"truncating to first {settings.max_elements}"
        )
        req.elements = req.elements[: settings.max_elements]

    result = await plan_actions(req)

    logger.info(
        f"Plan result: {len(result.actions)} actions, "
        f"done={result.done}, wait='{result.wait_for_user_input[:50]}'"
    )
    return result


@app.post("/reset")
async def reset_session(session_id: str = "default"):
    """Clear memory for a session so the planner starts fresh.

    Call this when the user starts a new task on a new page.
    """
    existed = clear_session(session_id)
    logger.info(f"POST /reset — session_id='{session_id}', existed={existed}")
    return {"status": "ok", "session_id": session_id, "was_active": existed}


@app.get("/sessions")
async def get_sessions():
    """List all active sessions (for debugging)."""
    sessions = list_sessions()
    return {"sessions": sessions, "count": len(sessions)}
