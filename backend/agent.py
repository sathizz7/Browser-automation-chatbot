"""Browser automation agent powered by Browser-Use + LiteLLM.

Adapted from custom-scraper-workflow/scraper.py:
  - ChatGoogle → ChatLiteLLM (model-agnostic via LiteLLM)
  - Single scrape task → multi-task routing (read, fill, navigate, checkout, scrape)
  - Allowlist enforcement before any agent action
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import traceback
from dataclasses import dataclass, field
from typing import Any, Optional

from browser_use import Agent, Browser, ChatGoogle
from langchain_community.chat_models import ChatLiteLLM
from pydantic import ValidationError

from allowlist import AllowlistManager
from prompts import build_prompt
from schemas import (
    AutomateResult,
    ScrapeResult,
    StepLog,
    TaskType,
    UserProfile,
)

logger = logging.getLogger(__name__)


# ── Browser-Use compatible LiteLLM wrapper ─────────────────

class BrowserUseLLM(ChatLiteLLM):
    """ChatLiteLLM subclass compatible with browser-use.
    
    browser-use internally:
      1. Reads llm.provider, llm.name, llm.model_name for telemetry
      2. Monkey-patches llm.ainvoke via setattr for token tracking
    
    We use model_config extra='allow' so Pydantic v2 permits arbitrary
    setattr calls (needed for browser-use's monkey-patching).
    """
    provider: str = "openai"
    name: Optional[str] = None
    model_name: Optional[str] = None

    model_config = {"extra": "allow", "arbitrary_types_allowed": True}


# ── Agent Configuration ────────────────────────────────────

@dataclass(slots=True)
class AgentConfig:
    """Configuration for a single agent run."""
    task_type: TaskType
    target_url: str
    user_message: str = ""
    user_profile: UserProfile | None = None
    page_context: dict[str, Any] | None = None

    # LLM settings
    model: str = ""  # LiteLLM format, e.g. "gemini/gemini-2.0-flash"
    fallback_models: tuple[str, ...] = ()
    retries_per_model: int = 2
    retry_backoff_seconds: float = 1.5

    # Browser settings
    headless: bool = True
    max_steps: int = 30


# ── Scraper-compatible config (backward compat) ───────────

@dataclass(slots=True)
class ScraperConfig:
    """Backward-compatible config matching the original scraper interface."""
    query: str
    limit: int = 8
    model: str = ""
    fallback_models: tuple[str, ...] = ()
    retries_per_model: int = 2
    retry_backoff_seconds: float = 1.5
    headless: bool = True
    max_steps: int = 30


# ── Internal helpers ───────────────────────────────────────

def _get_model(model_override: str = "") -> str:
    """Resolve the LLM model string from override → env → default."""
    if model_override:
        return model_override
    return os.getenv("LLM_MODEL", "gemini/gemini-2.0-flash")


def _build_model_chain(primary: str, fallbacks: tuple[str, ...] = ()) -> list[str]:
    """Build ordered list of models to try."""
    models: list[str] = [primary]
    for m in fallbacks:
        normalized = m.strip()
        if normalized and normalized not in models:
            models.append(normalized)
    return models


def _parse_fallback_models_from_env() -> tuple[str, ...]:
    raw = os.getenv("SCRAPER_FALLBACK_MODELS", "")
    if not raw.strip():
        return ()
    return tuple(chunk.strip() for chunk in raw.split(",") if chunk.strip())


def _build_llm(model_name: str) -> BrowserUseLLM:
    """Create a BrowserUseLLM instance for the given model.
    
    Derives provider from the model string, e.g.:
      "gemini/gemini-2.5-flash" → provider="gemini"
      "openai/gpt-4o"           → provider="openai"
    """
    provider = "openai"
    if "/" in model_name:
        provider = model_name.split("/")[0]

    llm = BrowserUseLLM(
        model=model_name,
        provider=provider,
        name=model_name,
        model_name=model_name,
    )
    logger.info(f"Built LLM: model={model_name}, provider={provider}")
    return llm


# ── Core agent runner ──────────────────────────────────────

def _run_agent_sync(
    task_prompt: str,
    model_name: str,
    headless: bool,
    max_steps: int,
    output_schema: type | None = None,
) -> dict[str, Any]:
    """Run Browser-Use agent in a fresh event loop (for Windows subprocess support).
    
    On Windows, uvicorn's event loop doesn't support create_subprocess_exec
    which browser-use needs to launch Chromium. This function creates a new
    ProactorEventLoop in the current thread to get full subprocess support.
    """
    if sys.platform == "win32":
        loop = asyncio.ProactorEventLoop()
    else:
        loop = asyncio.new_event_loop()
    
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(
            _run_agent_core(task_prompt, model_name, headless, max_steps, output_schema)
        )
    finally:
        loop.close()


async def _run_agent_core(
    task_prompt: str,
    model_name: str,
    headless: bool,
    max_steps: int,
    output_schema: type | None = None,
) -> dict[str, Any]:
    """The actual agent execution logic.
    
    Uses browser-use's native ChatGoogle instead of ChatLiteLLM because
    browser-use requires specific structured output formatting for its
    action schema that ChatGoogle handles natively.
    """
    # Extract the bare model name for ChatGoogle
    # e.g. "gemini/gemini-2.5-flash" -> "gemini-2.5-flash"
    bare_model = model_name
    if "/" in model_name:
        bare_model = model_name.split("/", 1)[1]
    
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    llm = ChatGoogle(model=bare_model, api_key=api_key)
    logger.info(f"Agent LLM created OK — ChatGoogle model={bare_model}")
    browser = Browser(headless=headless)

    agent_kwargs: dict[str, Any] = {
        "task": task_prompt,
        "llm": llm,
        "browser": browser,
        "max_actions_per_step": 5,
    }
    if output_schema:
        agent_kwargs["output_model_schema"] = output_schema

    agent = Agent(**agent_kwargs)
    history = await agent.run(max_steps=max_steps)

    # Extract structured output if available
    if output_schema and history.structured_output is not None:
        return history.structured_output.model_dump()

    # Fall back to final_result text
    final = history.final_result()
    if not final:
        raise RuntimeError("No final result returned by agent.")

    return {"raw_result": final}


async def _run_agent_once(
    task_prompt: str,
    model_name: str,
    headless: bool,
    max_steps: int,
    output_schema: type | None = None,
) -> dict[str, Any]:
    """Run Browser-Use agent once, using a separate thread on Windows."""
    import concurrent.futures
    
    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        result = await loop.run_in_executor(
            executor,
            _run_agent_sync,
            task_prompt,
            model_name,
            headless,
            max_steps,
            output_schema,
        )
    return result


async def _run_with_retries(
    task_prompt: str,
    model_chain: list[str],
    retries_per_model: int,
    retry_backoff_seconds: float,
    headless: bool,
    max_steps: int,
    output_schema: type | None = None,
) -> dict[str, Any]:
    """Run agent with model fallbacks and retries."""
    last_error: Exception | None = None

    for model_name in model_chain:
        for attempt in range(1, retries_per_model + 1):
            try:
                logger.info(f"Attempting model={model_name}, attempt={attempt}")
                return await _run_agent_once(
                    task_prompt=task_prompt,
                    model_name=model_name,
                    headless=headless,
                    max_steps=max_steps,
                    output_schema=output_schema,
                )
            except (RuntimeError, ValidationError, ValueError) as exc:
                last_error = exc
                logger.warning(
                    f"Attempt {attempt} with {model_name} failed: {exc}\n"
                    f"Traceback:\n{traceback.format_exc()}"
                )
            except Exception as exc:
                last_error = exc
                logger.error(
                    f"Unexpected error attempt {attempt} with {model_name}: {exc}\n"
                    f"Traceback:\n{traceback.format_exc()}"
                )

            if attempt < retries_per_model:
                backoff = retry_backoff_seconds * attempt
                logger.info(f"Retrying in {backoff}s...")
                await asyncio.sleep(backoff)

    error_detail = str(last_error) if last_error else "unknown error"
    raise RuntimeError(
        f"Agent failed after retries across models={model_chain}. Last error: {error_detail}"
    )


# ── Public API: Generic automation ─────────────────────────

async def run_automation(config: AgentConfig) -> AutomateResult:
    """Run a browser automation task based on the config."""
    # Build the task prompt
    prompt = build_prompt(
        task_type=config.task_type,
        target_url=config.target_url,
        user_message=config.user_message,
        profile=config.user_profile,
        page_context=config.page_context,
    )

    model = _get_model(config.model)
    model_chain = _build_model_chain(model, config.fallback_models)

    try:
        result_data = await _run_with_retries(
            task_prompt=prompt,
            model_chain=model_chain,
            retries_per_model=config.retries_per_model,
            retry_backoff_seconds=config.retry_backoff_seconds,
            headless=config.headless,
            max_steps=config.max_steps,
        )
        return AutomateResult(
            success=True,
            task_type=config.task_type,
            message="Automation completed successfully.",
            extracted_data=result_data,
        )
    except RuntimeError as exc:
        return AutomateResult(
            success=False,
            task_type=config.task_type,
            message="Automation failed.",
            error=str(exc),
        )


# ── Public API: Scraper (backward-compatible) ──────────────

def _build_scrape_task(config: ScraperConfig) -> str:
    """Build scrape prompt matching the original scraper behavior."""
    return f"""
Use case: scrape a structured product dataset from Books to Scrape.

Steps:
1. Navigate to https://books.toscrape.com/
2. Find products relevant to this query: "{config.query}"
3. Collect exactly {config.limit} distinct products from listing pages.
4. For each product, capture:
   - title
   - product_url
   - price_raw (include symbol, e.g. "£51.77")
   - price_value (numeric, e.g. 51.77)
   - currency (GBP)
   - rating (integer 1-5)
   - in_stock (boolean)
   - availability_text
5. Return data using the provided structured output schema only.

Quality rules:
- Prefer products clearly matching the query.
- No duplicate product_url values.
- URLs must be absolute.
- Keep values factual from the page only.
""".strip()


async def run_scraper(config: ScraperConfig) -> ScrapeResult:
    """Run the scraper agent — backward-compatible with original interface.

    This preserves the exact same function signature so existing
    code calling run_scraper(ScraperConfig(...)) continues to work.
    """
    model = _get_model(config.model)

    if not config.fallback_models:
        env_fallbacks = _parse_fallback_models_from_env()
        if env_fallbacks:
            config = ScraperConfig(
                query=config.query,
                limit=config.limit,
                model=config.model,
                fallback_models=env_fallbacks,
                retries_per_model=config.retries_per_model,
                retry_backoff_seconds=config.retry_backoff_seconds,
                headless=config.headless,
                max_steps=config.max_steps,
            )

    model_chain = _build_model_chain(model, config.fallback_models)
    task_prompt = _build_scrape_task(config)

    result_data = await _run_with_retries(
        task_prompt=task_prompt,
        model_chain=model_chain,
        retries_per_model=config.retries_per_model,
        retry_backoff_seconds=config.retry_backoff_seconds,
        headless=config.headless,
        max_steps=config.max_steps,
        output_schema=ScrapeResult,
    )
    return ScrapeResult.model_validate(result_data)
