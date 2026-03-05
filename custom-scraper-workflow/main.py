from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv

from scraper import ScraperConfig, run_scraper


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description='High-level custom scraper workflow using Browser-Use + Gemini + Pydantic validation.'
	)
	parser.add_argument(
		'--query',
		default='travel books',
		help='Natural language query used to focus product collection.',
	)
	parser.add_argument('--limit', type=int, default=8, help='How many products to collect.')
	parser.add_argument('--model', default='gemini-flash-latest', help='Gemini model name.')
	parser.add_argument(
		'--fallback-models',
		default='',
		help='Comma-separated fallback Gemini models. Example: "gemini-2.5-flash,gemini-1.5-flash"',
	)
	parser.add_argument('--retries-per-model', type=int, default=2, help='Retries to run per model before fallback.')
	parser.add_argument(
		'--retry-backoff-seconds',
		type=float,
		default=1.5,
		help='Base retry backoff in seconds (multiplied by attempt number).',
	)
	parser.add_argument('--max-steps', type=int, default=30, help='Max agent steps.')
	parser.add_argument('--headed', action='store_true', help='Show browser UI while running.')
	parser.add_argument(
		'--save',
		default='output/scrape_result.json',
		help='Output path for validated JSON result.',
	)
	return parser.parse_args()


def print_summary(result_json: dict) -> None:
	items = result_json.get('items', [])
	print('\nValidated scrape completed')
	print(f'Use case: {result_json.get("use_case")}')
	print(f'Query: {result_json.get("query")}')
	print(f'Source: {result_json.get("source_url")}')
	print(f'Items: {len(items)}')
	print('\nTop items:')
	for index, item in enumerate(items[:5], start=1):
		print(
			f'{index}. {item["title"]} | {item["price_raw"]} | '
			f'rating={item["rating"]} | in_stock={item["in_stock"]}'
		)


async def _run() -> int:
	load_dotenv()
	args = parse_args()

	config = ScraperConfig(
		query=args.query,
		limit=args.limit,
		model=args.model,
		fallback_models=tuple([m.strip() for m in args.fallback_models.split(',') if m.strip()]),
		retries_per_model=max(1, args.retries_per_model),
		retry_backoff_seconds=max(0.0, args.retry_backoff_seconds),
		headless=not args.headed,
		max_steps=args.max_steps,
	)
	result = await run_scraper(config)
	result_json = result.model_dump(mode='json')
	print_summary(result_json)

	output_path = Path(args.save)
	output_path.parent.mkdir(parents=True, exist_ok=True)
	output_path.write_text(json.dumps(result_json, indent=2), encoding='utf-8')
	print(f'\nSaved validated output: {output_path}')
	return 0


def main() -> None:
	raise SystemExit(asyncio.run(_run()))


if __name__ == '__main__':
	main()
