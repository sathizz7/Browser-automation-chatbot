"""Pydantic schemas for the DOM-agent planner.

Core types:
  - DOMElement:    abstracted interactive element from the content script
  - DOMAction:     single action the executor should perform
  - PlanRequest:   what the extension sends to POST /plan
  - PlanResponse:  what the backend returns
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ── Action types ───────────────────────────────────────────

class ActionType(str, Enum):
    TYPE = "type"
    CLICK = "click"
    SELECT = "select"
    SCROLL = "scroll"
    NAVIGATE = "navigate"
    WAIT = "wait"
    DONE = "done"


# ── DOM Element (from content script) ─────────────────────

class DOMElement(BaseModel):
    """Abstracted interactive element extracted by the content script."""
    model_config = ConfigDict(extra="ignore")

    id: str = Field(description="Stable element ID assigned by content script, e.g. el_0")
    tag: str = Field(description="HTML tag: input, button, select, textarea, a")
    type: str = Field(default="", description="Input type or element role")
    label: str = Field(default="", description="Associated label text")
    placeholder: str = Field(default="")
    text: str = Field(default="", description="Visible text content (for buttons/links)")
    name: str = Field(default="", description="HTML name attribute")
    value: str = Field(default="", description="Current value")
    aria_label: str = Field(default="", alias="ariaLabel")
    context: str = Field(default="", description="Semantic context: form title, section heading")
    visible: bool = Field(default=True)
    disabled: bool = Field(default=False)
    otp_detected: bool = Field(default=False, description="Rule-based OTP field detection")


# ── DOM Action (LLM output) ───────────────────────────────

class DOMAction(BaseModel):
    """Single action for the DOM executor to perform."""
    model_config = ConfigDict(extra="ignore")

    type: ActionType
    element_id: str = Field(default="", description="Target element ID (e.g. el_0)")
    value: str = Field(default="", description="Value to type or option to select")
    description: str = Field(default="", description="Human-readable step description")
    url: str = Field(default="", description="URL for navigate actions")
    condition: str = Field(default="", description="Wait condition: dom_change, network_idle")
    timeout_ms: int = Field(default=3000, description="Timeout for wait actions")


# ── Plan Request / Response ────────────────────────────────

class ActionResult(BaseModel):
    """Execution result for a single action."""
    element_id: str = ""
    action_type: str = ""
    success: bool = True
    error: str = ""


class PlanRequest(BaseModel):
    """Request body for POST /plan."""
    model_config = ConfigDict(extra="ignore")

    message: str = Field(min_length=1, max_length=4000)
    elements: list[DOMElement] = Field(default_factory=list)
    page_url: str = ""
    page_title: str = ""
    session_id: str = "default"
    action_history: list[list[dict[str, Any]]] = Field(
        default_factory=list,
        description="Last N action batches for loop detection"
    )
    action_results: list[ActionResult] = Field(
        default_factory=list,
        description="Results from the previous batch execution"
    )
    loop_detected: bool = False


class PlanResponse(BaseModel):
    """Response body from POST /plan."""
    actions: list[DOMAction] = Field(default_factory=list)
    message: str = Field(default="", description="Human-readable status for the chat UI")
    done: bool = Field(default=False, description="True when the task is complete")
    wait_for_user_input: str = Field(
        default="",
        description="Non-empty string = pause and ask the user (e.g. 'Please enter the OTP')"
    )
    error: str = Field(default="")
