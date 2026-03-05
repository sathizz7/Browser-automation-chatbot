// content.js
// Runs in the context of the active web page

function extractPageContext() {
    const context = {
        url: window.location.href,
        title: document.title,
        forms: []
    };

    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        const formInfo = {
            action: form.getAttribute('action') || '',
            method: form.getAttribute('method') || '',
            fields: []
        };

        const inputs = form.querySelectorAll('input, select, textarea');
        inputs.forEach(input => {
            const fieldInfo = {
                name: input.getAttribute('name') || '',
                id: input.getAttribute('id') || '',
                type: input.getAttribute('type') || input.tagName.toLowerCase(),
                placeholder: input.getAttribute('placeholder') || ''
            };

            // Try to find an associated label
            if (input.id) {
                const label = document.querySelector(`label[for="${input.id}"]`);
                if (label) {
                    fieldInfo.label = label.innerText.trim();
                }
            }

            // Filter out hidden/submit inputs
            if (['hidden', 'submit', 'button'].includes(fieldInfo.type)) {
                return;
            }

            formInfo.fields.push(fieldInfo);
        });

        if (formInfo.fields.length > 0) {
            context.forms.push(formInfo);
        }
    });

    return context;
}

// Listen for requests from the side panel
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.type === "GET_PAGE_CONTEXT") {
        sendResponse(extractPageContext());
    }
});

console.log("GHMC Assistant content script loaded.");
