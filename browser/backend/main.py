"""FastAPI server for the browser automation backend.

Provides REST endpoints for the Chrome Extension:
  - POST /chat      : Conversational AI responding with page context
  - POST /automate  : Triggers Browser-Use agent tasks
  - GET /profile    : Returns mock user profile (until DB is added)

Run with: uvicorn main:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from agent import AgentConfig, run_automation, BrowserUseLLM
from allowlist import AllowlistManager
from schemas import (
    AutomateRequest,
    AutomateResult,
    ChatRequest,
    ChatResponse,
    TaskType,
    UserProfile,
)

# Use our BrowserUseLLM wrapper for chat endpoint too (avoids deprecation warning)
from agent import _get_model

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-7s │ %(name)s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Browser Automation Chatbot API")

# Allow extension to talk to localhost
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "chrome-extension://*",
        "http://localhost:*",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Global State (Mock DB) ─────────────────────────────────

# In a real app, this would be in a database tied to auth.
MOCK_PROFILE = UserProfile(
    full_name="Citizen Tester",
    email="citizen@example.com",
    phone="+91-9876543210",
    address_line1="123 Jubilee Hills",
    city="Hyderabad",
    state="Telangana",
    zip_code="500033",
    country="India",
)

ALLOWLIST = AllowlistManager.load()


# ── Internal Helpers ───────────────────────────────────────

def _build_chat_prompt(req: ChatRequest) -> list:
    """Build LangChain messages for the chat endpoint."""
    sys_prompt = (
        "You are an AI browser assistant. "
        "Your job is to either chat with the user OR trigger a browser action.\n\n"
        "If the user is just asking a question, reply with normal text.\n"
        "If the user wants you to DO something (navigate, fill a form, checkout, scrape), "
        "you MUST reply ONLY with a JSON block in this exact format:\n"
        "```json\n"
        "{\n"
        '  "action": "navigate" | "fill_form" | "checkout_flow" | "scrape",\n'
        '  "target_url": "URL to act on",\n'
        '  "message": "Acknowledging message for the user"\n'
        "}\n"
        "```\n\n"
        "If no target URL is specified by the user, use the current page URL."
    )
    
    if req.page_url:
        sys_prompt += f"\n\nThe user is currently on: {req.page_url}"
    if req.page_context:
        ctx_str = json.dumps(req.page_context, indent=2)
        sys_prompt += f"\n\nPage context:\n{ctx_str}"

    return [
        SystemMessage(content=sys_prompt),
        HumanMessage(content=req.message),
    ]

async def _handle_action_intent(action: str, target_url: str, user_message: str, req: ChatRequest) -> ChatResponse:
    """Trigger automation if the LLM output a JSON action."""
    logger.info(f"LLM decided to trigger action: {action} on {target_url}")
    
    try:
        task_type = TaskType(action)
    except ValueError:
        task_type = TaskType.NAVIGATE  # fallback
        
    if not ALLOWLIST.is_allowed(target_url):
        return ChatResponse(
            message=f"I cannot perform actions on {target_url} because it is not allowed by the current policy.",
            session_id=req.session_id
        )

    config = AgentConfig(
        task_type=task_type,
        target_url=target_url,
        user_message=req.message,
        user_profile=MOCK_PROFILE,
        page_context=req.page_context,
        max_steps=15,
        headless=True,
    )

    result = await run_automation(config)
    
    if result.success:
        if result.extracted_data and "raw_result" in result.extracted_data:
            msg = f"{user_message}\n\nResult:\n{result.extracted_data['raw_result']}"
        else:
            msg = f"{user_message}\n\nTask completed successfully!"
    else:
        msg = f"Sorry, the automation failed: {result.error}"

    return ChatResponse(
        message=msg,
        session_id=req.session_id,
    )


# ── API Endpoints ──────────────────────────────────────────

@app.get("/health")
async def health_check():
    """Simple health ping."""
    return {"status": "ok", "allowlist_mode": ALLOWLIST.mode}


@app.get("/profile", response_model=UserProfile)
async def get_profile():
    """Return the current user profile (mocked)."""
    return MOCK_PROFILE


@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest):
    """Conversational endpoint with intent detection."""
    try:
        model_name = _get_model()
        provider = "openai"
        if "/" in model_name:
            provider = model_name.split("/")[0]
        llm = BrowserUseLLM(model=model_name, provider=provider, name=model_name, model_name=model_name)
        messages = _build_chat_prompt(req)
        
        response = llm.invoke(messages)
        content = str(response.content).strip()
        
        # Check if LLM output a JSON action block
        import re
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', content, re.DOTALL)
        if json_match:
            try:
                action_data = json.loads(json_match.group(1))
                if "action" in action_data and action_data["action"] in [t.value for t in TaskType]:
                    # LLM decided it's an automation task! Run it.
                    target_url = action_data.get("target_url") or req.page_url
                    return await _handle_action_intent(
                        action=action_data["action"],
                        target_url=target_url,
                        user_message=action_data.get("message", "Running task..."),
                        req=req
                    )
            except json.JSONDecodeError:
                pass # Fall back to normal chat if JSON is malformed
                
        # Normal chat
        suggested = []
        lower_msg = req.message.lower()
        if "form" in lower_msg or "fill" in lower_msg:
            suggested.append("Fill this form with my profile")
        if "buy" in lower_msg or "checkout" in lower_msg:
            suggested.append("Start checkout flow")
            
        return ChatResponse(
            message=content,
            suggested_actions=suggested,
            session_id=req.session_id,
        )
    except Exception as e:
        logger.error(f"Chat error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/automate", response_model=AutomateResult)
async def automate_endpoint(req: AutomateRequest):
    """Trigger the Browser-Use agent to perform an action."""
    logger.info(f"Received automate request: {req.task_type} for {req.target_url}")

    if not ALLOWLIST.is_allowed(req.target_url):
        logger.warning(f"Blocked URL: {req.target_url}")
        return AutomateResult(
            success=False,
            task_type=req.task_type,
            error=f"URL is not allowed by current policy mode: {ALLOWLIST.mode}",
        )

    # Use provided profile, or fall back to mock
    profile = req.user_profile or MOCK_PROFILE

    config = AgentConfig(
        task_type=req.task_type,
        target_url=req.target_url,
        user_message=req.user_message,
        user_profile=profile,
        page_context=req.page_context,
        max_steps=req.max_steps or 30,
        headless=True,  # Force headless for API runs
    )

    try:
        result = await run_automation(config)
        return result
    except Exception as e:
        logger.error(f"Automation error: {e}", exc_info=True)
        return AutomateResult(
            success=False,
            task_type=req.task_type,
            error=str(e),
        )

# If run directly via standard python execution (though uvicorn is preferred)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
