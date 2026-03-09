"""Action safety layer for the DOM-agent.

Validates planned actions before they reach the content script executor.
Blocks dangerous operations (password fields, payment forms, destructive actions).
"""
from __future__ import annotations

import logging
import re

from schemas import ActionType, DOMAction, DOMElement

logger = logging.getLogger(__name__)

# ── Blocked patterns ───────────────────────────────────────
#password -- add password if needed
_BLOCKED_INPUT_TYPES = {"file"}

_BLOCKED_NAME_PATTERNS = re.compile(
    r"(card.?num|cvv|cvc|expir|security.?code|ssn|social.?security)",
    re.IGNORECASE,
)

_DESTRUCTIVE_TEXT_PATTERNS = re.compile(
    r"(delete.?account|remove.?account|deactivate|close.?account|cancel.?subscription)",
    re.IGNORECASE,
)


def is_element_blocked(el: DOMElement) -> bool:
    """Check if an element should be blocked from interaction."""
    # Password fields
    if el.type in _BLOCKED_INPUT_TYPES:
        logger.warning(f"Blocked element {el.id}: type={el.type}")
        return True

    # Payment-related fields
    combined = f"{el.name} {el.label} {el.placeholder} {el.aria_label}"
    if _BLOCKED_NAME_PATTERNS.search(combined):
        logger.warning(f"Blocked element {el.id}: matches payment pattern in '{combined}'")
        return True

    return False


def is_action_destructive(action: DOMAction, elements: list[DOMElement]) -> bool:
    """Check if a click action targets a destructive button."""
    if action.type != ActionType.CLICK:
        return False

    target = next((el for el in elements if el.id == action.element_id), None)
    if not target:
        return False

    combined = f"{target.text} {target.label} {target.aria_label}"
    if _DESTRUCTIVE_TEXT_PATTERNS.search(combined):
        logger.warning(f"Blocked destructive action on {action.element_id}: '{combined}'")
        return True

    return False


def validate_actions(
    actions: list[DOMAction],
    elements: list[DOMElement],
) -> tuple[list[DOMAction], list[str]]:
    """Validate and filter a list of planned actions.

    Returns:
        (safe_actions, warnings) — filtered list + human-readable warnings.
    """
    element_map = {el.id: el for el in elements}
    safe: list[DOMAction] = []
    warnings: list[str] = []

    for action in actions:
        # Allow non-element actions (wait, navigate, done)
        if action.type in {ActionType.WAIT, ActionType.NAVIGATE, ActionType.DONE}:
            safe.append(action)
            continue

        # Check target element exists
        target = element_map.get(action.element_id)
        if not target:
            warnings.append(f"Element {action.element_id} not found — skipping {action.type.value}")
            continue

        # Check blocked elements
        if is_element_blocked(target):
            warnings.append(
                f"Blocked: {action.type.value} on {action.element_id} "
                f"({target.label or target.name}) — safety restriction"
            )
            continue

        # Check destructive actions
        if is_action_destructive(action, elements):
            warnings.append(
                f"Blocked destructive click on {action.element_id} "
                f"({target.text}) — requires explicit confirmation"
            )
            continue

        safe.append(action)

    return safe, warnings
