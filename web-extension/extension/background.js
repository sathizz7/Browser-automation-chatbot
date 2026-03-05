/**
 * Background Service Worker — Thin Client (Playwright-Powered Backend)
 *
 * The backend now controls the browser directly via Playwright.
 * This background script only does:
 * 1. WebSocket connection to FastAPI (for sending goals + receiving status)
 * 2. Toolbar icon click → toggle panel
 * 3. Routes agent messages/status to the content script panel
 *
 * REMOVED (now handled by Playwright backend):
 * - DOM snapshot requests
 * - Action execution relay
 * - Navigation handling
 */

const WS_URL = "ws://localhost:8000/ws";
const MAX_RECONNECT_DELAY = 30000;

let ws = null;
let reconnectDelay = 1000;
let sessionId = null;

// ─────────────────────────────────────────────
// WebSocket Connection
// ─────────────────────────────────────────────

function connectWebSocket() {
    if (ws && ws.readyState === WebSocket.OPEN) return;

    console.log("[BG] Connecting to", WS_URL);
    ws = new WebSocket(WS_URL);

    ws.onopen = () => {
        console.log("[BG] WebSocket connected");
        reconnectDelay = 1000;
        broadcastToPanel({ type: "connection_status", payload: { connected: true } });
    };

    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            console.log("[BG] From server:", data.type);

            // Store session ID
            if (data.type === "system" && data.payload?.session_id) {
                sessionId = data.payload.session_id;
            }

            // Forward everything to the panel
            // (agent_message, agent_status, system, error, etc.)
            broadcastToPanel(data);

        } catch (err) {
            console.error("[BG] Failed to parse server message:", err);
        }
    };

    ws.onclose = (event) => {
        console.log("[BG] WebSocket closed:", event.code);
        ws = null;
        broadcastToPanel({ type: "connection_status", payload: { connected: false } });
        scheduleReconnect();
    };

    ws.onerror = () => {
        ws?.close();
    };
}

function scheduleReconnect() {
    setTimeout(() => {
        connectWebSocket();
        reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY);
    }, reconnectDelay);
}

function sendToServer(message) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(message));
    } else {
        broadcastToPanel({
            type: "error",
            payload: { message: "⚠️ Backend not running. Start the backend server." },
        });
        connectWebSocket();
    }
}

// ─────────────────────────────────────────────
// Toolbar icon click → toggle panel
// ─────────────────────────────────────────────

chrome.action.onClicked.addListener(async (tab) => {
    if (!tab?.id) return;
    chrome.tabs.sendMessage(tab.id, { type: "toggle_panel" }).catch(() => { });
});

// ─────────────────────────────────────────────
// Message routing: Panel → Background → Server
// ─────────────────────────────────────────────

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    switch (message.type) {

        case "user_message":
            // Send the user's goal to the backend
            // No DOM snapshot — Playwright scrapes the page directly
            sendToServer({
                type: "user_message",
                payload: {
                    text: message.payload.text,
                    page_context: message.payload.page_context || null,
                },
            });
            sendResponse({ status: "sent" });
            break;

        case "get_status":
            sendResponse({
                connected: ws && ws.readyState === WebSocket.OPEN,
                sessionId,
            });
            break;

        case "reconnect":
            ws?.close();
            connectWebSocket();
            sendResponse({ status: "reconnecting" });
            break;

        default:
            sendToServer(message);
            sendResponse({ status: "forwarded" });
    }

    return true;
});

// ─────────────────────────────────────────────
// Broadcast to panel (via content script)
// ─────────────────────────────────────────────

async function broadcastToPanel(message) {
    try {
        const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
        for (const tab of tabs) {
            if (tab?.id) {
                chrome.tabs.sendMessage(tab.id, message).catch(() => { });
            }
        }
    } catch { }

    // Also forward to any open popup
    chrome.runtime.sendMessage(message).catch(() => { });
}

// ─────────────────────────────────────────────
// Init
// ─────────────────────────────────────────────

connectWebSocket();

// Keep service worker alive
chrome.alarms?.create("keepAlive", { periodInMinutes: 0.4 });
chrome.alarms?.onAlarm.addListener((alarm) => {
    if (alarm.name === "keepAlive") {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: "ping", payload: {} }));
        } else {
            connectWebSocket();
        }
    }
});
