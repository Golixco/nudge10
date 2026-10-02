// extension/config.js
// Nudge10 Extension Configuration
// Do NOT add any Backboard API keys or secrets here.

const NUDGE10_CONFIG = {
  // Live Render production service deployment
  API_BASE_URL: 'https://nudge10-9tli.onrender.com',
  WEB_APP_URL: 'https://nudge10-9tli.onrender.com',

  // Local development fallback (uncomment for local development testing):
  // API_BASE_URL: 'http://localhost:8000',
  // WEB_APP_URL: 'http://localhost:8000',

  // Allowed distraction categories (normalized)
  DISTRACTION_CATEGORIES: [
    'youtube.com',
    'instagram.com',
    'reddit.com',
    'x.com',
    'twitter.com'
  ]
};

// CommonJS export for Node validation and unit testing
if (typeof module !== 'undefined' && module.exports) {
  module.exports = NUDGE10_CONFIG;
}
