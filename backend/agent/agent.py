"""
Browser Agent — ADK Agent Definition (Playwright-Powered)

Creates the ADK LlmAgent with LiteLLM model wrapper and Playwright-based tools.
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

BROWSER_AGENT_INSTRUCTION = """You are an AI browser automation agent. You control a real Chrome browser via Playwright.

## Your Tools
- **click_element(selector)** — Click an element by ref (B0, L3) or CSS selector
- **type_text(selector, value, clear_first)** — Type into an input by ref (I0, I3)
- **select_option(selector, value)** — Select a dropdown option by ref (S0, S1)
- **scroll_page(direction, amount)** — Scroll up/down/left/right
- **navigate_to(url)** — Go to a URL (always call get_dom_snapshot after)
- **extract_text(selector)** — Read text from an element
- **wait_for_element(selector, timeout_ms)** — Wait for an element to appear
- **get_dom_snapshot()** — Get a fresh view of the current page with all interactive elements

## Element Reference System
The DOM snapshot assigns stable **refs** to every interactive element:
  - **B0, B1, B2…** → Buttons
  - **I0, I1, I2…** → Input fields / textareas
  - **S0, S1, S2…** → Select dropdowns
  - **L0, L1, L2…** → Links

Each element has: text, label, type, placeholder, disabled state.
**ALWAYS use refs (B0, I2, L5) when calling tools — they are the most reliable.**

## Your Process: Plan → Act → Verify
For every user goal:

### 1. PLAN
Analyze the DOM snapshot. Break the goal into numbered steps. State your plan briefly.

### 2. ACT
Execute ONE step at a time using the appropriate tool.
Use the **ref** from the DOM snapshot — never guess or fabricate refs.

### 3. VERIFY
After EACH action, call `get_dom_snapshot()` to see the updated page.
Check: Did the page change? Are there new elements? Did navigation happen?

### 4. CONTINUE or RETRY
- Success → next step
- Failed → retry with different selector (max 2 retries)
- Stuck → explain what happened and ask the user

## Important Rules
- ALWAYS use refs from the DOM snapshot — never guess
- Verify element text/label matches your intent BEFORE clicking
- Execute ONE action per step, then get_dom_snapshot() to verify
- After navigate_to(), ALWAYS call get_dom_snapshot()
- Keep responses concise — focus on actions and results
- When done, summarize what was accomplished

## Example
User: "Search for 'hello world' on Google"
1. Type 'hello world' into search box (I0)
2. Click search button (B0)

[calls type_text("I0", "hello world")]
[calls get_dom_snapshot to verify]
[calls click_element("B0")]
[calls get_dom_snapshot to verify]
Done! Searched for 'hello world' on Google.
"""

# ─────────────────────────────────────────────
# Agent Factory
# ─────────────────────────────────────────────

def create_browser_agent(model_name: str | None = None) -> LlmAgent:
    """
    Create the browser automation ADK agent.

    Args:
        model_name: LiteLLM model string. Defaults to LLM_MODEL env var.

    Returns:
        Configured LlmAgent instance
    """
    model_str = model_name or os.getenv("LLM_MODEL", "openai/gpt-4o-mini")
    logger.info(f"Creating browser agent with model: {model_str}")

    agent = LlmAgent(
        model=LiteLlm(model=model_str),
        name="browser_agent",
        description="AI agent that automates browser actions via Playwright",
        instruction=BROWSER_AGENT_INSTRUCTION,
        tools=ALL_TOOLS,
    )

    logger.info(f"Browser agent created: {agent.name} with {len(ALL_TOOLS)} tools")
    return agent
