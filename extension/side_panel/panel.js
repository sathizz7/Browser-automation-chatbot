// panel.js — Side Panel Chat UI + Action Loop Orchestration
// All API calls route to a single backend port 8000.
// Switch backends simply by running the desired backend on port 8000.

const BACKEND_URL = "http://localhost:8000";
const DOM_AGENT_URL = "http://localhost:8000"; // Same port — run desired backend here

const chatContainer = document.getElementById("chat-container");
const chatInput = document.getElementById("chat-input");
const sendBtn = document.getElementById("send-btn");
const contextBar = document.getElementById("context-bar");
const contextTitle = document.getElementById("context-title");
const contextUrl = document.getElementById("context-url");
const quickActions = document.getElementById("quick-actions");
const settingsBtn = document.getElementById("settings-btn");

let currentPageContext = null;
let currentSessionId = "sess_" + Math.random().toString(36).substr(2, 9);
let actionHistory = []; // Track recent batches for loop detection
let isAutomating = false; // Prevent concurrent automations
let waitingForUserInput = false; // OTP / pause state
let pendingWaitResolve = null; // Resolves when user provides input during wait

// ── Initialization ──────────────────────────────────────

async function loadContext() {
    try {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (!tab || !tab.url || tab.url.startsWith("chrome://")) {
            hideContext();
            return;
        }
        chrome.tabs.sendMessage(tab.id, { type: "GET_PAGE_CONTEXT" }, (response) => {
            if (chrome.runtime.lastError || !response) {
                setContextBasic(tab);
            } else {
                setContextFull(response);
            }
        });
    } catch (err) {
        console.error("Failed to load context:", err);
        hideContext();
    }
}

function setContextBasic(tab) {
    currentPageContext = { url: tab.url, title: tab.title };
    contextTitle.textContent = tab.title || "Unknown Page";
    contextUrl.textContent = tab.url;
    contextBar.classList.remove("hidden");
    quickActions.classList.add("hidden");
}

function setContextFull(context) {
    currentPageContext = context;
    contextTitle.textContent = context.title || "Unknown Page";
    contextUrl.textContent = context.url;
    contextBar.classList.remove("hidden");
    if (context.forms && context.forms.length > 0) {
        quickActions.classList.remove("hidden");
    } else {
        quickActions.classList.add("hidden");
    }
}

function hideContext() {
    currentPageContext = null;
    contextBar.classList.add("hidden");
    quickActions.classList.add("hidden");
}

// ── API Calls ───────────────────────────────────────────

async function apiCall(endpoint, payload, method = "POST") {
    return new Promise((resolve, reject) => {
        chrome.runtime.sendMessage(
            {
                type: "API_CALL",
                endpoint: endpoint,
                method: method,
                body: method === "GET" ? undefined : payload,
            },
            (response) => {
                if (!response) reject(new Error("Background script failed to respond"));
                else if (!response.success) reject(new Error(response.error || "API call failed"));
                else resolve(response.data);
            }
        );
    });
}

async function getUserProfile() {
    return new Promise((resolve) => {
        chrome.storage.local.get(["userProfile"], (result) => {
            resolve(result.userProfile || null);
        });
    });
}

// ── Chat UI Helpers ─────────────────────────────────────

function appendMessage(role, text, isLoading = false) {
    const div = document.createElement("div");
    div.className = `message ${role}`;
    if (isLoading) {
        div.innerHTML = `<span class="loading-dots">Thinking</span>`;
        div.id = "loading-msg";
    } else {
        div.textContent = text;
    }
    chatContainer.appendChild(div);
    chatContainer.scrollTop = chatContainer.scrollHeight;
    return div;
}

function appendHtml(role, html) {
    const div = document.createElement("div");
    div.className = `message ${role}`;
    div.innerHTML = html;
    chatContainer.appendChild(div);
    chatContainer.scrollTop = chatContainer.scrollHeight;
    return div;
}

function removeLoading() {
    const loading = document.getElementById("loading-msg");
    if (loading) loading.remove();
}

function appendProgress(text) {
    const div = document.createElement("div");
    div.className = "progress-step";
    div.innerHTML = `<span class="step-icon">⚡</span> ${text}`;
    chatContainer.appendChild(div);
    chatContainer.scrollTop = chatContainer.scrollHeight;
    return div;
}

// ── DOM Snapshot Helper ─────────────────────────────────

