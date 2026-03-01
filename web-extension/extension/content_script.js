/**
 * Content Script — Runs inside each webpage
 * 
 * Responsibilities:
 * 1. DOM Reader — extracts structured snapshot of visible elements
 * 2. Page Observer — watches for DOM mutations
 * 3. Action Executor — executes browser actions (click, type, scroll, etc.)
 */

// ─────────────────────────────────────────────
// 1. DOM READER
// ─────────────────────────────────────────────

/**
 * Build a unique CSS selector for an element.
 */
function buildSelector(el) {
    if (el.id) return `#${el.id}`;

    // Try data attributes
    const dataAttrs = ["data-testid", "data-cy", "data-id", "name"];
    for (const attr of dataAttrs) {
        const val = el.getAttribute(attr);
        if (val) return `${el.tagName.toLowerCase()}[${attr}="${val}"]`;
    }

    // Build path-based selector
    const parts = [];
    let current = el;
    while (current && current !== document.body && parts.length < 4) {
        let selector = current.tagName.toLowerCase();
        if (current.className && typeof current.className === "string") {
            const cls = current.className.trim().split(/\s+/).filter(c => c && !c.includes(":")).slice(0, 2).join(".");
            if (cls) selector += "." + cls;
        }
        // Add nth-child for disambiguation
        const parent = current.parentElement;
        if (parent) {
            const siblings = Array.from(parent.children).filter(c => c.tagName === current.tagName);
            if (siblings.length > 1) {
                const idx = siblings.indexOf(current) + 1;
                selector += `:nth-child(${idx})`;
            }
        }
        parts.unshift(selector);
        current = current.parentElement;
    }
    return parts.join(" > ");
}

/**
 * Check if an element is visible in the viewport.
 */
function isVisible(el) {
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") {
        return false;
    }
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
}

/**
 * Check if an element is interactive (clickable/typable).
 */
function isInteractive(el) {
    const tag = el.tagName.toLowerCase();
    const interactiveTags = ["a", "button", "input", "select", "textarea", "details", "summary"];
    if (interactiveTags.includes(tag)) return true;
    if (el.getAttribute("role") && ["button", "link", "tab", "menuitem", "checkbox", "radio", "switch", "option"].includes(el.getAttribute("role"))) return true;
    if (el.onclick || el.getAttribute("onclick")) return true;
    if (el.getAttribute("tabindex") && el.getAttribute("tabindex") !== "-1") return true;
    const cursor = window.getComputedStyle(el).cursor;
    if (cursor === "pointer") return true;
    return false;
}

/**
 * Extract text content from an element (direct text, not children).
 */
function getDirectText(el) {
    let text = "";
    for (const node of el.childNodes) {
        if (node.nodeType === Node.TEXT_NODE) {
            text += node.textContent.trim();
        }
    }
    return text.slice(0, 200);  // Cap at 200 chars
}

/**
 * Get structured DOM snapshot of all meaningful visible elements.
 */
function getDOMSnapshot() {
    const SKIP_TAGS = new Set(["script", "style", "noscript", "svg", "path", "meta", "link", "br", "hr"]);
    const elements = [];
    const seen = new Set();

    // Select all potentially interesting elements
    const candidates = document.querySelectorAll(
        "a, button, input, select, textarea, label, h1, h2, h3, h4, h5, h6, " +
        "p, span, div, li, td, th, img, [role], [onclick], [tabindex], form, " +
        "nav, header, footer, main, section, article"
    );

    for (const el of candidates) {
        const tag = el.tagName.toLowerCase();
        if (SKIP_TAGS.has(tag)) continue;
        if (!isVisible(el)) continue;

        // Skip if already processed (dedup)
        if (seen.has(el)) continue;
        seen.add(el);

        const rect = el.getBoundingClientRect();
        const text = getDirectText(el) || el.getAttribute("aria-label") || el.getAttribute("placeholder") || el.getAttribute("title") || el.getAttribute("alt") || "";

        // Skip empty non-interactive elements
        if (!text && !isInteractive(el) && tag !== "img" && tag !== "input") continue;

        const entry = {
            tag: tag,
            text: text.slice(0, 200),
            role: el.getAttribute("role") || "",
            selector: buildSelector(el),
            bounding_box: {
                x: Math.round(rect.x),
                y: Math.round(rect.y),
                width: Math.round(rect.width),
                height: Math.round(rect.height),
            },
            clickable: isInteractive(el),
            visible: true,
            attributes: {},
        };

        // Add relevant attributes
        if (el.type) entry.attributes.type = el.type;
        if (el.name) entry.attributes.name = el.name;
        if (el.value) entry.attributes.value = el.value.slice(0, 100);
        if (el.href) entry.attributes.href = el.href.slice(0, 200);
        if (el.src) entry.attributes.src = el.src.slice(0, 200);
        if (el.checked !== undefined) entry.attributes.checked = el.checked;
        if (el.disabled) entry.attributes.disabled = true;
        if (el.placeholder) entry.attributes.placeholder = el.placeholder;

        elements.push(entry);
    }

    // Sort by position: top-left first
    elements.sort((a, b) => {
        const dy = a.bounding_box.y - b.bounding_box.y;
        if (Math.abs(dy) > 20) return dy;
        return a.bounding_box.x - b.bounding_box.x;
    });

    // Cap at 500 elements to avoid overwhelming the LLM
    return elements.slice(0, 500);
}


