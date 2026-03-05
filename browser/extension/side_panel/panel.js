// panel.js

const API_BASE = "http://localhost:8000";
const chatContainer = document.getElementById('chat-container');
const chatInput = document.getElementById('chat-input');
const sendBtn = document.getElementById('send-btn');
const contextBar = document.getElementById('context-bar');
const contextTitle = document.getElementById('context-title');
const contextUrl = document.getElementById('context-url');
const quickActions = document.getElementById('quick-actions');
const settingsBtn = document.getElementById('settings-btn');


let currentPageContext = null;
let currentSessionId = "sess_" + Math.random().toString(36).substr(2, 9);


// ── Initialization ──

async function loadContext() {
    try {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (!tab || !tab.url || tab.url.startsWith('chrome://')) {
            hideContext();
            return;
        }

        // Try to get context from content script
        chrome.tabs.sendMessage(tab.id, { type: "GET_PAGE_CONTEXT" }, (response) => {
            if (chrome.runtime.lastError || !response) {
                // Content script might not be injected yet
                console.log("Could not get detailed context", chrome.runtime.lastError);
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
    contextBar.classList.remove('hidden');
    quickActions.classList.add('hidden'); // Needs forms to show actions generally
}

function setContextFull(context) {
    currentPageContext = context;
    contextTitle.textContent = context.title || "Unknown Page";
    contextUrl.textContent = context.url;
    contextBar.classList.remove('hidden');

    // Show quick actions if forms exist
    if (context.forms && context.forms.length > 0) {
        quickActions.classList.remove('hidden');
    } else {
        quickActions.classList.add('hidden');
    }
}

function hideContext() {
    currentPageContext = null;
    contextBar.classList.add('hidden');
    quickActions.classList.add('hidden');
}


// ── API Calls via Background ──

async function apiCall(endpoint, payload) {
    return new Promise((resolve, reject) => {
        chrome.runtime.sendMessage({
            type: "API_CALL",
            method: "POST",
            url: `${API_BASE}${endpoint}`,
            body: payload
        }, (response) => {
            if (!response) {
                reject(new Error("Background script failed to respond"));
            } else if (!response.success) {
                reject(new Error(response.error || "API call failed"));
            } else {
                resolve(response.data);
            }
        });
    });
}

async function getUserProfile() {
    return new Promise((resolve) => {
        chrome.storage.local.get(['userProfile'], (result) => {
            resolve(result.userProfile || null);
        });
    });
}


// ── Chat UI ──

function appendMessage(role, text, isLoading = false) {
    const div = document.createElement('div');
    div.className = `message ${role}`;
    if (isLoading) {
        div.innerHTML = `<span class="loading-dots">Thinking</span>`;
        div.id = 'loading-msg';
    } else {
        div.textContent = text;
    }
    chatContainer.appendChild(div);
    chatContainer.scrollTop = chatContainer.scrollHeight;
    return div;
}

function removeLoading() {
    const loading = document.getElementById('loading-msg');
    if (loading) loading.remove();
}


// ── Actions ──

async function handleChat(messageText) {
    if (!messageText.trim()) return;

    appendMessage('user', messageText);
    chatInput.value = '';
    const loadingDiv = appendMessage('system', '', true);

    try {
        const data = await apiCall('/chat', {
            message: messageText,
            session_id: currentSessionId,
            page_url: currentPageContext?.url || "",
            page_context: currentPageContext
        });

        removeLoading();

        // Check if the response contains a navigation URL
        const urlMatch = data.message.match(/Final URL:\s*(https?:\/\/[^\s]+)/i);
        if (urlMatch) {
            const targetUrl = urlMatch[1];

            // Show the result in chat with a clickable link
            const msgDiv = appendMessage('system', '');
            msgDiv.innerHTML = `✅ Found it! Navigating to:<br>
                <a href="${targetUrl}" style="color:#2563eb; text-decoration:underline; word-break:break-all;" 
                   id="nav-link">${targetUrl}</a><br>
                <span style="font-size:12px; color:#64748b; margin-top:4px; display:block;">
                    ${data.message.replace(/Final URL:.*$/m, '').trim()}
                </span>`;

            // Navigate the user's active tab
            const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
            if (tab) {
                chrome.tabs.update(tab.id, { url: targetUrl });
            }
        } else {
            appendMessage('system', data.message);
        }

        // Show suggested actions if any
        if (data.suggested_actions && data.suggested_actions.length > 0) {
            const sugDiv = document.createElement('div');
            sugDiv.className = 'quick-actions';
            sugDiv.style.padding = '4px 0';
            data.suggested_actions.forEach(action => {
                const btn = document.createElement('button');
                btn.className = 'action-btn';
                btn.textContent = action;
                btn.onclick = () => handleChat(action);
                sugDiv.appendChild(btn);
            });
            chatContainer.appendChild(sugDiv);
        }

    } catch (err) {
        console.error("Chat error:", err);
        removeLoading();
        appendMessage('system', `Error: ${err.message}`);
    }
}

async function handleAutomate(taskType, userMessage = "") {
    if (!currentPageContext || !currentPageContext.url) {
        appendMessage('system', "I don't have a valid active page to interact with.");
        return;
    }

    appendMessage('user', userMessage || `Starting task: ${taskType}`);
    const statusDiv = appendMessage('system', 'Starting browser automation...', true);

    try {
        const profile = await getUserProfile();

        const data = await apiCall('/automate', {
            task_type: taskType,
            target_url: currentPageContext.url,
            user_message: userMessage,
            user_profile: profile,
            page_context: currentPageContext
        });

        removeLoading();
        const resultMsg = data.success
            ? `✅ Automation finished. ${data.message || ''}`
            : `❌ Automation failed. ${data.error || ''}`;

        const finalDiv = appendMessage('system', resultMsg);

        if (data.extracted_data && data.extracted_data.raw_result) {
            const detail = document.createElement('div');
            detail.className = 'progress-step';
            detail.textContent = "Result: " + data.extracted_data.raw_result.substring(0, 150) + "...";
            finalDiv.appendChild(detail);
        }

    } catch (err) {
        console.error("Automate error:", err);
        removeLoading();
        appendMessage('system', `Error running automation: ${err.message}`);
    }
}


// ── Event Listeners ──

sendBtn.addEventListener('click', () => handleChat(chatInput.value));
chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleChat(chatInput.value);
    }
});

quickActions.addEventListener('click', (e) => {
    if (e.target.classList.contains('action-btn')) {
        const action = e.target.getAttribute('data-action');
        const label = e.target.textContent.trim();
        handleAutomate(action, `Please ${label.toLowerCase()} on this page.`);
    }
});

settingsBtn.addEventListener('click', () => {
    chrome.runtime.openOptionsPage();
});

// Update context when switching tabs
chrome.tabs.onActivated.addListener(loadContext);
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
    if (changeInfo.status === 'complete' && tab.active) {
        loadContext();
    }
});

// Init
loadContext();