async function getDomSnapshot() {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab) throw new Error("No active tab");

    // Try to get snapshot directly first
    const trySnapshot = () =>
        new Promise((resolve, reject) => {
            chrome.tabs.sendMessage(tab.id, { type: "GET_DOM_SNAPSHOT" }, (response) => {
                if (chrome.runtime.lastError) {
                    reject(new Error(chrome.runtime.lastError.message));
                } else if (!response) {
                    reject(new Error("No DOM snapshot received"));
                } else {
                    resolve(response);
                }
            });
        });

    try {
        return await trySnapshot();
    } catch (err) {
        // Content script not present — inject it dynamically then retry
        if (err.message.includes("Receiving end does not exist") || err.message.includes("Could not establish connection")) {
            console.log("[DOM Agent] Content script missing — injecting dynamically...");
            await new Promise((resolve, reject) => {
                chrome.runtime.sendMessage({ type: "INJECT_CONTENT_SCRIPT" }, (res) => {
                    if (!res || !res.success) {
                        reject(new Error("Injection failed: " + (res?.error || "unknown")));
                    } else {
                        resolve();
                    }
                });
            });
            // Short wait for the injected script to initialize
            await new Promise((r) => setTimeout(r, 400));
            return await trySnapshot();
        }
        throw err;
    }
}

// ── Execute Actions in Content Script ───────────────────

async function executeActions(actions) {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab) throw new Error("No active tab");

    return new Promise((resolve, reject) => {
        chrome.tabs.sendMessage(tab.id, { type: "EXECUTE_ACTIONS", actions }, (response) => {
            if (chrome.runtime.lastError) {
                const errMsg = chrome.runtime.lastError.message;
                // If the page reloaded or navigated as a result of an action (e.g., clicking Submit),
                // the content script context is destroyed and the port closes.
                // We treat this as a success, not an error!
                if (errMsg.includes("message channel closed") || errMsg.includes("receiving end does not exist")) {
                    console.log("[DOM Agent] Page likely navigated/reloaded during execution. Treating as success.");
                    resolve({ results: [{ success: true, action_type: "navigation_inferred" }] });
                } else {
                    reject(new Error("Execution failed: " + errMsg));
                }
            } else {
                resolve(response);
            }
        });
    });
}

// ── Session Reset ───────────────────────────────────────

async function resetSession() {
    try {
        await fetch(`${DOM_AGENT_URL}/reset?session_id=${encodeURIComponent(currentSessionId)}`, {
            method: "POST",
        });
        console.log(`[DOM Agent] Session '${currentSessionId}' reset.`);
    } catch (err) {
        console.warn("[DOM Agent] Could not reset session:", err.message);
    }
}

// ── Loop Detection ──────────────────────────────────────

function detectLoop(newActions) {
    const signature = JSON.stringify(
        newActions.map((a) => ({ type: a.type, element_id: a.element_id, value: a.value }))
    );

    const recentSignatures = actionHistory.slice(-5);
    const repeatCount = recentSignatures.filter((s) => s === signature).length;

    actionHistory.push(signature);
    // Keep bounded
    if (actionHistory.length > 10) actionHistory.shift();

    return repeatCount >= 2;
}

// ── Action Loop Orchestration ───────────────────────────