// ─────────────────────────────────────────────
// 2. PAGE OBSERVER (MutationObserver)
// ─────────────────────────────────────────────

let mutationTimeout = null;

const observer = new MutationObserver((mutations) => {
    // Debounce: wait 500ms after last mutation before notifying
    clearTimeout(mutationTimeout);
    mutationTimeout = setTimeout(() => {
        chrome.runtime.sendMessage({
            type: "dom_changed",
            payload: { url: window.location.href, timestamp: Date.now() },
        }).catch(() => { });
    }, 500);
});

// Start observing
observer.observe(document.documentElement, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["class", "style", "disabled", "hidden", "aria-hidden"],
});


// ─────────────────────────────────────────────
// 3. ACTION EXECUTOR
// ─────────────────────────────────────────────

/**
 * Find an element by selector, with retries.
 */
async function findElement(selector, timeoutMs = 3000) {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
        const el = document.querySelector(selector);
        if (el) return el;
        await new Promise(r => setTimeout(r, 200));
    }
    return null;
}

/**
 * Execute a browser action dispatched from the backend.
 */
async function executeAction(action) {
    const { tool, args } = action;
    console.log(`[CS] Executing action: ${tool}`, args);

    try {
        switch (tool) {
            case "click": {
                const el = await findElement(args.selector);
                if (!el) return { success: false, error: `Element not found: ${args.selector}` };
                el.scrollIntoView({ behavior: "smooth", block: "center" });
                await new Promise(r => setTimeout(r, 300));
                el.click();
                return { success: true, action: "click", selector: args.selector };
            }

            case "type": {
                const el = await findElement(args.selector);
                if (!el) return { success: false, error: `Element not found: ${args.selector}` };
                el.scrollIntoView({ behavior: "smooth", block: "center" });
                el.focus();
                if (args.clear_first !== false) {
                    el.value = "";
                    el.dispatchEvent(new Event("input", { bubbles: true }));
                }
                // Type character by character for frameworks that listen to input events
                for (const char of args.value) {
                    el.value += char;
                    el.dispatchEvent(new Event("input", { bubbles: true }));
                    el.dispatchEvent(new KeyboardEvent("keydown", { key: char, bubbles: true }));
                    el.dispatchEvent(new KeyboardEvent("keyup", { key: char, bubbles: true }));
                }
                el.dispatchEvent(new Event("change", { bubbles: true }));
                return { success: true, action: "type", selector: args.selector, value: args.value };
            }

            case "scroll": {
                const x = args.x || 0;
                const y = args.y || 0;
                window.scrollBy({ left: x, top: y, behavior: "smooth" });
                return { success: true, action: "scroll", x, y };
            }

            case "navigate": {
                window.location.href = args.url;
                return { success: true, action: "navigate", url: args.url };
            }

            case "extract": {
                const el = await findElement(args.selector);
                if (!el) return { success: false, error: `Element not found: ${args.selector}` };
                return {
                    success: true,
                    action: "extract",
                    selector: args.selector,
                    text: el.textContent.trim().slice(0, 2000),
                    html: el.innerHTML.slice(0, 2000),
                };
            }

            case "wait_for": {
                const timeoutMs = args.timeout_ms || 5000;
                const el = await findElement(args.selector, timeoutMs);
                if (!el) return { success: false, error: `Timeout waiting for: ${args.selector}` };
                return { success: true, action: "wait_for", selector: args.selector };
            }

            default:
                return { success: false, error: `Unknown action: ${tool}` };
        }
    } catch (err) {
        return { success: false, error: `Action error: ${err.message}` };
    }
}


// ─────────────────────────────────────────────
// 4. MESSAGE HANDLER (from Background)
// ─────────────────────────────────────────────

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    console.log("[CS] Received message:", message.type);

    switch (message.type) {
        case "get_dom_snapshot":
            const snapshot = getDOMSnapshot();
            sendResponse({
                success: true,
                url: window.location.href,
                title: document.title,
                element_count: snapshot.length,
                elements: snapshot,
            });
            break;

        case "execute_action":
            // executeAction is async, so we need to handle it properly
            executeAction(message.payload)
                .then((result) => sendResponse(result))
                .catch((err) => sendResponse({ success: false, error: err.message }));
            return true; // Keep message channel open for async response

        default:
            sendResponse({ error: `Unknown message type: ${message.type}` });
    }

    return true;
});

// Notify that content script is loaded
console.log("[CS] Browser Agent content script loaded on:", window.location.href);
