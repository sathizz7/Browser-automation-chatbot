/**
 * Background Service Worker
 * - Maintains persistent WebSocket connection to FastAPI backend
 * - Relays messages between popup <-> backend <-> content script
 * - Routes DOM snapshot requests and action commands to content scripts
 * - Handles reconnection with exponential backoff
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
        reconnectDelay = 1000; // Reset backoff
        // Notify popup that connection is ready
        broadcastToPopup({ type: "connection_status", payload: { connected: true } });
    };

    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            console.log("[BG] Received from server:", data.type);

            // Store session ID from system welcome message
            if (data.type === "system" && data.payload?.session_id) {
                sessionId = data.payload.session_id;
            }

            // Route action commands from server to content script
            if (data.type === "execute_action") {
                sendToContentScript(data.payload);
                return;
            }

            // Route DOM snapshot requests from server to content script
            if (data.type === "request_dom_snapshot") {
                requestDOMSnapshot();
                return;
            }

            // Forward all other server messages to popup
            broadcastToPopup(data);
        } catch (err) {
            console.error("[BG] Failed to parse server message:", err);
        }
    };

    ws.onclose = (event) => {
        console.log("[BG] WebSocket closed:", event.code, event.reason);
        ws = null;
        broadcastToPopup({ type: "connection_status", payload: { connected: false } });
        scheduleReconnect();
    };

    ws.onerror = (error) => {
        console.error("[BG] WebSocket error:", error);
        ws?.close();
    };
}

function scheduleReconnect() {
    console.log(`[BG] Reconnecting in ${reconnectDelay}ms...`);
    setTimeout(() => {
        connectWebSocket();
        reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY);
    }, reconnectDelay);
}

function sendToServer(message) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(message));
        console.log("[BG] Sent to server:", message.type);
    } else {
        console.warn("[BG] WebSocket not connected, cannot send");
        broadcastToPopup({
            type: "error",
            payload: { message: "Not connected to backend. Retrying..." },
        });
        connectWebSocket();
    }
}

// ─────────────────────────────────────────────
// Message Routing: Popup <-> Background <-> Server
// ─────────────────────────────────────────────

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    console.log("[BG] Message from popup/content:", message.type);

    switch (message.type) {
        case "user_message":
            // Grab DOM snapshot first, then send both to backend
            requestDOMSnapshot().then((snapshot) => {
                sendToServer({
                    type: "user_message",
                    payload: {
                        text: message.payload.text,
                        page_context: snapshot || null,
                    },
                });
                sendResponse({ status: "sent" });
            });
            return true; // async

        case "get_dom_snapshot":
            // Popup requested a snapshot directly
            requestDOMSnapshot().then((snapshot) => {
                sendResponse(snapshot);
            });
            return true; // async

        case "get_status":
            // Return connection status
            sendResponse({
                connected: ws && ws.readyState === WebSocket.OPEN,
                sessionId: sessionId,
            });
            break;

        case "reconnect":
            // Force reconnect
            ws?.close();
            connectWebSocket();
            sendResponse({ status: "reconnecting" });
            break;

        case "dom_changed":
            // Content script reports DOM mutation
            console.log("[BG] DOM changed on:", message.payload?.url);
            sendResponse({ received: true });
            break;

        case "action_result":
            // Content script returns action execution result
            console.log("[BG] Action result:", message.payload);
            sendToServer({
                type: "action_result",
                payload: message.payload,
            });
            sendResponse({ received: true });
            break;

        default:
            // Forward any other messages to server
            sendToServer(message);
            sendResponse({ status: "forwarded" });
    }

    return true; // Keep message channel open for async response
});

// ─────────────────────────────────────────────
// Broadcast to Popup
// ─────────────────────────────────────────────

function broadcastToPopup(message) {
    chrome.runtime.sendMessage(message).catch(() => {
        // Popup might be closed — that's fine
    });
}

// ─────────────────────────────────────────────
// Content Script Communication
// ─────────────────────────────────────────────

/**
 * Request DOM snapshot from the active tab's content script.
 * Returns the snapshot data or null on failure.
 */
async function requestDOMSnapshot() {
    try {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (!tab?.id) {
            console.warn("[BG] No active tab found");
            return null;
        }
        return new Promise((resolve) => {
            chrome.tabs.sendMessage(tab.id, { type: "get_dom_snapshot" }, (response) => {
                if (chrome.runtime.lastError) {
                    console.warn("[BG] Content script not ready:", chrome.runtime.lastError.message);
                    resolve(null);
                } else {
                    resolve(response);
                }
            });
        });
    } catch (err) {
        console.error("[BG] Error requesting DOM snapshot:", err);
        return null;
    }
}

/**
 * Send an action command to the active tab's content script.
 */
async function sendToContentScript(actionPayload) {
    try {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (!tab?.id) {
            console.warn("[BG] No active tab for action");
            sendToServer({ type: "action_result", payload: { success: false, error: "No active tab" } });
            return;
        }
        chrome.tabs.sendMessage(tab.id, { type: "execute_action", payload: actionPayload }, (result) => {
            if (chrome.runtime.lastError) {
                sendToServer({
                    type: "action_result",
                    payload: { success: false, error: chrome.runtime.lastError.message },
                });
            } else {
                sendToServer({ type: "action_result", payload: result });
            }
        });
    } catch (err) {
        sendToServer({ type: "action_result", payload: { success: false, error: err.message } });
    }
}

// ─────────────────────────────────────────────
// Initialize on service worker start
// ─────────────────────────────────────────────

connectWebSocket();

// Keep the service worker alive by setting up an alarm
chrome.alarms?.create("keepAlive", { periodInMinutes: 0.5 });
chrome.alarms?.onAlarm.addListener((alarm) => {
    if (alarm.name === "keepAlive") {
        // Ping to keep WS alive
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: "ping", payload: {} }));
        } else {
            connectWebSocket();
        }
    }
});
