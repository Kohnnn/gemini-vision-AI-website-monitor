// static/darkmode.js

// --- Unified Dark Mode Toggle with Icon Update ---
function setDarkMode(enabled) {
    if (enabled) {
       document.body.classList.add('dark-mode');
       localStorage.setItem('dark-mode', 'true');
   } else {
       document.body.classList.remove('dark-mode');
       localStorage.setItem('dark-mode', 'false');
   }
    updateDarkIcon();
}

function toggleDarkMode() {
    setDarkMode(!document.body.classList.contains('dark-mode'));
}

function updateDarkIcon() {
    const icon = document.getElementById('darkmode-icon');
   if (!icon) return;
   // Check only body class now
   if (document.body.classList.contains('dark-mode')) {
       icon.textContent = '🌙';
   } else {
        icon.textContent = '☀️';
    }
}

// On page load, apply user's preference and set up toggle
(function() {
   // Removed injected style block - CSS file handles this now

   const darkPref = localStorage.getItem('dark-mode');
   if (darkPref === 'true') {
        setDarkMode(true);
    } else if (darkPref === 'false') {
        setDarkMode(false);
    } else {
        // Check for system preference
        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
            setDarkMode(true);
        } else {
            updateDarkIcon();
        }
    }
    // Attach to toggle button/icon
    const toggleBtn = document.getElementById('darkmode-toggle');
    if (toggleBtn) {
        toggleBtn.onclick = toggleDarkMode;
    }
})();

// Make toggleDarkMode globally accessible
window.toggleDarkMode = toggleDarkMode;

// --- Notification System --- [REMOVED]
// Removed the showNotification function as Flask flash messages are used.