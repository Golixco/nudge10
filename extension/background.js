// extension/background.js
// Nudge10 Manifest V3 Service Worker
// Manages focus session state, listens for navigation to distraction domains,
// and requests AI interventions from the Nudge10 backend.

if (typeof importScripts === 'function') {
  try {
    importScripts('config.js');
  } catch (e) {
    console.warn('config.js could not be imported:', e);
  }
}

// In-memory tab tracking to prevent duplicate interventions on the same domain
// Map of tabId -> normalizedCategory
const lastTabDistraction = new Map();

// -----------------------------------------------------------------------------
// Hostname Normalization & Allowlist
// -----------------------------------------------------------------------------
function normalizeHostname(hostname) {
  if (!hostname) return null;
  const host = hostname.toLowerCase().trim();

  // youtube.com (including m.youtube.com, www.youtube.com)
  if (host === 'youtube.com' || host.endsWith('.youtube.com')) {
    return 'youtube.com';
  }
  // instagram.com (including www.instagram.com, m.instagram.com)
  if (host === 'instagram.com' || host.endsWith('.instagram.com')) {
    return 'instagram.com';
  }
  // reddit.com (including old.reddit.com, www.reddit.com)
  if (host === 'reddit.com' || host.endsWith('.reddit.com')) {
    return 'reddit.com';
  }
  // x.com (including www.x.com)
  if (host === 'x.com' || host.endsWith('.x.com')) {
    return 'x.com';
  }
  // twitter.com (including mobile.twitter.com, www.twitter.com)
  if (host === 'twitter.com' || host.endsWith('.twitter.com')) {
    return 'twitter.com';
  }

  return null;
}

// -----------------------------------------------------------------------------
// Session Storage Helper (survives service worker suspension)
// -----------------------------------------------------------------------------
async function getActiveSession() {
  try {
    const data = await chrome.storage.local.get('nudge10_session');
    const session = data?.nudge10_session;
    if (session && session.activeSessionId && session.enabled) {
      return session;
    }
  } catch (err) {
    console.warn('Failed to read from chrome.storage.local:', err);
  }
  return null;
}

async function setActiveSession(session) {
  try {
    await chrome.storage.local.set({ nudge10_session: session });
  } catch (err) {
    console.warn('Failed to save session to chrome.storage.local:', err);
  }
}

async function clearActiveSession() {
  try {
    await chrome.storage.local.remove('nudge10_session');
    lastTabDistraction.clear();
  } catch (err) {
    console.warn('Failed to clear session from chrome.storage.local:', err);
  }
}

// -----------------------------------------------------------------------------
// Runtime Message Listener (Bridge from Content Script on Web App Origin)
// -----------------------------------------------------------------------------
if (typeof chrome !== 'undefined' && chrome.runtime?.onMessage) {
  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (!message || typeof message !== 'object') return false;

    if (message.type === 'NUDGE10_SESSION_START') {
      const { sessionId, startedAt, task, missionTitle } = message;
      if (!sessionId) {
        sendResponse({ ok: false, error: 'missing_session_id' });
        return false;
      }

      const sessionData = {
        activeSessionId: String(sessionId),
        startedAt: Number(startedAt) || Date.now(),
        task: String(task || 'Current task'),
        missionTitle: String(missionTitle || '10-minute focus mission'),
        enabled: true,
      };

      setActiveSession(sessionData).then(() => {
        sendResponse({ ok: true });
      });
      return true; // Async response
    }

    if (message.type === 'NUDGE10_SESSION_END') {
      clearActiveSession().then(() => {
        sendResponse({ ok: true });
      });
      return true;
    }

    if (message.type === 'NUDGE10_PING') {
      sendResponse({ ok: true, type: 'NUDGE10_PONG' });
      return false;
    }

    return false;
  });
}

