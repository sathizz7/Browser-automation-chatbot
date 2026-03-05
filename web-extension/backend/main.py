"""
Browser Automation Chatbot — FastAPI Backend (Playwright-Powered)

Start with:
    cd backend
    uvicorn main:app --reload --port 8000

Modes:
    1. WebSocket (Extension) — Extension panel sends goals via WS
    2. HTTP API — POST /api/run to run tasks programmatically

Requires:
    - .env file with API keys (OPENAI_API_KEY / GEMINI_API_KEY)
    - LLM_MODEL env var (default: gemini/gemini-2.5-flash)
    - Playwright + Chromium installed (pip install playwright && playwright install chromium)
"""

import uuid
import json
import logging
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

from ws.manager import ConnectionManager
from agent.runner import initialize as init_agent
from agent.orchestrator import Orchestrator
from agent.tools import set_ws_manager
from browser.manager import BrowserManager, BrowserConfig, set_browser_manager, get_browser_manager

# ---------------------------------------------------------------------------
# Load environment variables
# ---------------------------------------------------------------------------
load_dotenv()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger("browser-agent")

# ---------------------------------------------------------------------------
# WebSocket Manager & Orchestrator (module-level)
# ---------------------------------------------------------------------------
ws_manager = ConnectionManager()
orchestrator: Orchestrator | None = None


