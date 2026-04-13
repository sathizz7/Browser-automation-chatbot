"""LLM-based DOM action planner with session memory.

Uses LangChain's InMemoryChatMessageHistory + RunnableWithMessageHistory
to keep conversation context across /plan calls within a session.
"""
from __future__ import annotations

import os
os.environ.setdefault("LITELLM_TELEMETRY", "false")
os.environ.setdefault("ARIZE_PHOENIX_OTLP_ENDPOINT", "")

import json
import logging
import traceback
from typing import Any

from langchain_community.chat_models import ChatLiteLLM
from langchain_core.chat_history import InMemoryChatMessageHistory
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables.history import RunnableWithMessageHistory

from config import settings
from schemas import (
    ActionType,
    DOMAction,
    DOMElement,
    PlanRequest,
    PlanResponse,
)
from safety import validate_actions

logger = logging.getLogger(__name__)

# ── Session Store ──────────────────────────────────────────
# Global dict: session_id → InMemoryChatMessageHistory
# Each session remembers all planner turns (DOM snapshots + LLM replies)

_session_store: dict[str, InMemoryChatMessageHistory] = {}


def get_session_history(session_id: str) -> InMemoryChatMessageHistory:
    """Get or create chat history for a session."""
    if session_id not in _session_store:
        _session_store[session_id] = InMemoryChatMessageHistory()
        logger.info(f"New session created: {session_id}")
    return _session_store[session_id]


def clear_session(session_id: str) -> bool:
    """Clear memory for a session. Returns True if session existed."""
    if session_id in _session_store:
        del _session_store[session_id]
        logger.info(f"Session cleared: {session_id}")
        return True
    return False


def list_sessions() -> list[str]:
    """List all active session IDs."""
    return list(_session_store.keys())


# ── System prompt ──────────────────────────────────────────

SYSTEM_PROMPT = """You are a browser automation assistant. You control a user's Chrome tab by outputting JSON action plans.

## Rules:
1. You receive a list of interactive DOM elements, each with a stable `id` (e.g. "input_mobile_3a8f2c", "btn_send_otp_7d2ea1").
2. You MUST return a JSON object with an "actions" array. Each action references an element by its `id`.
3. NEVER output raw CSS selectors — only use element IDs from the provided list.
4. You may batch multiple actions in one response for efficiency.
5. If you need user input (e.g. OTP), set `wait_for_user_input` to describe what you need.
6. When the task is complete, include a `done` action and set `done: true`.
7. Each element has a `context` field showing its form/section (e.g. "Login Form → OTP Verification"). Use this to understand what part of the page you are interacting with.
8. You have MEMORY of previous turns. Check the conversation history before planning — do NOT repeat actions that already succeeded.
9. If a field already has a value filled (check the `value` field), do NOT re-type into it.

## Action types:
- `type`: Type text into an input field. Requires `element_id` and `value`.
- `click`: Click a button/link. Requires `element_id`.
- `select`: Select a dropdown option. Requires `element_id` and `value`.
- `scroll`: Scroll to an element. Requires `element_id`.
- `navigate`: Navigate to a URL. Requires `url`.
- `wait`: Wait for page changes. Optional `condition` (dom_change, network_idle) and `timeout_ms`.
- `done`: Task complete. Set `done: true`.

## Response format (strict JSON only, no markdown):
{
  "actions": [
    {"type": "type", "element_id": "input_mobile_3a8f2c", "value": "some text", "description": "Filling mobile number"},
    {"type": "click", "element_id": "btn_send_otp_7d2ea1", "description": "Clicking send OTP button"}
  ],
  "message": "Brief status message for the user",
  "done": false,
  "wait_for_user_input": ""
}

## Few-shot examples:

### Example 1: Fill a form field and submit
User says: "fill my mobile number 8248007169 and click send OTP"
Elements: input_mobile_3a8f2c (input, placeholder="Mobile No."), btn_send_otp_7d2ea1 (button, text="Send OTP")
You respond:
{"actions": [{"type": "type", "element_id": "input_mobile_3a8f2c", "value": "8248007169", "description": "Filling mobile number"}, {"type": "click", "element_id": "btn_send_otp_7d2ea1", "description": "Clicking Send OTP"}], "message": "Filling mobile number and sending OTP.", "done": false, "wait_for_user_input": ""}

### Example 2: Wait for user OTP input
Elements show an OTP field: input_otp_verify_9b3c1d (input, ⚠️ OTP_FIELD)
You respond:
{"actions": [], "message": "OTP field detected. Please enter your OTP.", "done": false, "wait_for_user_input": "Please enter the OTP sent to your mobile number"}

### Example 3: Select a dropdown option
User says: "choose gandhi nagar statue hall"
Elements: sel_area_name_a1b2c3 (select, label="Area"), sel_function_hall_d4e5f6 (select, label="Function Hall Name")
You respond:
{"actions": [{"type": "select", "element_id": "sel_area_name_a1b2c3", "value": "Gandhi Nagar", "description": "Selecting area"}, {"type": "select", "element_id": "sel_function_hall_d4e5f6", "value": "Statue Hall", "description": "Selecting function hall"}], "message": "Selecting Gandhi Nagar area and Statue Hall.", "done": false, "wait_for_user_input": ""}

## Safety:
- NEVER click buttons that say: "Delete Account", "Remove", "Deactivate".
- If unsure what an element does, ask the user via `wait_for_user_input`.
"""


# ── Prompt Template ────────────────────────────────────────