// -----------------------------------------------------------------------------
// Tab Navigation Listener
// -----------------------------------------------------------------------------
if (typeof chrome !== 'undefined' && chrome.tabs?.onUpdated) {
  chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  // Trigger when page finishes loading
  if (changeInfo.status !== 'complete') return;

  const urlString = tab.url;
  if (!urlString) return;

  // Ignore non-http/https
  if (!urlString.startsWith('http://') && !urlString.startsWith('https://')) return;

  let parsedUrl;
  try {
    parsedUrl = new URL(urlString);
  } catch {
    return;
  }

  // Check if this domain is Nudge10 web app itself
  const appHost = (typeof NUDGE10_CONFIG !== 'undefined' && NUDGE10_CONFIG.WEB_APP_URL)
    ? new URL(NUDGE10_CONFIG.WEB_APP_URL).hostname
    : 'localhost';
  if (parsedUrl.hostname === appHost || parsedUrl.hostname === '127.0.0.1') {
    return;
  }

  const category = normalizeHostname(parsedUrl.hostname);
  if (!category) {
    // User navigated to a non-distraction site -> reset this tab's distraction state
    lastTabDistraction.delete(tabId);
    return;
  }

  // Check if an active session exists
  const activeSession = await getActiveSession();
  if (!activeSession) return;

  // Duplicate prevention: If already triggered for this distraction category in this tab, do not re-trigger
  if (lastTabDistraction.get(tabId) === category) {
    return;
  }

  // Mark this category as triggered for this tab
  lastTabDistraction.set(tabId, category);

  // Compute elapsed seconds securely from session startedAt
  const startedAt = typeof activeSession.startedAt === 'number'
    ? activeSession.startedAt
    : Date.now();
  const elapsedSeconds = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));

  // Request AI intervention from Nudge10 backend
  const apiBase = (typeof NUDGE10_CONFIG !== 'undefined' && NUDGE10_CONFIG.API_BASE_URL)
    ? NUDGE10_CONFIG.API_BASE_URL
    : 'http://localhost:8000';

  let intervention;
  try {
    const res = await fetch(`${apiBase}/api/session/distraction`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: activeSession.activeSessionId,
        site: category,
        elapsed_seconds: elapsedSeconds,
      }),
    });

    if (res.ok) {
      intervention = await res.json();
    } else {
      intervention = {
        message: "You're outside your focus session.",
        action: "Return to the task you started.",
      };
    }
  } catch (err) {
    console.warn('Nudge10 backend call failed, using fallback:', err);
    intervention = {
      message: "You're outside your focus session.",
      action: "Return to the task you started.",
    };
  }

  // Forward intervention message to content script in tab
  const messagePayload = {
    type: 'NUDGE10_INTERVENTION',
    message: intervention.message,
    action: intervention.action,
    site: category,
    task: activeSession.task,
    missionTitle: activeSession.missionTitle,
    webAppUrl: (typeof NUDGE10_CONFIG !== 'undefined' && NUDGE10_CONFIG.WEB_APP_URL)
      ? NUDGE10_CONFIG.WEB_APP_URL
      : 'http://localhost:8000',
  };

  // Deliver to tab with retries to account for content script initialization
  deliverIntervention(tabId, messagePayload);
  });
}

// Retry delivery in case content script is still completing document_idle initialization
async function deliverIntervention(tabId, payload, retries = 3) {
  for (let i = 0; i < retries; i++) {
    try {
      if (typeof chrome !== 'undefined' && chrome.tabs?.sendMessage) {
        await chrome.tabs.sendMessage(tabId, payload);
      }
      return;
    } catch (e) {
      if (i < retries - 1) {
        await new Promise((r) => setTimeout(r, 350));
      }
    }
  }
}

// Clean up tab tracking when tab is closed
if (typeof chrome !== 'undefined' && chrome.tabs?.onRemoved) {
  chrome.tabs.onRemoved.addListener((tabId) => {
    lastTabDistraction.delete(tabId);
  });
}

// Export helper functions for testing in Node
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    normalizeHostname,
    lastTabDistraction,
  };
}
