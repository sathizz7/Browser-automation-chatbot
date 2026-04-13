# Browser Automation Chatbot

Agentic chatbot with browser controls — automatic form-filling, navigation, and DOM interaction for any website. Built with FastAPI, Google ADK, Playwright, and a Chrome Extension frontend.

## Project Structure

```
├── backend/             # FastAPI server + agent loop
│   ├── main.py          # Entry point (uvicorn)
│   ├── requirements.txt # Python dependencies
│   ├── agent/           # LLM orchestration (Google ADK)
│   ├── browser/         # Playwright browser manager & DOM scraper
│   └── ws/              # WebSocket session manager
├── extension/           # Chrome Extension (Manifest V3)
│   ├── manifest.json
│   ├── background.js    # Service worker
│   ├── content_script.js
│   ├── panel/           # Slide-in chat panel
│   └── popup/           # Extension popup
├── docs/
│   └── 101-getting-started.md
├── hld.md               # High-level design
└── prd.md               # Product requirements
```

## Quick Start

```bash
# 1. Install Python dependencies
cd backend
pip install -r requirements.txt
playwright install chromium

# 2. Configure environment
cp .env.example .env
# Edit .env with your LLM API key

# 3. Start the backend
uvicorn main:app --reload --port 8000
```

Then load the `extension/` folder as an unpacked Chrome extension.

See [docs/101-getting-started.md](docs/101-getting-started.md) for full setup and API reference.
