/**
 * Browser Agent — Side Panel Logic
 *
 * Handles:
 * - FAB toggle & panel open/close
 * - Messaging via chrome.runtime to background
 * - Streaming responses (agent_stream tokens)
 * - Status updates (agent_status messages)
 * - Quick action chips
 * - Pin mode, clear chat
 */

// ─────────────────────────────────────────────
// DOM refs
// ─────────────────────────────────────────────
const fab = document.getElementById('agentFab');
const panel = document.getElementById('agentPanel');
const closeBtn = document.getElementById('closePanel');
const pinBtn = document.getElementById('pinBtn');
const clearBtn = document.getElementById('clearBtn');
const sendBtn = document.getElementById('sendBtn');
const msgInput = document.getElementById('msgInput');
const chatArea = document.getElementById('chatArea');
const statusBadge = document.getElementById('statusBadge');
const statusLabel = document.getElementById('statusLabel');
const panelUrl = document.getElementById('panelUrl');
const fabBadge = document.getElementById('fabBadge');
const chips = document.querySelectorAll('.chip');

// ─────────────────────────────────────────────
// State
// ─────────────────────────────────────────────
let isPinned = false;
let isConnected = false;
let isStreaming = false;
let streamingEl = null; // current streaming bubble element

// ─────────────────────────────────────────────
// Init
// ─────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    // Display current page URL
    updatePageUrl();

    // Check connection status
    chrome.runtime.sendMessage({ type: 'get_status' }, (res) => {
        if (res) updateConnectionStatus(res.connected);
    });

    msgInput.focus();
});

// ─────────────────────────────────────────────
// Panel open / close
// ─────────────────────────────────────────────
fab.addEventListener('click', togglePanel);
closeBtn.addEventListener('click', closePanel);

function togglePanel() {
    if (panel.classList.contains('open')) {
        if (!isPinned) closePanel();
    } else {
        openPanel();
    }
}

function openPanel() {
    panel.classList.add('open');
    fab.classList.add('panel-open');
    fabBadge.classList.remove('show');
    msgInput.focus();
}

function closePanel() {
    panel.classList.remove('open');
    fab.classList.remove('panel-open');
}

// ─────────────────────────────────────────────
// Pin mode
// ─────────────────────────────────────────────
pinBtn.addEventListener('click', () => {
    isPinned = !isPinned;
    pinBtn.classList.toggle('active', isPinned);
    pinBtn.title = isPinned ? 'Unpin panel' : 'Pin panel';
});

// ─────────────────────────────────────────────
// Clear chat
// ─────────────────────────────────────────────
clearBtn.addEventListener('click', () => {
    clearChat();
});

function clearChat() {
    chatArea.innerHTML = '';
    const welcome = document.createElement('div');
    welcome.className = 'chat-welcome';
    welcome.id = 'chatWelcome';
    welcome.innerHTML = `
    <div class="welcome-icon">🤖</div>
    <p class="welcome-title">Browser Agent</p>
    <p class="welcome-sub">Tell me what to do on this page</p>
  `;
    chatArea.appendChild(welcome);
    streamingEl = null;
    isStreaming = false;
}

// ─────────────────────────────────────────────
// Quick action chips
// ─────────────────────────────────────────────
chips.forEach(chip => {
    chip.addEventListener('click', () => {
        const prompt = chip.dataset.prompt;
        if (prompt) sendMessage(prompt);
    });
});

// ─────────────────────────────────────────────
// Send message
// ─────────────────────────────────────────────
sendBtn.addEventListener('click', () => sendMessage());
msgInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

function sendMessage(text) {
    const msg = (text || msgInput.value).trim();
    if (!msg) return;

    // Clear input
    if (!text) msgInput.value = '';

    // Show user message immediately
    appendMessage('user', msg);

    // Disable send while processing
    sendBtn.disabled = true;

    // Send to background → backend
    chrome.runtime.sendMessage(
        { type: 'user_message', payload: { text: msg } },
        (res) => {
            if (chrome.runtime.lastError) {
                appendMessage('error', 'Failed to send. Is the backend running?');
                sendBtn.disabled = false;
            }
        }
    );
}

