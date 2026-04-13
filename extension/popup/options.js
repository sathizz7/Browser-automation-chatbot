// options.js

document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('profile-form');
    const statusEl = document.getElementById('status');

    const fields = [
        'full_name', 'email', 'phone',
        'address_line1', 'city', 'state', 'zip_code'
    ];

    // Load saved data
    chrome.storage.local.get(['userProfile'], (result) => {
        if (result.userProfile) {
            fields.forEach(field => {
                const el = document.getElementById(field);
                if (el && result.userProfile[field]) {
                    el.value = result.userProfile[field];
                }
            });
        }
    });

    // Save data
    form.addEventListener('submit', (e) => {
        e.preventDefault();

        const profileData = {};
        fields.forEach(field => {
            const el = document.getElementById(field);
            if (el) {
                profileData[field] = el.value.trim();
            }
        });

        chrome.storage.local.set({ userProfile: profileData }, () => {
            statusEl.textContent = 'Profile saved successfully!';
            setTimeout(() => { statusEl.textContent = ''; }, 3000);
        });
    });
});
