/**
 * Content Script — Thin UI Client (Playwright-Powered Backend)
 *
 * This content script is now a THIN CLIENT. All DOM capture and action
 * execution has moved to the Playwright backend (browser/scraper.py
 * and browser/action_handler.py).
 *
 * This script only does:
 * 1. Injects the side panel (Shadow DOM iframe)
 * 2. Forwards agent messages from background.js into the panel
 * 3. Handles panel toggle
 */

// ─────────────────────────────────────────────
// 1. MESSAGE HANDLER (from Background)
// ─────────────────────────────────────────────

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    switch (message.type) {
        case "toggle_panel":
            toggleAgentPanel();
            sendResponse({ toggled: true });
            break;

        // Forward all agent/status messages into the panel iframe
        case "agent_message":
        case "agent_status":
        case "agent_stream":
        case "agent_stream_end":
        case "system":
        case "error":
        case "connection_status":
            forwardToPanelFrame(message);
            sendResponse({ received: true });
            break;

        default:
            sendResponse({ received: true });
    }
    return true;
});


// ─────────────────────────────────────────────
// 2. INJECTED SIDE PANEL (Shadow DOM)
// ─────────────────────────────────────────────

let panelHost = null;
let panelShadow = null;
let panelFrame = null;
let panelOpen = false;

/**
 * Inject the side panel into the page using Shadow DOM for CSS isolation.
 * Uses an <iframe> pointing to panel.html for full script + style isolation.
 */
function injectPanel() {
    if (panelHost) return; // already injected

    // Create host element
    panelHost = document.createElement("div");
    panelHost.id = "__browser-agent-host__";
    panelHost.style.cssText = `
        all: initial;
        position: fixed;
        top: 0;
        right: 0;
        width: 0;
        height: 100vh;
        z-index: 2147483647;
        pointer-events: none;
    `;

    // Attach Shadow DOM
    panelShadow = panelHost.attachShadow({ mode: "closed" });

    // Create iframe pointing to panel.html
    panelFrame = document.createElement("iframe");
    panelFrame.src = chrome.runtime.getURL("panel/panel.html");
    panelFrame.style.cssText = `
        position: fixed;
        top: 0;
        right: 0;
        width: 0;
        height: 100vh;
        border: none;
        background: transparent;
        pointer-events: none;
        transition: width 0.25s cubic-bezier(0.4, 0, 0.2, 1);
        z-index: 2147483647;
    `;

    panelShadow.appendChild(panelFrame);
    document.documentElement.appendChild(panelHost);
}

/**
 * Toggle the side panel open/closed.
 */
function toggleAgentPanel() {
    if (!panelHost) injectPanel();

    panelOpen = !panelOpen;

    if (panelOpen) {
        panelHost.style.pointerEvents = "all";
        panelFrame.style.width = "420px";
        panelFrame.style.pointerEvents = "all";
    } else {
        panelHost.style.pointerEvents = "none";
        panelFrame.style.width = "0";
        panelFrame.style.pointerEvents = "none";
    }
}

/**
 * Forward messages from background into the panel iframe.
 */
function forwardToPanelFrame(message) {
    if (panelFrame && panelFrame.contentWindow) {
        panelFrame.contentWindow.postMessage(message, "*");
    }
}

// Inject on load
if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", injectPanel);
} else {
    injectPanel();
}

console.log("[CS] Browser Agent panel loaded on:", window.location.href);
