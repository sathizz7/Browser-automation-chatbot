// content.js — DOM Reader + Executor + State Observer
// Runs in the context of the active web page.
// Three responsibilities:
//   1. Element Abstraction Layer: extracts interactive elements with stable IDs
//   2. DOM Action Executor: executes actions visibly with human-like events
//   3. State Observer: waits for DOM stability between actions

(function () {
    "use strict";

    // ── Configuration (fetched from dom-agent /config) ──────
    let CONFIG = {
        maxElements: 50,
        typeDelayMinMs: 50,
        typeDelayMaxMs: 130,
        domSettleTimeoutMs: 3000,
        networkIdleMs: 500,
        mutationSettleMs: 300,
    };

    // ── Utility ─────────────────────────────────────────────

    function delay(ms) {
        return new Promise((resolve) => setTimeout(resolve, ms));
    }

    function randomDelay(min, max) {
        return delay(min + Math.random() * (max - min));
    }

    // ── 1. PERCEPTION ENGINE (Element Abstraction + Ranking + Context) ────

    /**
     * Simple non-crypto hash for generating stable element IDs.
     * Uses djb2 algorithm — fast, deterministic, low collision.
     */
    function hashString(str) {
        let hash = 5381;
        for (let i = 0; i < str.length; i++) {
            hash = ((hash << 5) + hash + str.charCodeAt(i)) & 0xffffffff;
        }
        return (hash >>> 0).toString(16).substring(0, 6);
    }

    /**
     * Generate a stable, human-readable element ID that survives DOM reorderings.
     * Format: "tag_readableHint_hash", e.g. "input_mobile_3a8f2c" or "btn_send_otp_7d2ea1"
     */
    function generateStableId(el) {
        const tag = el.tagName.toLowerCase();
        const name = el.name || "";
        const label = findLabel(el);
        const placeholder = el.placeholder || "";
        const text = (el.innerText || el.textContent || "").trim().substring(0, 50);
        const ariaLabel = el.getAttribute("aria-label") || "";

        // Build hash from stable properties (NOT affected by DOM order)
        const hashInput = [tag, name, label, placeholder, text, ariaLabel].join("|");
        const hash = hashString(hashInput);

        // Build a readable prefix
        const hint = (label || placeholder || text || name || tag)
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, "_")
            .replace(/^_|_$/g, "")
            .substring(0, 20);

        const prefix = tag === "input" || tag === "textarea" ? "input" :
            tag === "button" || (tag === "input" && el.type === "submit") ? "btn" :
                tag === "select" ? "sel" :
                    tag === "a" ? "link" : tag;

        return `${prefix}_${hint || "el"}_${hash}`;
    }

    /**
     * Check if an element is truly visible on the page.
     */
    function isVisible(el) {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") {
            return false;
        }
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    }

    /**
     * Check if an element is currently in (or near) the viewport.
     */
    function isInViewport(el) {
        const rect = el.getBoundingClientRect();
        const margin = 200; // pixels of margin around viewport
        return (
            rect.top < (window.innerHeight + margin) &&
            rect.bottom > -margin &&
            rect.left < (window.innerWidth + margin) &&
            rect.right > -margin
        );
    }

    /**
     * Find the label text associated with an element.
     */
    function findLabel(el) {
        // Explicit label[for]
        if (el.id) {
            const label = document.querySelector(`label[for="${el.id}"]`);
            if (label) return label.innerText.trim();
        }
        // Parent label
        const parentLabel = el.closest("label");
        if (parentLabel) return parentLabel.innerText.trim();
        // aria-label
        if (el.getAttribute("aria-label")) return el.getAttribute("aria-label");
        // Nearby text (previous sibling)
        const prev = el.previousElementSibling;
        if (prev && prev.tagName === "LABEL") return prev.innerText.trim();
        return "";
    }

    /**
     * Find semantic context around an element:
     * - Parent form title / legend
     * - Closest section heading (h1-h4)
     * - Fieldset legend
     */
    function findContext(el) {
        const parts = [];

        // 1. Parent <form> title — check for a heading inside the form
        const form = el.closest("form");
        if (form) {
            const formHeading = form.querySelector("h1, h2, h3, h4, legend, .form-title, .card-header");
            if (formHeading) parts.push(formHeading.innerText.trim().substring(0, 60));
        }

        // 2. Fieldset legend
        const fieldset = el.closest("fieldset");
        if (fieldset) {
            const legend = fieldset.querySelector("legend");
            if (legend) parts.push(legend.innerText.trim().substring(0, 40));
        }

        // 3. Walk up to find nearest preceding heading (h1-h4)
        let node = el;
        for (let i = 0; i < 15 && node; i++) {
            node = node.previousElementSibling || node.parentElement;
            if (node && /^H[1-4]$/.test(node.tagName)) {
                parts.push(node.innerText.trim().substring(0, 60));
                break;
            }
        }

        // 4. Page title fallback (if we found nothing)
        if (parts.length === 0) {
            parts.push(document.title.substring(0, 60));
        }

        // Deduplicate and join with arrow
        return [...new Set(parts)].join(" → ");
    }

    /**
     * Detect if an input is likely an OTP field (rule-based).
     */
    function isOtpField(el) {
        const hints = [
            el.name || "",
            el.id || "",
            el.placeholder || "",
            el.getAttribute("aria-label") || "",
        ].join(" ").toLowerCase();

        if (hints.includes("otp") || hints.includes("verification") || hints.includes("verify")) {
            return true;
        }
        const maxLen = el.maxLength;
        const pattern = el.getAttribute("pattern");
        if (maxLen >= 4 && maxLen <= 8 && el.type === "text") return true;
        if (pattern && pattern.includes("[0-9]")) return true;
        return false;
    }

    /**
     * Score an element's relevance to the user's intent message.
     * Higher score = more likely to be what the user wants to interact with.
     */
    function scoreElement(el, metadata, userMessage) {
        let score = 0;
        if (!userMessage) return score;

        const keywords = userMessage.toLowerCase().split(/\s+/).filter(w => w.length > 2);
        const label = (metadata.label || "").toLowerCase();
        const placeholder = (metadata.placeholder || "").toLowerCase();
        const text = (metadata.text || "").toLowerCase();
        const name = (metadata.name || "").toLowerCase();

        for (const kw of keywords) {
            if (label.includes(kw)) score += 5;
            if (placeholder.includes(kw)) score += 4;
            if (text.includes(kw)) score += 3;
            if (name.includes(kw)) score += 2;
        }

        // Bonus for viewport proximity
        if (isInViewport(el)) score += 2;

        // Bonus for clickable elements
        const tag = el.tagName.toLowerCase();
        if (tag === "button" || tag === "a" || el.type === "submit") score += 1;

        // Bonus for OTP fields if user mentions OTP
        if (metadata.otp_detected && userMessage.toLowerCase().includes("otp")) score += 6;

        return score;
    }

    /**
     * Build a stable CSS selector for an element (internal use — never sent to LLM).
     */
    function buildSelector(el) {
        if (el.id) return `#${CSS.escape(el.id)}`;
        if (el.name) return `${el.tagName.toLowerCase()}[name="${CSS.escape(el.name)}"]`;
        if (el.getAttribute("aria-label")) {
            return `${el.tagName.toLowerCase()}[aria-label="${CSS.escape(el.getAttribute("aria-label"))}"]`;
        }
        if (el.getAttribute("data-testid")) {
            return `[data-testid="${CSS.escape(el.getAttribute("data-testid"))}"]`;
        }
        const parent = el.parentElement;
        if (parent) {
            const siblings = Array.from(parent.querySelectorAll(`:scope > ${el.tagName.toLowerCase()}`));
            const index = siblings.indexOf(el) + 1;
            return `${buildSelector(parent)} > ${el.tagName.toLowerCase()}:nth-of-type(${index})`;
        }
        return el.tagName.toLowerCase();
    }

    /**
     * Extract all interactive elements from the page with stable IDs,
     * context enrichment, and intent-based ranking.
     *
     * @param {string} userMessage — (optional) user's task description for ranking
     * @returns {{ [stableId]: { metadata + _selector + _domRef } }}
     */
    function extractElements(userMessage = "") {
        const selectors = "input, button, select, textarea, a[href]";
        const allElements = document.querySelectorAll(selectors);
        const candidates = [];
        const seenIds = new Set();

        for (const el of allElements) {
            if (!isVisible(el)) continue;
            const type = el.getAttribute("type") || el.tagName.toLowerCase();
            if (["hidden"].includes(type) && el.tagName === "INPUT") continue;

            let stableId = generateStableId(el);
            // Handle rare hash collisions
            if (seenIds.has(stableId)) {
                stableId += "_" + seenIds.size;
            }
            seenIds.add(stableId);

            const label = findLabel(el);
            const metadata = {
                id: stableId,
                tag: el.tagName.toLowerCase(),
                type: type,
                label: label,
                placeholder: el.placeholder || "",
                text: (el.innerText || el.textContent || "").trim().substring(0, 100),
                name: el.name || "",
                value: el.value || "",
                ariaLabel: el.getAttribute("aria-label") || "",
                context: findContext(el),
                visible: true,
                disabled: el.disabled || false,
                otp_detected: isOtpField(el),
            };

            const score = scoreElement(el, metadata, userMessage);

            candidates.push({
                ...metadata,
                _score: score,
                _selector: buildSelector(el),
                _domRef: el,
            });
        }

        // Sort by score descending, then cap at maxElements
        candidates.sort((a, b) => b._score - a._score);
        const topN = candidates.slice(0, CONFIG.maxElements);

        // Build element map keyed by stable ID
        const elementMap = {};
        for (const entry of topN) {
            elementMap[entry.id] = entry;
        }

        return elementMap;
    }

    /**
     * Build the DOM snapshot payload for the backend (strips internal refs).
     */
    function buildSnapshot(elementMap) {
        const elements = Object.values(elementMap).map((e) => {
            const { _selector, _domRef, ...rest } = e;
            return rest;
        });
        return {
            elements,
            page_url: window.location.href,
            page_title: document.title,
        };
    }

    // ── 2. DOM ACTION EXECUTOR ──────────────────────────────

    /** Store the current element map for action resolution */
    let currentElementMap = {};

    /**
     * Resolve a stable element_id to a live DOM element.
     * Tries: cached DOM ref → CSS selector → re-extract and match by ID.
     */
    function resolveElement(elementId) {
        const entry = currentElementMap[elementId];
        if (!entry) {
            // Element not in current map — try re-extracting
            console.warn(`[DOM Agent] Element ${elementId} not in map, re-extracting...`);
            currentElementMap = extractElements();
            const retryEntry = currentElementMap[elementId];
            if (retryEntry && retryEntry._domRef && document.contains(retryEntry._domRef)) {
                return retryEntry._domRef;
            }
            return null;
        }

        // First try the cached DOM ref
        if (entry._domRef && document.contains(entry._domRef)) {
            return entry._domRef;
        }
        // Fallback: re-query by CSS selector
        try {
            const found = document.querySelector(entry._selector);
            if (found) return found;
        } catch { /* ignore selector errors */ }

        // Last resort: re-extract and look up again
        currentElementMap = extractElements();
        const refreshed = currentElementMap[elementId];
        return refreshed?._domRef || null;
    }

    /**
     * Briefly highlight an element to show the user what's being interacted with.
     */
    function highlightElement(el) {
        const original = el.style.outline;
        const originalTransition = el.style.transition;
        el.style.transition = "outline 0.2s ease";
        el.style.outline = "3px solid #2563eb";
        setTimeout(() => {
            el.style.outline = original;
            el.style.transition = originalTransition;
        }, 800);
    }

    /**
     * Scroll an element into the viewport center.
     */
    function scrollToElement(el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        return delay(300);
    }

    /**
     * Simulate human-like typing into an input field using React-safe setters.
     */
    async function simulateType(el, text) {
        await scrollToElement(el);
        highlightElement(el);

        el.focus();
        el.dispatchEvent(new Event("focus", { bubbles: true }));

        // To bypass React/Vue's value tracking getters/setters, we must use the prototype's native setter
        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set;
        const nativeTextAreaValueSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value")?.set;
        const setter = el.tagName === "TEXTAREA" ? nativeTextAreaValueSetter : nativeInputValueSetter;

        // Erase existing content gracefully
        if (setter) {
            setter.call(el, "");
        } else {
            el.value = "";
        }
        el.dispatchEvent(new InputEvent("input", { data: "", inputType: "deleteContentBackward", bubbles: true }));

        // Simulate a slight pause before typing
        await delay(150);

        // We type the full string into the element value efficiently to prevent the framework
        // from doing an async re-render and corrupting partially typed data.
        if (setter) {
            setter.call(el, text);
        } else {
            el.value = text;
        }

        // Fire the necessary events that frameworks listen to
        el.dispatchEvent(new KeyboardEvent("keydown", { key: text.charAt(text.length - 1), bubbles: true }));
        el.dispatchEvent(new InputEvent("input", { data: text, inputType: "insertText", bubbles: true }));
        el.dispatchEvent(new KeyboardEvent("keyup", { key: text.charAt(text.length - 1), bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
        el.dispatchEvent(new Event("blur", { bubbles: true }));

        // Simulate time spent typing for visual flow
        await delay(text.length * 50);
    }

    /**
     * Simulate a human-like click on an element.
     */
    async function simulateClick(el) {
        await scrollToElement(el);
        highlightElement(el);
        await delay(100);

        el.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true }));
        el.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true }));
        el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));

        // Also try native click as fallback
        el.click();
    }

    /**
     * Select an option in a dropdown.
     */
    async function simulateSelect(el, value) {
        await scrollToElement(el);
        highlightElement(el);

        // Try matching by value or visible text
        const options = Array.from(el.options || []);
        const match = options.find(
            (o) => o.value === value || o.textContent.trim().toLowerCase() === value.toLowerCase()
        );
        if (match) {
            el.value = match.value;
            el.dispatchEvent(new Event("change", { bubbles: true }));
        } else {
            throw new Error(`Option "${value}" not found in select`);
        }
    }

    /**
     * Execute a single DOM action. Returns { success, error }.
     */
    async function executeAction(action) {
        try {
            switch (action.type) {
                case "type": {
                    const el = resolveElement(action.element_id);
                    if (!el) throw new Error(`Element ${action.element_id} not found`);
                    await simulateType(el, action.value);
                    return { success: true, error: "" };
                }
                case "click": {
                    const el = resolveElement(action.element_id);
                    if (!el) throw new Error(`Element ${action.element_id} not found`);
                    await simulateClick(el);
                    return { success: true, error: "" };
                }
                case "select": {
                    const el = resolveElement(action.element_id);
                    if (!el) throw new Error(`Element ${action.element_id} not found`);
                    await simulateSelect(el, action.value);
                    return { success: true, error: "" };
                }
                case "scroll": {
                    const el = resolveElement(action.element_id);
                    if (!el) throw new Error(`Element ${action.element_id} not found`);
                    await scrollToElement(el);
                    return { success: true, error: "" };
                }
                case "navigate": {
                    window.location.href = action.url;
                    return { success: true, error: "" };
                }
                case "wait": {
                    await waitForStable(action.timeout_ms || CONFIG.domSettleTimeoutMs);
                    return { success: true, error: "" };
                }
                case "done": {
                    return { success: true, error: "" };
                }
                default:
                    return { success: false, error: `Unknown action type: ${action.type}` };
            }
        } catch (err) {
            console.error(`Action ${action.type} failed:`, err);
            return { success: false, error: err.message };
        }
    }

    /**
     * Execute a batch of actions sequentially. Returns results + new snapshot.
     */
    async function executeBatch(actions) {
        const results = [];
        for (const action of actions) {
            console.log(`[DOM Agent] Executing: ${action.type} on ${action.element_id || action.url || ""}`);
            const result = await executeAction(action);
            results.push({
                element_id: action.element_id || "",
                action_type: action.type,
                ...result,
            });

            // Wait for DOM to settle between actions (unless it's a wait action itself)
            if (action.type !== "wait" && action.type !== "done") {
                await waitForStable(CONFIG.mutationSettleMs);
            }

            // If an action failed, stop the batch
            if (!result.success) {
                console.warn(`[DOM Agent] Action failed, stopping batch: ${result.error}`);
                break;
            }
        }

        // Re-extract elements after batch execution
        currentElementMap = extractElements();
        const newSnapshot = buildSnapshot(currentElementMap);

        return { results, ...newSnapshot };
    }

    // ── 3. STATE OBSERVER ───────────────────────────────────

    /**
     * Wait for the DOM to stabilize (no mutations for a period).
     */
    function waitForMutationSettle(timeoutMs) {
        return new Promise((resolve) => {
            let timer = null;
            const observer = new MutationObserver(() => {
                clearTimeout(timer);
                timer = setTimeout(() => {
                    observer.disconnect();
                    resolve();
                }, CONFIG.mutationSettleMs);
            });
            observer.observe(document.body, {
                childList: true,
                subtree: true,
                attributes: true,
            });
            // Start initial timer
            timer = setTimeout(() => {
                observer.disconnect();
                resolve();
            }, CONFIG.mutationSettleMs);
            // Hard timeout
            setTimeout(() => {
                observer.disconnect();
                resolve();
            }, timeoutMs);
        });
    }

    /**
     * Wait for DOM to be stable — combines mutation observer + hard timeout.
     */
    async function waitForStable(timeoutMs = CONFIG.domSettleTimeoutMs) {
        await waitForMutationSettle(timeoutMs);
    }

    // ── MESSAGE HANDLER ─────────────────────────────────────

    chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
        // Legacy handler for backward compatibility
        if (request.type === "GET_PAGE_CONTEXT") {
            currentElementMap = extractElements();
            const snapshot = buildSnapshot(currentElementMap);
            // Also include legacy format
            sendResponse({
                url: snapshot.page_url,
                title: snapshot.page_title,
                forms: extractLegacyForms(),
            });
            return;
        }

        // V2: DOM snapshot with Perception Engine (stable IDs + context)
        if (request.type === "GET_DOM_SNAPSHOT") {
            // Update config if provided
            if (request.config) {
                Object.assign(CONFIG, request.config);
            }
            currentElementMap = extractElements();
            const snapshot = buildSnapshot(currentElementMap);
            sendResponse(snapshot);
            return;
        }

        // New: Execute action batch
        if (request.type === "EXECUTE_ACTIONS") {
            // Must return true immediately to keep the message channel open for async response
            executeBatch(request.actions)
                .then((result) => sendResponse(result))
                .catch((err) => sendResponse({ results: [], error: err.message }));
            return true;
        }
    });

    /**
     * Legacy form extraction for backward compatibility with existing chat.
     */
    function extractLegacyForms() {
        const forms = [];
        document.querySelectorAll("form").forEach((form) => {
            const formInfo = {
                action: form.getAttribute("action") || "",
                method: form.getAttribute("method") || "",
                fields: [],
            };
            form.querySelectorAll("input, select, textarea").forEach((input) => {
                const type = input.getAttribute("type") || input.tagName.toLowerCase();
                if (["hidden", "submit", "button"].includes(type)) return;
                formInfo.fields.push({
                    name: input.getAttribute("name") || "",
                    id: input.getAttribute("id") || "",
                    type: type,
                    placeholder: input.getAttribute("placeholder") || "",
                });
            });
            if (formInfo.fields.length > 0) forms.push(formInfo);
        });
        return forms;
    }

    console.log("[DOM Agent] Content script loaded — Element Abstraction + Executor + Observer ready.");
})();