// ─────────────────────────────────────────────
// Receive messages from content script (via postMessage)
// ─────────────────────────────────────────────
// Note: panel.js runs in an iframe — chrome.runtime.onMessage doesn't fire here.
// The content script forwards messages via postMessage instead.
window.addEventListener("message", (event) => {
    // Accept messages from extension URLs only (security)
    const message = event.data;
    if (!message || typeof message !== "object" || !message.type) return;

    switch (message.type) {

        case "agent_message":
            clearStatusMessage();
            finalizeStream();
            appendMessage("agent", message.payload?.text || "...");
            sendBtn.disabled = false;
            break;

        case "agent_status":
            showStatusMessage(message.payload?.text || "Working...");
            break;

        case "agent_stream":
            handleStreamToken(message.payload?.token || "");
            break;

        case "agent_stream_end":
            finalizeStream();
            sendBtn.disabled = false;
            break;

        case "system":
            appendMessage("system", message.payload?.message || "Connected");
            break;

        case "error":
            clearStatusMessage();
            finalizeStream();
            appendMessage("error", message.payload?.message || "An error occurred");
            sendBtn.disabled = false;
            break;

        case "connection_status":
            updateConnectionStatus(message.payload?.connected);
            break;
    }
});

// ─────────────────────────────────────────────
// UI helpers
// ─────────────────────────────────────────────

function appendMessage(type, text) {
    // Remove welcome screen
    const welcome = document.getElementById('chatWelcome');
    if (welcome) welcome.remove();

    const wrap = document.createElement('div');
    wrap.className = `msg ${type}`;

    const bubble = document.createElement('div');
    bubble.className = 'msg-bubble';
    bubble.textContent = text;

    const time = document.createElement('div');
    time.className = 'msg-time';
    time.textContent = now();

    wrap.appendChild(bubble);
    if (type !== 'system') wrap.appendChild(time);
    chatArea.appendChild(wrap);
    scrollBottom();
}

// ─── Status messages (transient, replaced each update) ───
let statusEl = null;

function showStatusMessage(text) {
    clearStatusMessage();

    // Remove welcome if needed
    const welcome = document.getElementById('chatWelcome');
    if (welcome) welcome.remove();

    statusEl = document.createElement('div');
    statusEl.className = 'msg status';
    statusEl.id = 'agentStatusMsg';

    const bubble = document.createElement('div');
    bubble.className = 'msg-bubble';
    bubble.textContent = text;

    statusEl.appendChild(bubble);
    chatArea.appendChild(statusEl);
    scrollBottom();
}

function clearStatusMessage() {
    if (statusEl) {
        statusEl.remove();
        statusEl = null;
    }
}

// ─── Streaming ───
function startStream() {
    // Remove welcome if needed
    const welcome = document.getElementById('chatWelcome');
    if (welcome) welcome.remove();

    clearStatusMessage();

    const wrap = document.createElement('div');
    wrap.className = 'msg agent';

    const bubble = document.createElement('div');
    bubble.className = 'msg-bubble stream-cursor';
    bubble.textContent = '';

    wrap.appendChild(bubble);
    chatArea.appendChild(wrap);
    scrollBottom();

    streamingEl = bubble;
    isStreaming = true;
    return bubble;
}

function handleStreamToken(token) {
    if (!isStreaming || !streamingEl) {
        startStream();
    }
    streamingEl.textContent += token;
    scrollBottom();
}

function finalizeStream() {
    if (streamingEl) {
        streamingEl.classList.remove('stream-cursor');
        // Add timestamp
        const time = document.createElement('div');
        time.className = 'msg-time';
        time.textContent = now();
        streamingEl.parentElement?.appendChild(time);
        streamingEl = null;
    }
    isStreaming = false;
}

// ─── Connection status ───
function updateConnectionStatus(connected) {
    isConnected = connected;
    if (connected) {
        statusBadge.classList.add('online');
        statusLabel.textContent = 'Online';
    } else {
        statusBadge.classList.remove('online');
        statusLabel.textContent = 'Offline';
    }
}

// ─── Page URL ───
function updatePageUrl() {
    const url = window.location.href;
    try {
        const host = new URL(url).hostname;
        panelUrl.textContent = host;
        panelUrl.title = url;
    } catch {
        panelUrl.textContent = url.slice(0, 40);
    }
}

// ─── Utility ───
function scrollBottom() {
    chatArea.scrollTop = chatArea.scrollHeight;
}

function now() {
    return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}
