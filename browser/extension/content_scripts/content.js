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

    // ── 1. ELEMENT ABSTRACTION LAYER ────────────────────────

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
        // Nearby text (previous sibling or parent)
        const prev = el.previousElementSibling;
        if (prev && prev.tagName === "LABEL") return prev.innerText.trim();
        return "";
    }

    /**
     * Detect if an input is likely an OTP field (rule-based, not LLM-dependent).
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
        // Short numeric-only input
        const maxLen = el.maxLength;
        const pattern = el.getAttribute("pattern");
        if (maxLen >= 4 && maxLen <= 8 && el.type === "text") return true;
        if (pattern && pattern.includes("[0-9]")) return true;

        return false;
    }

    /**
     * Build a stable selector for an element (for internal use only — never sent to LLM).
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
        // Fallback: nth-of-type from parent
        const parent = el.parentElement;
        if (parent) {
            const siblings = Array.from(parent.querySelectorAll(`:scope > ${el.tagName.toLowerCase()}`));
            const index = siblings.indexOf(el) + 1;
            return `${buildSelector(parent)} > ${el.tagName.toLowerCase()}:nth-of-type(${index})`;
        }
        return el.tagName.toLowerCase();
    }

    /**
     * Extract all interactive elements from the page.
     * Returns an element map { el_N: { metadata, domRef } }.
     */
    function extractElements() {
        const selectors = "input, button, select, textarea, a[href]";
        const allElements = document.querySelectorAll(selectors);
        const elementMap = {};
        let idx = 0;

        for (const el of allElements) {
            if (idx >= CONFIG.maxElements) break;

            // Skip hidden, disabled-hidden, or non-interactive
            if (!isVisible(el)) continue;
            const type = el.getAttribute("type") || el.tagName.toLowerCase();
            if (["hidden", "submit"].includes(type) && el.tagName === "INPUT") continue;

            const id = `el_${idx}`;
            elementMap[id] = {
                id: id,
                tag: el.tagName.toLowerCase(),
                type: type,
                label: findLabel(el),
                placeholder: el.placeholder || "",
                text: (el.innerText || el.textContent || "").trim().substring(0, 100),
                name: el.name || "",
                value: el.value || "",
                ariaLabel: el.getAttribute("aria-label") || "",
                visible: true,
                disabled: el.disabled || false,
                otp_detected: isOtpField(el),
                // Internal only — never sent to LLM
                _selector: buildSelector(el),
                _domRef: el,
            };
            idx++;
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
     * Resolve an element_id to a live DOM element.
     */
    function resolveElement(elementId) {
        const entry = currentElementMap[elementId];
        if (!entry) return null;

        // First try the cached DOM ref
        if (entry._domRef && document.contains(entry._domRef)) {
            return entry._domRef;
        }
        // Fallback: re-query by selector
        try {
            return document.querySelector(entry._selector);
        } catch {
            return null;
        }
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

        // New: DOM snapshot with element abstraction
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
