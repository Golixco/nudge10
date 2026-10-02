// extension/content.js
// Nudge10 Content Script
// Dual purpose:
//   1. On Nudge10 web app origin: bridges window messages to the service worker.
//   2. On distraction sites: receives intervention messages and renders the overlay.

(function () {
  'use strict';

  const currentHost = window.location.hostname;
  const webAppHost = (typeof NUDGE10_CONFIG !== 'undefined' && NUDGE10_CONFIG.WEB_APP_URL)
    ? new URL(NUDGE10_CONFIG.WEB_APP_URL).hostname
    : 'localhost';

  const isWebApp = currentHost === webAppHost ||
                   currentHost === 'localhost' ||
                   currentHost === '127.0.0.1' ||
                   currentHost.endsWith('.onrender.com');

  // ===========================================================================
  // Mode A: Nudge10 Web App Origin (Bridge)
  // ===========================================================================
  if (isWebApp) {
    // Notify the web app that the extension content script is active
    window.postMessage({ source: 'nudge10-extension', type: 'NUDGE10_EXTENSION_READY' }, '*');

    window.addEventListener('message', (event) => {
      // Validate event source
      if (event.source !== window) return;
      if (!event.data || event.data.source !== 'nudge10-web') return;

      const { type, sessionId, startedAt, task, missionTitle, reason } = event.data;

      // Handle Ping / Pong handshake
      if (type === 'NUDGE10_PING') {
        window.postMessage({ source: 'nudge10-extension', type: 'NUDGE10_PONG' }, '*');
        return;
      }

      // Handle Session Start
      if (type === 'NUDGE10_SESSION_START') {
        if (!sessionId) return;
        chrome.runtime.sendMessage({
          type: 'NUDGE10_SESSION_START',
          sessionId: String(sessionId),
          startedAt: startedAt || Date.now(),
          task: String(task || ''),
          missionTitle: String(missionTitle || ''),
        }).catch(() => {});
        return;
      }

      // Handle Session End (Completed or Abandoned)
      if (type === 'NUDGE10_SESSION_END') {
        chrome.runtime.sendMessage({
          type: 'NUDGE10_SESSION_END',
          sessionId: String(sessionId || ''),
          reason: String(reason || ''),
        }).catch(() => {});
        return;
      }
    });

    return;
  }

  // ===========================================================================
  // Mode B: Distraction Sites (Overlay Intervention)
  // ===========================================================================
  let overlayVisible = false;

  function showInterventionOverlay(data) {
    if (overlayVisible || document.getElementById('nudge10-overlay')) return;
    overlayVisible = true;

    const overlay = document.createElement('div');
    overlay.id = 'nudge10-overlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-labelledby', 'n10-title');

    const taskText = data.missionTitle || data.task || 'Your 10-minute focus mission';
    const message = data.message || "You're outside your focus session.";
    const action = data.action || 'Return to the task you started.';
    const webAppUrl = data.webAppUrl || (typeof NUDGE10_CONFIG !== 'undefined' ? NUDGE10_CONFIG.WEB_APP_URL : 'http://localhost:8000');

    overlay.innerHTML = `
      <div class="n10-card">
        <div class="n10-header">
          <div class="n10-brand"><span class="n10-dot"></span>NUDGE10</div>
          <div class="n10-kicker">FOCUS INTERVENTION</div>
        </div>
        <div class="n10-task-section">
          <div class="n10-task-label">YOU WERE WORKING ON</div>
          <div class="n10-task-text">${escapeHtml(taskText)}</div>
        </div>
        <h2 class="n10-title" id="n10-title">${escapeHtml(message)}</h2>
        <div class="n10-action-box">${escapeHtml(action)}</div>
        <div class="n10-row">
          <button id="n10-back" class="n10-btn-primary" autofocus>Back to work →</button>
          <button id="n10-dismiss" class="n10-btn-ghost">Dismiss</button>
        </div>
      </div>
    `;

    document.documentElement.appendChild(overlay);

    // Focus "Back to work" for keyboard accessibility
    const backBtn = document.getElementById('n10-back');
    const dismissBtn = document.getElementById('n10-dismiss');
    if (backBtn) backBtn.focus();

    backBtn?.addEventListener('click', () => {
      overlay.remove();
      overlayVisible = false;
      window.location.href = webAppUrl;
    });

    dismissBtn?.addEventListener('click', () => {
      overlay.remove();
      overlayVisible = false;
    });

    // Escape key dismiss
    const handleKeydown = (e) => {
      if (e.key === 'Escape') {
        overlay.remove();
        overlayVisible = false;
        document.removeEventListener('keydown', handleKeydown);
      }
    };
    document.addEventListener('keydown', handleKeydown);
  }

  function escapeHtml(text) {
    if (!text) return '';
    return String(text).replace(/[&<>"']/g, (m) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#039;',
    }[m]));
  }

  // Listen for messages from the service worker
  if (typeof chrome !== 'undefined' && chrome.runtime?.onMessage) {
    chrome.runtime.onMessage.addListener((message) => {
      if (message && message.type === 'NUDGE10_INTERVENTION') {
        showInterventionOverlay(message);
      }
    });
  }
})();
