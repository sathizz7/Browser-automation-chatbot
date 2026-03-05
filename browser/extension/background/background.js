// background.js — Service worker for Chrome Extension
// Single-port setup: all API calls go to port 8000.
// Switch between dom-agent and browser-use simply by running the desired
// backend on port 8000.

const BACKEND_URL = "http://127.0.0.1:8000";

// Enable side panel to open on extension icon click
chrome.sidePanel
    .setPanelBehavior({ openPanelOnActionClick: true })
    .catch((error) => console.error(error));

// Listen for messages from side panel or content scripts
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {

    // ── API Proxy ────────────────────────────────────────
    if (request.type === "API_CALL") {
        const endpoint = request.endpoint || "";
        const url = `${BACKEND_URL}${endpoint}`;

        const fetchOptions = {
            method: request.method || "POST",
            headers: { "Content-Type": "application/json" },
        };

        if (request.body && request.method !== "GET") {
            fetchOptions.body = JSON.stringify(request.body);
        }

        fetch(url, fetchOptions)
            .then((response) => response.json())
            .then((data) => sendResponse({ success: true, data }))
            .catch((error) => sendResponse({ success: false, error: error.message }));

        return true; // async response
    }

    // ── Dynamic Content Script Injection ─────────────────
    // Called by panel.js before getDomSnapshot() to ensure content.js is present,
    // even if the tab was already open before the extension was loaded/reloaded.
    if (request.type === "INJECT_CONTENT_SCRIPT") {
        chrome.tabs.query({ active: true, currentWindow: true }, ([tab]) => {
            if (!tab || !tab.url || tab.url.startsWith("chrome://")) {
                sendResponse({ success: false, error: "Cannot inject on chrome:// pages" });
                return;
            }
            chrome.scripting.executeScript(
                {
                    target: { tabId: tab.id },
                    files: ["content_scripts/content.js"],
                },
                () => {
                    if (chrome.runtime.lastError) {
                        sendResponse({ success: false, error: chrome.runtime.lastError.message });
                    } else {
                        sendResponse({ success: true });
                    }
                }
            );
        });
        return true; // async response
    }
});
