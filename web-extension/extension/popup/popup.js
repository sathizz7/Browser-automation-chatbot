/**
 * Popup Chat Logic
 * - Sends user messages to background service worker
 * - Receives and renders agent / system / error messages
 * - Manages connection status indicator
 */

// ─────────────────────────────────────────────
// DOM references
// ─────────────────────────────────────────────
const chatArea = document.getElementById("chatArea");
const messageInput = document.getElementById("messageInput");
const sendBtn = document.getElementById("sendBtn");
const statusDot = document.getElementById("statusDot");
const statusText = document.getElementById("statusText");

let isConnected = false;

// ─────────────────────────────────────────────
// Initialize
// ─────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    // Check current connection status
    chrome.runtime.sendMessage({ type: "get_status" }, (response) => {
        if (response) {
            updateConnectionStatus(response.connected);
        }
    });

    // Focus the input
    messageInput.focus();
});

// ─────────────────────────────────────────────
// Send user message
// ─────────────────────────────────────────────
function sendMessage() {
    const text = messageInput.value.trim();
    if (!text) return;

    // Render user message immediately
    appendMessage("user", text);
    messageInput.value = "";

    // Send to background -> backend
    chrome.runtime.sendMessage(
        { type: "user_message", payload: { text } },
        (response) => {
            if (chrome.runtime.lastError) {
                appendMessage("error", "Failed to send message. Is the backend running?");
            }
        }
    );
}

// Send on Enter key
messageInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

// Send on button click
sendBtn.addEventListener("click", sendMessage);

// ─────────────────────────────────────────────
// Receive messages from background
// ─────────────────────────────────────────────
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    switch (message.type) {
        case "agent_message":
            // Remove any pending status message
            removeStatusMessage();
            appendMessage("agent", message.payload?.text || "...");
            break;

        case "agent_status":
            // Real-time status update (Plan/Act/Evaluate indicators)
            showStatusMessage(message.payload?.text || "Working...");
            break;

        case "system":
            appendMessage("system", message.payload?.message || "System event");
            break;

        case "error":
            removeStatusMessage();
            appendMessage("error", message.payload?.message || "An error occurred");
            break;

        case "connection_status":
            updateConnectionStatus(message.payload?.connected);
            break;

        default:
            console.log("[Popup] Unknown message type:", message.type);
    }

    sendResponse({ received: true });
    return true;
});

// ─────────────────────────────────────────────
// UI helpers
// ─────────────────────────────────────────────
function appendMessage(type, text) {
    // Remove welcome message on first real message
    const welcome = chatArea.querySelector(".welcome-message");
    if (welcome) welcome.remove();

    const msgEl = document.createElement("div");
    msgEl.className = `message ${type}`;

    const bubble = document.createElement("div");
    bubble.className = "message-bubble";
    bubble.textContent = text;

    const time = document.createElement("div");
    time.className = "message-time";
    time.textContent = new Date().toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
    });

    msgEl.appendChild(bubble);
    msgEl.appendChild(time);
    chatArea.appendChild(msgEl);

    // Auto scroll
    chatArea.scrollTop = chatArea.scrollHeight;
}

function updateConnectionStatus(connected) {
    isConnected = connected;
    if (connected) {
        statusDot.classList.add("connected");
        statusText.textContent = "Online";
    } else {
        statusDot.classList.remove("connected");
        statusText.textContent = "Offline";
    }
}

// Reconnect on status dot click
statusDot.addEventListener("click", () => {
    if (!isConnected) {
        chrome.runtime.sendMessage({ type: "reconnect" });
        statusText.textContent = "Connecting...";
    }
});

// ─────────────────────────────────────────────
// Status message handling (real-time agent updates)
// ─────────────────────────────────────────────
function showStatusMessage(text) {
    // Remove existing status message first
    removeStatusMessage();

    // Remove welcome message if present
    const welcome = chatArea.querySelector(".welcome-message");
    if (welcome) welcome.remove();

    const statusEl = document.createElement("div");
    statusEl.className = "message agent status-message";
    statusEl.id = "agentStatus";

    const bubble = document.createElement("div");
    bubble.className = "message-bubble status-bubble";
    bubble.textContent = text;

    statusEl.appendChild(bubble);
    chatArea.appendChild(statusEl);
    chatArea.scrollTop = chatArea.scrollHeight;
}

function removeStatusMessage() {
    const existing = document.getElementById("agentStatus");
    if (existing) existing.remove();
}
