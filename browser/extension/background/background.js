// background.js

// Enable side panel to open on extension icon click
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true })
    .catch((error) => console.error(error));

// Listen for messages from side panel or content scripts
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.type === "API_CALL") {
        // Proxy API calls through background to avoid CORS in content scripts/panel
        fetch(request.url, {
            method: request.method || "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: request.body ? JSON.stringify(request.body) : null
        })
            .then(response => response.json())
            .then(data => sendResponse({ success: true, data }))
            .catch(error => sendResponse({ success: false, error: error.message }));

        // Return true to indicate we wish to send a response asynchronously
        return true;
    }
});
