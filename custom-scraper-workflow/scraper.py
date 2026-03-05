from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

from browser_use import Agent, Browser, ChatGoogle
from pydantic import ValidationError

from schemas import ScrapeResult


@dataclass(slots=True)
class ScraperConfig:
	query: str
	limit: int = 8
	model: str = 'gemini-flash-latest'
	fallback_models: tuple[str, ...] = ()
	retries_per_model: int = 2
	retry_backoff_seconds: float = 1.5
	headless: bool = True
	max_steps: int = 30


def build_task(config: ScraperConfig) -> str:
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


def _build_model_chain(config: ScraperConfig) -> list[str]:
	models: list[str] = [config.model]
	for model_name in config.fallback_models:
		normalized = model_name.strip()
		if normalized and normalized not in models:
			models.append(normalized)
	return models


def _parse_fallback_models_from_env() -> tuple[str, ...]:
	raw = os.getenv('SCRAPER_FALLBACK_MODELS', '')
	if not raw.strip():
		return ()
	return tuple([chunk.strip() for chunk in raw.split(',') if chunk.strip()])


async def _run_agent_once(config: ScraperConfig, api_key: str, model_name: str) -> ScrapeResult:
	llm = ChatGoogle(model=model_name, api_key=api_key)
	browser = Browser(headless=config.headless)
	agent = Agent(
		task=build_task(config),
		llm=llm,
		browser=browser,
		output_model_schema=ScrapeResult,
		max_actions_per_step=5,
	)

	history = await agent.run(max_steps=config.max_steps)
	parsed = history.structured_output
	if parsed is not None:
		return ScrapeResult.model_validate(parsed.model_dump())

	final_result = history.final_result()
	if not final_result:
		raise RuntimeError('No final result returned by agent.')
	return ScrapeResult.model_validate_json(final_result)


async def run_scraper(config: ScraperConfig) -> ScrapeResult:
	api_key = os.getenv('GOOGLE_API_KEY')
	if not api_key:
		raise ValueError('GOOGLE_API_KEY is not set')

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

	model_chain = _build_model_chain(config)
	last_error: Exception | None = None
	for model_name in model_chain:
		for attempt in range(1, config.retries_per_model + 1):
			try:
				return await _run_agent_once(config=config, api_key=api_key, model_name=model_name)
			except (RuntimeError, ValidationError, ValueError) as exc:
				last_error = exc
			except Exception as exc:
				last_error = exc

			should_retry_same_model = attempt < config.retries_per_model
			if should_retry_same_model:
				backoff = config.retry_backoff_seconds * attempt
				await asyncio.sleep(backoff)

	error_detail = str(last_error) if last_error else 'unknown error'
	raise RuntimeError(
		f'Scraper failed after retries across models={model_chain}. Last error: {error_detail}'
	)
