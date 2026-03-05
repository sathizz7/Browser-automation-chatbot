# Custom Scraper Workflow (Gemini + Browser-Use)

This folder is isolated from the main repo code and demonstrates a high-level custom scraping workflow.

## Use case

Scrape product data from `https://books.toscrape.com/` using an AI browser agent and return validated structured output.

## Files

- `main.py`: Local entrypoint and CLI runner.
- `scraper.py`: Agent wiring, Gemini model setup, task prompt.
- `schemas.py`: Pydantic v2 models and custom business validation.
- `.env.example`: Required environment variable template.

## Run

From repository root:

```powershell
uv venv --python 3.11
.\.venv\Scripts\activate
uv sync
```

Create `.env` in the same folder as `main.py` or in repo root:

```env
GOOGLE_API_KEY=your_google_api_key_here
```

Run:

```powershell
uv run python sandbox/custom-scraper-workflow/main.py --query "travel books" --limit 8 --headed
```

Optional:

```powershell
uv run python sandbox/custom-scraper-workflow/main.py --model gemini-flash-latest --max-steps 35 --save output/books.json
```

Retry and fallback:

```powershell
uv run python sandbox/custom-scraper-workflow/main.py `
  --model gemini-flash-latest `
  --fallback-models "gemini-2.5-flash,gemini-1.5-flash" `
  --retries-per-model 3 `
  --retry-backoff-seconds 2
```

Or set env fallback list:

```env
SCRAPER_FALLBACK_MODELS=gemini-2.5-flash,gemini-1.5-flash
```
