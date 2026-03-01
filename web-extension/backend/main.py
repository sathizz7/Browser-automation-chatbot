"""
Browser Automation Chatbot — FastAPI Backend (Phase 3: ADK Agent)

Start with:
    cd backend
    uvicorn main:app --reload --port 8000

Requires:
    - .env file with OPENAI_API_KEY (or other provider key)
    - LLM_MODEL env var (default: openai/gpt-4o-mini)
"""

import uuid
import json
import logging
from datetime import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from ws.manager import ConnectionManager
from agent.runner import initialize as init_agent, run_agent
from agent.tools import resolve_action_result

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
# FastAPI App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Browser Automation Agent",
    description="Local FastAPI backend for AI-powered browser automation with Google ADK",
    version="0.3.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# WebSocket Manager
# ---------------------------------------------------------------------------
manager = ConnectionManager()


# ---------------------------------------------------------------------------
# Startup: Initialize ADK Agent
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def startup():
    logger.info("Initializing ADK Agent...")
    init_agent(manager)
    logger.info("ADK Agent ready!")


# ---------------------------------------------------------------------------
# Health Check
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "connections": manager.connection_count,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# WebSocket Endpoint
# ---------------------------------------------------------------------------
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    session_id = str(uuid.uuid4())[:8]
    await manager.connect(session_id, websocket)

    # Send welcome message
    await manager.send_json(session_id, {
        "type": "system",
        "payload": {
            "message": f"Connected to Browser Agent (ADK). Session: {session_id}",
            "session_id": session_id,
        },
    })

    try:
        while True:
            # Receive JSON message from extension
            raw = await websocket.receive_text()
            logger.info(f"[{session_id}] Received: {raw[:200]}")

            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, Exception):
                data = {"type": "user_message", "payload": {"text": raw}}

            msg_type = data.get("type", "unknown")
            payload = data.get("payload", {})

            # ---------------------------------------------------------------
            # Phase 3: ADK Agent handles user messages
            # ---------------------------------------------------------------
            if msg_type == "user_message":
                user_text = payload.get("text", "")
                page_context = payload.get("page_context")
                logger.info(f"[{session_id}] User says: {user_text}")

                # Log DOM snapshot summary
                if page_context and page_context.get("elements"):
                    count = len(page_context["elements"])
                    url = page_context.get("url", "unknown")
                    logger.info(f"[{session_id}] 📄 DOM: {count} elements from {url}")

                # Send "thinking" status to popup
                await manager.send_json(session_id, {
                    "type": "agent_message",
                    "payload": {
                        "text": "🧠 Thinking...",
                        "session_id": session_id,
                        "status": "thinking",
                    },
                })

                # Run ADK agent
                try:
                    agent_response = await run_agent(
                        ws_session_id=session_id,
                        user_text=user_text,
                        page_context=page_context,
                    )
                except Exception as e:
                    logger.error(f"[{session_id}] Agent error: {e}", exc_info=True)
                    agent_response = f"❌ Agent error: {str(e)}"

                # Send agent response to popup
                await manager.send_json(session_id, {
                    "type": "agent_message",
                    "payload": {
                        "text": agent_response,
                        "session_id": session_id,
                        "status": "complete",
                    },
                })

            elif msg_type == "action_result":
                # Content script returned an action result
                logger.info(f"[{session_id}] Action result: {json.dumps(payload)[:200]}")
                # Resolve the pending future in tools.py
                resolve_action_result(session_id, payload)

            elif msg_type == "dom_snapshot":
                # Content script returned a DOM snapshot (requested by tools)
                logger.info(f"[{session_id}] DOM snapshot received: {payload.get('element_count', '?')} elements")
                resolve_action_result(session_id, payload)

            elif msg_type == "page_state":
                logger.info(f"[{session_id}] Page state: URL={payload.get('url', 'N/A')}")

            elif msg_type == "ping":
                pass  # Keep-alive, no response needed

            else:
                logger.warning(f"[{session_id}] Unknown message type: {msg_type}")

    except WebSocketDisconnect:
        manager.disconnect(session_id)
        logger.info(f"[{session_id}] Client disconnected")
    except Exception as e:
        manager.disconnect(session_id)
        logger.error(f"[{session_id}] Error: {e}", exc_info=True)
