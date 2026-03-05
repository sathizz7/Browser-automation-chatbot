"""LLM-based DOM action planner.

Receives a DOM snapshot (abstracted elements) + user message and returns
a list of DOMActions that the content script should execute visibly.
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
from langchain_core.messages import HumanMessage, SystemMessage

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

# ── System prompt ──────────────────────────────────────────

SYSTEM_PROMPT = """You are a browser automation assistant. You control a user's Chrome tab by outputting JSON action plans.

## Rules:
1. You receive a list of interactive DOM elements, each with a unique `id` (e.g. "el_0", "el_1").
2. You MUST return a JSON object with an "actions" array. Each action references an element by its `id`.
3. NEVER output raw CSS selectors — only use element IDs from the provided list.
4. You may batch multiple actions in one response for efficiency.
5. If you need user input (e.g. OTP), set `wait_for_user_input` to describe what you need.
6. When the task is complete, include a `done` action and set `done: true`.

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
    {"type": "type", "element_id": "el_0", "value": "some text", "description": "Filling name field"},
    {"type": "click", "element_id": "el_1", "description": "Clicking submit button"}
  ],
  "message": "Brief status message for the user",
  "done": false,
  "wait_for_user_input": ""
}

## Safety:
- NEVER interact with password or payment fields.
- NEVER click buttons that say: "Delete Account", "Remove", "Deactivate".
- If unsure what an element does, ask the user via `wait_for_user_input`.
"""


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
    """Build the user message for the LLM."""
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


async def plan_actions(req: PlanRequest) -> PlanResponse:
    """Generate an action plan from the DOM snapshot + user message.

    Returns a PlanResponse with validated, safe actions.
    """
    try:
        # Build LLM messages
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=_build_user_prompt(req)),
        ]

        # Call LLM
        model_name = settings.llm_model
        llm = ChatLiteLLM(model=model_name)
        logger.info(f"Calling LLM: {model_name}")

        response = llm.invoke(messages)
        raw = str(response.content).strip()
        logger.debug(f"LLM raw response: {raw[:500]}")

        # Parse JSON
        try:
            data = _parse_llm_response(raw)
        except json.JSONDecodeError:
            logger.warning("LLM returned non-JSON, retrying with strict prompt")
            # Retry with stricter prompt
            messages.append(HumanMessage(
                content="Your response was not valid JSON. Please respond with ONLY a JSON object, no explanation."
            ))
            response = llm.invoke(messages)
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