prompt = ChatPromptTemplate.from_messages([
    SystemMessage(content=SYSTEM_PROMPT),
    MessagesPlaceholder(variable_name="history"),  # LangChain injects past turns here
    ("human", "{input}"),                           # Current turn's user prompt
])


# ── Element Formatting ────────────────────────────────────

def _format_elements(elements: list[DOMElement]) -> str:
    """Format elements list for the LLM prompt."""
    if not elements:
        return "No interactive elements found on the page."

    lines: list[str] = []
    for el in elements:
        parts = [f'id="{el.id}"', f"tag={el.tag}"]
        if el.type:
            parts.append(f"type={el.type}")
        if el.label:
            parts.append(f'label="{el.label}"')
        if el.text:
            parts.append(f'text="{el.text}"')
        if el.placeholder:
            parts.append(f'placeholder="{el.placeholder}"')
        if el.name:
            parts.append(f"name={el.name}")
        if el.value:
            parts.append(f'value="{el.value}"')
        if el.context:
            parts.append(f'context="{el.context}"')
        if el.disabled:
            parts.append("DISABLED")
        if el.otp_detected:
            parts.append("⚠️ OTP_FIELD")
        lines.append(f"  [{', '.join(parts)}]")

    return "\n".join(lines)


def _format_results(results: list[dict[str, Any]]) -> str:
    """Format previous action results for context."""
    if not results:
        return ""
    lines = ["Previous action results:"]
    for r in results:
        status = "✅" if r.get("success", True) else "❌"
        lines.append(f"  {status} {r.get('action_type', '?')} on {r.get('element_id', '?')}: {r.get('error', 'ok')}")
    return "\n".join(lines)


def _build_user_prompt(req: PlanRequest) -> str:
    """Build the user message for the current turn."""
    parts = [
        f"Page: {req.page_url}",
        f"Title: {req.page_title}",
        "",
        "Interactive elements:",
        _format_elements(req.elements),
    ]

    # Add previous results if any
    results_text = _format_results([r.model_dump() for r in req.action_results])
    if results_text:
        parts.extend(["", results_text])

    # Add loop warning
    if req.loop_detected:
        parts.extend([
            "",
            "⚠️ LOOP DETECTED: Your previous actions are repeating. Try a different approach or ask the user for help.",
        ])

    parts.extend(["", f"User instruction: {req.message}"])

    return "\n".join(parts)


def _parse_llm_response(content: str) -> dict[str, Any]:
    """Parse LLM response, extracting JSON from potential markdown wrapping."""
    content = content.strip()

    # Strip markdown code fences if present
    if content.startswith("```"):
        lines = content.split("\n")
        # Remove first and last lines (fences)
        lines = [l for l in lines if not l.strip().startswith("```")]
        content = "\n".join(lines).strip()

    return json.loads(content)


# ── LLM Chain (created once, reused) ──────────────────────

_llm = None
_chain_with_history = None


def _get_chain():
    """Lazily create the LLM chain with history. Created once on first call."""
    global _llm, _chain_with_history

    if _chain_with_history is not None:
        return _chain_with_history

    model_name = settings.llm_model
    logger.info(f"Creating LLM chain: {model_name}")

    _llm = ChatLiteLLM(
        model=model_name,
        temperature=0,  # Deterministic for planning
    )

    # prompt | llm = the runnable chain
    chain = prompt | _llm

    # Wrap with session history
    _chain_with_history = RunnableWithMessageHistory(
        chain,
        get_session_history,
        input_messages_key="input",
        history_messages_key="history",
    )

    return _chain_with_history


# ── Main Planner ──────────────────────────────────────────

async def plan_actions(req: PlanRequest) -> PlanResponse:
    """Generate an action plan from the DOM snapshot + user message.

    Uses LangChain's RunnableWithMessageHistory so the LLM
    remembers all prior turns within the same session_id.
    """
    try:
        chain = _get_chain()
        user_prompt = _build_user_prompt(req)

        # Config tells RunnableWithMessageHistory which session to use
        config = {"configurable": {"session_id": req.session_id}}

        logger.info(f"Calling LLM for session '{req.session_id}'")
        response = chain.invoke({"input": user_prompt}, config=config)

        raw = str(response.content).strip()
        logger.debug(f"LLM raw response: {raw[:500]}")

        # Parse JSON
        try:
            data = _parse_llm_response(raw)
        except json.JSONDecodeError:
            logger.warning("LLM returned non-JSON, retrying with strict prompt")
            # Retry: add a correction message to history
            retry_prompt = "Your response was not valid JSON. Please respond with ONLY a JSON object, no explanation."
            response = chain.invoke({"input": retry_prompt}, config=config)
            raw = str(response.content).strip()
            data = _parse_llm_response(raw)

        # Parse into DOMActions
        raw_actions = data.get("actions", [])
        actions = []
        for a in raw_actions[:settings.max_actions_per_batch]:
            try:
                actions.append(DOMAction(**a))
            except Exception as e:
                logger.warning(f"Skipping invalid action {a}: {e}")

        # Safety validation
        safe_actions, warnings = validate_actions(actions, req.elements)
        if warnings:
            for w in warnings:
                logger.warning(f"Safety: {w}")

        message = data.get("message", "")
        if warnings:
            message += "\n⚠️ " + "; ".join(warnings)

        return PlanResponse(
            actions=safe_actions,
            message=message,
            done=data.get("done", False),
            wait_for_user_input=data.get("wait_for_user_input", ""),
        )

    except Exception as e:
        logger.error(f"Planner error: {e}\n{traceback.format_exc()}")
        return PlanResponse(
            actions=[],
            message=f"Planning failed: {str(e)}",
            done=False,
            error=str(e),
        )