# ---------------------------------------------------------------------------
# Lifespan: Start Playwright + ADK on startup, clean up on shutdown
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    global orchestrator

    # ── STARTUP ──
    logger.info("🚀 Starting up...")

    # 1. Initialize Playwright browser manager (don't launch yet — launch on first use)
    browser_mgr = BrowserManager(BrowserConfig(headless=False))
    set_browser_manager(browser_mgr)
    logger.info("✅ Playwright BrowserManager initialized (launch on first use)")

    # 2. Initialize ADK agent + orchestrator
    set_ws_manager(ws_manager)
    runner, session_service = init_agent(ws_manager)
    orchestrator = Orchestrator(runner, session_service, ws_manager)
    logger.info("✅ ADK Agent + Orchestrator ready!")

    yield  # ── App is running ──

    # ── SHUTDOWN ──
    logger.info("🔒 Shutting down...")
    browser_mgr = get_browser_manager()
    if browser_mgr.is_connected:
        await browser_mgr.close()
    logger.info("✅ Cleanup complete")


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Browser Automation Agent",
    description="Playwright-powered AI browser automation with Google ADK",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health Check
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    browser_mgr = get_browser_manager()
    return {
        "status": "ok",
        "browser_connected": browser_mgr.is_connected,
        "browser_mode": browser_mgr.mode,
        "ws_connections": ws_manager.connection_count,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# API: Run a task (Headless mode — no extension needed)
# ---------------------------------------------------------------------------
class RunRequest(BaseModel):
    goal: str
    url: str | None = None
    headless: bool = True


class RunResponse(BaseModel):
    success: bool
    result: str
    url: str | None = None
    error: str | None = None


@app.post("/api/run", response_model=RunResponse)
async def api_run(req: RunRequest):
    """
    Run a browser automation task via HTTP API.
    No extension needed — Playwright controls a headless browser.

    Body:
        goal: What to automate (e.g. "Search for hello world on Google")
        url: Starting URL (optional, e.g. "https://google.com")
        headless: Whether to run headless (default: True)
    """
    browser_mgr = get_browser_manager()

    try:
        # Launch browser if not already connected
        if not browser_mgr.is_connected:
            await browser_mgr.launch_headless()

        # Navigate to URL if provided
        if req.url:
            await browser_mgr.navigate(req.url)

        # Create a virtual session ID for this API request
        api_session_id = f"api_{str(uuid.uuid4())[:8]}"

        # Run the orchestrator
        result = await orchestrator.run(
            ws_session_id=api_session_id,
            user_text=req.goal,
        )

        page = await browser_mgr.get_page()
        return RunResponse(success=True, result=result, url=page.url)

    except Exception as e:
        logger.error(f"API run error: {e}", exc_info=True)
        return RunResponse(success=False, result="", error=str(e))


# ---------------------------------------------------------------------------
# API: Connect to existing Chrome (CDP mode)
# ---------------------------------------------------------------------------
class ConnectRequest(BaseModel):
    cdp_endpoint: str = "http://localhost:9222"


@app.post("/api/connect")
async def api_connect(req: ConnectRequest):
    """
    Connect to an existing Chrome browser via CDP.
    Start Chrome with: chrome.exe --remote-debugging-port=9222
    """
    browser_mgr = get_browser_manager()

    try:
        page = await browser_mgr.connect_cdp(req.cdp_endpoint)
        return {
            "success": True,
            "mode": "cdp",
            "url": page.url,
            "title": await page.title(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# API: Launch headless browser
# ---------------------------------------------------------------------------
@app.post("/api/launch")
async def api_launch():
    """Launch a new headless Chromium browser."""
    browser_mgr = get_browser_manager()

    try:
        if browser_mgr.is_connected:
            await browser_mgr.close()
        page = await browser_mgr.launch_headless()
        return {
            "success": True,
            "mode": "headless",
            "url": page.url,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# WebSocket Endpoint (Extension panel communication)
# ---------------------------------------------------------------------------
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    session_id = str(uuid.uuid4())[:8]
    await ws_manager.connect(session_id, websocket)

    # Send welcome message
    await ws_manager.send_json(session_id, {
        "type": "system",
        "payload": {
            "message": f"Connected to Browser Agent (Playwright). Session: {session_id}",
            "session_id": session_id,
        },
    })

    try:
        while True:
            raw = await websocket.receive_text()
            logger.info(f"[{session_id}] Received: {raw[:200]}")

            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, Exception):
                data = {"type": "user_message", "payload": {"text": raw}}

            msg_type = data.get("type", "unknown")
            payload = data.get("payload", {})

            # ── User sends a goal ──
            if msg_type == "user_message":
                user_text = payload.get("text", "")
                logger.info(f"[{session_id}] User says: {user_text}")

                # Ensure browser is connected
                browser_mgr = get_browser_manager()
                if not browser_mgr.is_connected:
                    # Try CDP first (user's browser), then headless
                    try:
                        await browser_mgr.connect_cdp("http://localhost:9222")
                        logger.info(f"[{session_id}] Auto-connected to Chrome via CDP")
                    except Exception:
                        await browser_mgr.launch_headless()
                        logger.info(f"[{session_id}] Launched headless browser")

                # Navigate if page context has a URL
                page_context = payload.get("page_context")
                if page_context and page_context.get("url"):
                    current_page = await browser_mgr.get_page()
                    ctx_url = page_context["url"]
                    # Only navigate if we're not already on this page
                    if current_page.url != ctx_url and ctx_url != "about:blank":
                        await browser_mgr.navigate(ctx_url)

                # Run orchestrator
                try:
                    agent_response = await orchestrator.run(
                        ws_session_id=session_id,
                        user_text=user_text,
                    )
                except Exception as e:
                    logger.error(f"[{session_id}] Orchestrator error: {e}", exc_info=True)
                    agent_response = f"❌ Agent error: {str(e)}"

                # Send final response
                await ws_manager.send_json(session_id, {
                    "type": "agent_message",
                    "payload": {
                        "text": agent_response,
                        "session_id": session_id,
                        "status": "complete",
                    },
                })

            elif msg_type == "ping":
                pass

            else:
                logger.debug(f"[{session_id}] Message type: {msg_type}")

    except WebSocketDisconnect:
        ws_manager.disconnect(session_id)
        logger.info(f"[{session_id}] Client disconnected")
    except Exception as e:
        ws_manager.disconnect(session_id)
        logger.error(f"[{session_id}] Error: {e}", exc_info=True)
