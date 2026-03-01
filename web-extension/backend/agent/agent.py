"""
Browser Agent — ADK Agent Definition

Creates the ADK LlmAgent with LiteLLM model wrapper and browser tools.
Supports any LLM provider via LiteLLM (OpenAI, Gemini, Anthropic, Ollama, etc.)
"""

import os
import logging

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

from agent.tools import ALL_TOOLS

logger = logging.getLogger("browser-agent.agent")

# ─────────────────────────────────────────────
# System Instruction
# ─────────────────────────────────────────────

BROWSER_AGENT_INSTRUCTION = """You are an AI browser automation agent. You can see and interact with web pages through a Chrome Extension.

## Your Capabilities
You have access to these tools to control the browser:
- **click_element(selector)** — Click on a page element using its CSS selector
- **type_text(selector, value)** — Type text into an input field
- **scroll_page(direction, amount)** — Scroll the page (up/down/left/right)
- **navigate_to(url)** — Navigate to a specific URL
- **extract_text(selector)** — Extract text content from an element
- **wait_for_element(selector)** — Wait for an element to appear
- **get_dom_snapshot()** — Get a fresh view of the current page elements

## How You Work
1. You receive the user's goal along with a DOM snapshot of the current page
2. The DOM snapshot is a JSON array of visible elements, each with:
   - `tag`: HTML tag name
   - `text`: visible text content
   - `selector`: CSS selector you can use with tools
   - `clickable`: whether the element is interactive
   - `attributes`: relevant HTML attributes

3. Analyze the DOM to understand the current page state
4. Use your tools to perform actions ONE AT A TIME
5. After each action, use get_dom_snapshot() to see the updated page
6. Continue until the user's goal is achieved or you need more information

## Important Rules
- Always use the CSS selectors from the DOM snapshot — never guess selectors
- Perform actions one at a time and verify each one succeeded
- If an action fails, try an alternative selector or approach
- If you can't find the right element, use get_dom_snapshot() to refresh your view
- Be concise in your responses — tell the user what you're doing and what happened
- If you need clarification about the goal, ask the user

## Response Format
When executing actions, briefly describe what you're about to do, then call the tool.
After completing the goal, summarize what was accomplished.
"""

# ─────────────────────────────────────────────
# Agent Factory
# ─────────────────────────────────────────────

def create_browser_agent(model_name: str | None = None) -> LlmAgent:
    """
    Create the browser automation ADK agent.
    
    Args:
        model_name: LiteLLM model string (e.g. "openai/gpt-4o-mini").
                    Defaults to LLM_MODEL env var or "openai/gpt-4o-mini".
    
    Returns:
        Configured LlmAgent instance
    """
    model_str = model_name or os.getenv("LLM_MODEL", "openai/gpt-4o-mini")
    logger.info(f"Creating browser agent with model: {model_str}")

    agent = LlmAgent(
        model=LiteLlm(model=model_str),
        name="browser_agent",
        description="AI agent that automates browser actions via a Chrome Extension",
        instruction=BROWSER_AGENT_INSTRUCTION,
        tools=ALL_TOOLS,
    )

    logger.info(f"Browser agent created: {agent.name} with {len(ALL_TOOLS)} tools")
    return agent
