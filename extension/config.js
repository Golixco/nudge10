// extension/config.js
// Nudge10 Extension Configuration
// Do NOT add any Backboard API keys or secrets here.

const NUDGE10_CONFIG = {
  // Active configuration (default: local development)
  // For local development: keep http://localhost:8000
  API_BASE_URL: 'http://localhost:8000',
  WEB_APP_URL: 'http://localhost:8000',

  // Production Render deployment placeholder:
  // Once your service is deployed on Render, update API_BASE_URL & WEB_APP_URL below
  // to your exact service URL (e.g. 'https://nudge10.onrender.com') and narrow
  // host_permissions in manifest.json to that exact host. Do NOT use wildcards.
  // PRODUCTION_API_BASE_URL: 'https://YOUR-SERVICE-NAME.onrender.com',
  // PRODUCTION_WEB_APP_URL: 'https://YOUR-SERVICE-NAME.onrender.com',

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
