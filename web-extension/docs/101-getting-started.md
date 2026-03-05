# Browser Automation Agent — 101 Getting Started Guide

## Prerequisites

- Python 3.11+ installed on Windows
- Google Chrome installed
- Node.js (optional, only for extension development)
- An `.env` file with your LLM API key (see Step 1)

---

## Step 1: Configure the Backend

Create a `.env` file inside the `backend/` folder:

```env
# Pick your LLM provider (LiteLLM format)
LLM_MODEL=openai/gpt-4o-mini
OPENAI_API_KEY=sk-...

# OR use Gemini
# LLM_MODEL=gemini/gemini-2.5-flash
# GEMINI_API_KEY=AI...
```

---

## Step 2: Install Dependencies

In a **Windows PowerShell** terminal:

```powershell
cd D:\Mini-proj\ghmc\Browser-automation-chatbot\web-extension\backend

# Create and activate virtual environment (first time only)
python -m venv env
.\env\Scripts\activate

# Install Python packages
pip install -r requirements.txt

# Install Playwright + Chromium browser binary (first time only)
playwright install chromium
```

---

## Step 3: Start the Backend Server

```powershell
uvicorn main:app --reload --port 8000
```

You should see:
```
✅ Playwright BrowserManager initialized
✅ ADK Agent + Orchestrator ready!
INFO: Uvicorn running on http://127.0.0.1:8000
```

Check it's alive:
```powershell
curl http://localhost:8000/health
```

---

## Mode A: Headless API Mode (No Browser Window)

This is the simplest way to run automation. Playwright launches an **invisible** Chromium internally.

### Step A1: Run a task

```powershell
curl -X POST http://localhost:8000/api/run `
  -H "Content-Type: application/json" `
  -d '{"goal": "Search for hello world on Google", "url": "https://google.com"}'
```

#### Parameters:
| Field | Required | Description |
|---|---|---|
| `goal` | ✅ | What to automate in plain English |
| `url` | ❌ | Starting URL to navigate to first |

#### Response:
```json
{
  "success": true,
  "result": "Done! I searched for 'hello world' on Google...",
  "url": "https://www.google.com/search?q=hello+world"
}
```

#### What happens internally:
```
POST /api/run
     │
     ▼
Playwright launches invisible Chromium
     │
     ▼
Orchestrator scrapes the page (DOM + screenshot)
     │
     ▼
ADK Agent + LLM plans actions
     │
     ▼
Playwright executes: click / type / scroll / navigate
     │
     ▼
Returns the agent's summary response
```

---

## Mode B: CDP Mode (Watch Your Own Chrome)

CDP mode connects Playwright to your **existing Chrome window** so you can watch every action happen in real time.

### Step B1: Start Chrome with Remote Debugging

Open a **new PowerShell window** and run:

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222
```

> ⚠️ Chrome must be fully closed before running this command. Check the system tray.

### Step B2: Connect the backend to Chrome

```powershell
curl -X POST http://localhost:8000/api/connect `
  -H "Content-Type: application/json" `
  -d '{"cdp_endpoint": "http://localhost:9222"}'
```

Success response:
```json
{"success": true, "mode": "cdp", "url": "chrome://newtab/", "title": "New Tab"}
```

### Step B3: Run a task

```powershell
curl -X POST http://localhost:8000/api/run `
  -H "Content-Type: application/json" `
  -d '{"goal": "Go to wikipedia.org and search for Playwright"}'
```

👁️ **Watch your Chrome browser** — you'll see it navigate and type automatically!

> **WSL Users:** If your backend runs in WSL, the server auto-detects WSL and rewrites `localhost` to your Windows IP. Just use `http://localhost:9222` and it will work automatically.

---

## Mode C: Chrome Extension + Panel UI

The extension adds a **slide-in chat panel** to every webpage. You type your goal in the panel, and the backend automates the browser.

### Step C1: Load the Extension

1. Open Chrome and go to `chrome://extensions/`
2. Enable **Developer mode** (top-right toggle)
3. Click **Load unpacked**
4. Select the folder: `web-extension/extension/`
5. You should see **"Browser Automation Agent"** appear in the list

### Step C2: Make sure the backend is running

```powershell
uvicorn main:app --reload --port 8000
```

### Step C3: Start Chrome with debugging (to watch navigation)

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222
```

Then connect:
```powershell
curl -X POST http://localhost:8000/api/connect `
  -H "Content-Type: application/json" `
  -d '{"cdp_endpoint": "http://localhost:9222"}'
```

### Step C4: Open the Panel

Click the **extension icon** in the Chrome toolbar (top-right).
A chat panel slides in from the right side of any page.

### Step C5: Type a goal and submit

Type your automation goal in the chat input, for example:
```
Search for "GHMC Hyderabad" on Google and find the official website link
```

Press **Enter** or click **Send**.

### How status updates appear in the panel:
```
📸 Analyzing page...
📋 Planning...
🖱️ Clicking L0
✅ Step 1 done: click_element
📸 Analyzing page...
⌨️ Typing "GHMC Hyderabad" into I0
✅ Step 2 done: type_text
...
Done! Here's what I found...
```

---

## API Reference

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Check server + browser status |
| `/api/run` | POST | Run a goal (headless or current browser) |
| `/api/launch` | POST | Launch a new headless Chromium |
| `/api/connect` | POST | Connect to Chrome via CDP |
| `/ws` | WebSocket | Extension panel connection for streaming |

---

## Quick Test Script

Run this to verify everything works:

```powershell
cd D:\Mini-proj\ghmc\Browser-automation-chatbot\web-extension\backend

# Test headless
python test_playwright.py --headless

# Test CDP (Chrome must be running with --remote-debugging-port=9222)
python test_playwright.py --cdp

# Test both
python test_playwright.py --all
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `libnspr4.so not found` (WSL) | Run `playwright install-deps chromium` inside WSL |
| `dpkg was interrupted` (WSL) | Run `sudo dpkg --configure -a` then retry |
| CDP connect fails | Make sure Chrome was launched **before** running `/api/connect`. Close all Chrome windows first, then start with `--remote-debugging-port=9222` |
| Extension panel doesn't open | Check `chrome://extensions/` → "Browser Automation Agent" is enabled |
| Extension shows "Backend not running" | Start `uvicorn main:app --reload --port 8000` |
| 149 WebSocket connections | Reload the extension in `chrome://extensions/` — this clears stale connections |