async function runDomAgent(userMessage) {
    if (isAutomating) {
        appendMessage("system", "⏳ Already running an automation. Please wait.");
        return;
    }
    isAutomating = true;

    // Reset session memory for a fresh task
    currentSessionId = "sess_" + Math.random().toString(36).substr(2, 9);
    actionHistory = [];

    try {
        let message = userMessage;
        let maxLoops = 10;
        let loopCount = 0;

        while (loopCount < maxLoops) {
            loopCount++;

            // 1. Get DOM snapshot
            appendProgress("📸 Reading page elements...");
            let snapshot;
            try {
                snapshot = await getDomSnapshot();
            } catch (err) {
                appendMessage("system", `❌ Could not read page: ${err.message}`);
                break;
            }

            // 2. Check for loop
            const loopDetected = loopCount > 1 && detectLoop([]);

            // 3. Call /plan
            appendProgress("🧠 Planning actions...");
            let plan;
            try {
                plan = await apiCall("/plan", {
                    message: message,
                    elements: snapshot.elements,
                    page_url: snapshot.page_url,
                    page_title: snapshot.page_title,
                    session_id: currentSessionId,
                    action_history: actionHistory.slice(-5).map((s) => JSON.parse(s)),
                    loop_detected: loopDetected,
                });
            } catch (err) {
                appendMessage("system", `❌ Planning failed: ${err.message}`);
                break;
            }

            // 4. Show plan message
            if (plan.message) {
                appendMessage("system", plan.message);
            }

            // 5. Handle error
            if (plan.error) {
                appendMessage("system", `❌ ${plan.error}`);
                break;
            }

            // 6. Handle done
            if (plan.done) {
                appendMessage("system", "✅ Task complete!");
                break;
            }

            // 7. Handle wait for user input (OTP, etc.)
            if (plan.wait_for_user_input) {
                appendHtml(
                    "system",
                    `⏸️ <strong>${plan.wait_for_user_input}</strong><br>
                     <span style="font-size:12px; color:#64748b;">Type your response below and press Enter.</span>`
                );

                // Execute any actions that came before the wait
                if (plan.actions && plan.actions.length > 0) {
                    appendProgress(`▶️ Executing ${plan.actions.length} action(s)...`);
                    for (const action of plan.actions) {
                        if (action.description) appendProgress(`  → ${action.description}`);
                    }
                    await executeActions(plan.actions);

                    // Update loop detection
                    detectLoop(plan.actions);
                }

                // Pause and wait for user input
                waitingForUserInput = true;
                const userResponse = await new Promise((resolve) => {
                    pendingWaitResolve = resolve;
                });
                waitingForUserInput = false;
                pendingWaitResolve = null;

                // Continue with user's response as the next message
                message = userResponse;
                continue;
            }

            // 8. Execute actions
            if (!plan.actions || plan.actions.length === 0) {
                appendMessage("system", "🤔 No actions to perform. Try rephrasing your request.");
                break;
            }

            appendProgress(`▶️ Executing ${plan.actions.length} action(s)...`);
            for (const action of plan.actions) {
                if (action.description) appendProgress(`  → ${action.description}`);
            }

            // Update loop detection
            detectLoop(plan.actions);

            const execResult = await executeActions(plan.actions);

            // Check results
            const failures = (execResult.results || []).filter((r) => !r.success);
            if (failures.length > 0) {
                for (const f of failures) {
                    appendProgress(`  ❌ ${f.action_type} on ${f.element_id}: ${f.error}`);
                }
                // Continue loop — planner will see the failures and replan
                message = `Previous actions had failures: ${failures.map((f) => f.error).join("; ")}. ${userMessage}`;
            } else {
                appendProgress("  ✅ All actions executed successfully");
                message = userMessage; // Original message for next planning round
            }
        }

        if (loopCount >= maxLoops) {
            appendMessage("system", "⚠️ Reached maximum steps. Please try a simpler instruction.");
        }
    } catch (err) {
        console.error("DOM Agent error:", err);
        appendMessage("system", `❌ Automation error: ${err.message}`);
    } finally {
        isAutomating = false;
    }
}

// ── Chat Handler (routes to chat API or DOM agent) ──────

async function handleChat(messageText) {
    if (!messageText.trim()) return;

    // If waiting for user input (OTP/pause), resolve the promise
    if (waitingForUserInput && pendingWaitResolve) {
        appendMessage("user", messageText);
        chatInput.value = "";
        pendingWaitResolve(messageText);
        return;
    }

    appendMessage("user", messageText);
    chatInput.value = "";

    // All messages go to the DOM agent planner
    await runDomAgent(messageText);
}

// ── Event Listeners ─────────────────────────────────────

sendBtn.addEventListener("click", () => handleChat(chatInput.value));
chatInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleChat(chatInput.value);
    }
});

quickActions.addEventListener("click", (e) => {
    if (e.target.classList.contains("action-btn")) {
        const action = e.target.getAttribute("data-action");
        const label = e.target.textContent.trim();
        if (action === "fill_form" || action === "checkout_flow") {
            // Route to DOM agent for visible interaction
            handleChat(`Please ${label.toLowerCase()} on this page.`);
        } else {
            handleChat(`Please ${label.toLowerCase()} on this page.`);
        }
    }
});

settingsBtn.addEventListener("click", () => {
    chrome.runtime.openOptionsPage();
});

// Update context when switching tabs
chrome.tabs.onActivated.addListener(loadContext);
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
    if (changeInfo.status === "complete" && tab.active) {
        loadContext();
    }
});

// Init
loadContext();
