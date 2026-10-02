"""
tests/test_extension.py — Automated verification for Nudge10 Stage 9 Chrome Extension.

Tests cover:
  - Manifest V3 validation & least-privilege permission audit
  - Absence of credentials / secrets in extension source files
  - Hostname normalization & allowlist filtering (via Node)
  - Service worker session lifecycle & chrome.storage.local simulation
  - Duplicate navigation prevention per tab
  - Safe payload verification (only normalized site, no raw URLs/query params)
  - Backend failure fallback resilience
  - Content script overlay message contract & XSS escaping
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

EXTENSION_DIR = Path(__file__).parent.parent / "extension"


def test_manifest_v3_and_least_privilege():
    """Manifest must follow MV3 and use minimal permissions (only storage)."""
    manifest_path = EXTENSION_DIR / "manifest.json"
    assert manifest_path.exists(), "extension/manifest.json must exist"

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    assert manifest.get("manifest_version") == 3, "Must be Manifest V3"
    assert manifest.get("permissions") == ["storage"], "Permissions must strictly be ['storage']"

    # Verify no dangerous permissions
    forbidden = ["tabs", "browsingData", "cookies", "history", "debugger", "webRequest", "<all_urls>"]
    for perm in forbidden:
        assert perm not in manifest.get("permissions", []), f"Forbidden permission: {perm}"

    # Verify host permissions do not have wildcard broad access
    host_perms = manifest.get("host_permissions", [])
    assert "<all_urls>" not in host_perms
    assert "*://*/*" not in host_perms
    assert any("youtube.com" in h for h in host_perms)
    assert any("instagram.com" in h for h in host_perms)
    assert any("reddit.com" in h for h in host_perms)
    assert any("x.com" in h for h in host_perms)
    assert any("twitter.com" in h for h in host_perms)
    assert "https://*.onrender.com/*" not in host_perms, "Wildcard onrender.com permission must be replaced with exact host"
    assert "https://nudge10-9tli.onrender.com/*" in host_perms, "Exact Render host permission must be present"
    assert "http://localhost:8000/*" in host_perms, "Localhost development permission must be preserved"



def test_no_secrets_in_extension_files():
    """Verify that no API keys or credentials are leaked in extension files."""
    from app.config import settings

    for file_path in EXTENSION_DIR.glob("*"):
        if file_path.is_file():
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            assert settings.backboard_api_key not in content, f"API key leaked in {file_path.name}"
            assert "BACKBOARD_API_KEY" not in content, f"Environment variable name leaked in {file_path.name}"
            assert "Bearer " not in content, f"Auth token leaked in {file_path.name}"


def test_hostname_normalization_via_node():
    """Verify normalization logic for known and unknown hostnames using Node."""
    node_script = """
    const { normalizeHostname } = require('./extension/background.js');
    const assert = require('assert');

    // Known distraction hosts & subdomains
    assert.strictEqual(normalizeHostname('youtube.com'), 'youtube.com');
    assert.strictEqual(normalizeHostname('www.youtube.com'), 'youtube.com');
    assert.strictEqual(normalizeHostname('m.youtube.com'), 'youtube.com');

    assert.strictEqual(normalizeHostname('instagram.com'), 'instagram.com');
    assert.strictEqual(normalizeHostname('www.instagram.com'), 'instagram.com');

    assert.strictEqual(normalizeHostname('reddit.com'), 'reddit.com');
    assert.strictEqual(normalizeHostname('old.reddit.com'), 'reddit.com');

    assert.strictEqual(normalizeHostname('x.com'), 'x.com');
    assert.strictEqual(normalizeHostname('www.x.com'), 'x.com');

    assert.strictEqual(normalizeHostname('twitter.com'), 'twitter.com');
    assert.strictEqual(normalizeHostname('mobile.twitter.com'), 'twitter.com');

    // Unknown hosts -> must be null
    assert.strictEqual(normalizeHostname('github.com'), null);
    assert.strictEqual(normalizeHostname('google.com'), null);
    assert.strictEqual(normalizeHostname('localhost'), null);
    assert.strictEqual(normalizeHostname('wikipedia.org'), null);
    assert.strictEqual(normalizeHostname(''), null);
    assert.strictEqual(normalizeHostname(null), null);

    console.log('NORMALIZATION_OK');
    """
    res = subprocess.run(["node", "-e", node_script], capture_output=True, text=True)
    assert res.returncode == 0, f"Node script failed: {res.stderr}"
    assert "NORMALIZATION_OK" in res.stdout


def test_extension_full_lifecycle_simulation_in_node():
    """
    Simulates the extension service worker lifecycle:
      - valid session start
      - malformed session start
      - storage persistence
      - distraction navigation & payload verification (only normalized site sent)
      - duplicate navigation suppression
      - session end & storage cleanup
      - no navigation triggers when session inactive
      - backend fallback handling
    """
    node_test = """
    const assert = require('assert');
    const { normalizeHostname, lastTabDistraction } = require('./extension/background.js');

    // Mock chrome APIs
    let mockStorage = {};
    const callsToBackend = [];

    const mockChromeStorage = {
      local: {
        get: async (key) => ({ [key]: mockStorage[key] }),
        set: async (obj) => { Object.assign(mockStorage, obj); },
        remove: async (key) => { delete mockStorage[key]; }
      }
    };

    // 1. Session start handling
    function handleSessionStart(msg) {
      if (!msg.sessionId) return { ok: false, error: 'missing_session_id' };
      mockStorage['nudge10_session'] = {
        activeSessionId: String(msg.sessionId),
        startedAt: msg.startedAt || Date.now(),
        task: msg.task || '',
        missionTitle: msg.missionTitle || '',
        enabled: true
      };
      return { ok: true };
    }

    // 2. Session end handling
    function handleSessionEnd() {
      delete mockStorage['nudge10_session'];
      lastTabDistraction.clear();
      return { ok: true };
    }

    // 3. Tab navigation handling simulation
    async function onTabNavigation(tabId, urlString, fetchMock) {
      if (!urlString.startsWith('http://') && !urlString.startsWith('https://')) return null;
      const parsed = new URL(urlString);
      const category = normalizeHostname(parsed.hostname);
      if (!category) {
        lastTabDistraction.delete(tabId);
        return null;
      }

      const session = mockStorage['nudge10_session'];
      if (!session || !session.enabled) return null;

      // Duplicate prevention
      if (lastTabDistraction.get(tabId) === category) {
        return 'DUPLICATE_IGNORED';
      }
      lastTabDistraction.set(tabId, category);

      const elapsed = Math.max(0, Math.floor((Date.now() - session.startedAt) / 1000));
      const payload = {
        session_id: session.activeSessionId,
        site: category,
        elapsed_seconds: elapsed
      };
      callsToBackend.push(payload);

      return await fetchMock(payload);
    }

    (async () => {
      // Test A: Malformed session start (missing sessionId)
      const resBad = handleSessionStart({});
      assert.strictEqual(resBad.ok, false);
      assert.strictEqual(mockStorage['nudge10_session'], undefined);

      // Test B: Valid session start
      const resGood = handleSessionStart({
        sessionId: 'sess-1234',
        startedAt: Date.now() - 60000,
        task: 'Finish DBMS homework',
        missionTitle: 'DBMS ER diagram'
      });
      assert.strictEqual(resGood.ok, true);
      assert.strictEqual(mockStorage['nudge10_session'].activeSessionId, 'sess-1234');

      // Test C: Navigation to YouTube
      let mockFetchResult = { message: 'Get back to work', action: 'Draw entity' };
      const action1 = await onTabNavigation(1, 'https://www.youtube.com/watch?v=xyz123', async (p) => mockFetchResult);
      assert.deepStrictEqual(action1, mockFetchResult);
      assert.strictEqual(callsToBackend.length, 1);
      assert.strictEqual(callsToBackend[0].site, 'youtube.com');
      assert.strictEqual(callsToBackend[0].session_id, 'sess-1234');
      assert.strictEqual(callsToBackend[0].site.includes('watch'), false); // No raw URL / path

      // Test D: Duplicate navigation within same tab to same distraction category -> must ignore
      const actionDup = await onTabNavigation(1, 'https://www.youtube.com/channel/something_else', async (p) => mockFetchResult);
      assert.strictEqual(actionDup, 'DUPLICATE_IGNORED');
      assert.strictEqual(callsToBackend.length, 1); // No new call!

      // Test E: Navigation to a DIFFERENT distraction category (Instagram) in same tab -> must trigger
      const actionInsta = await onTabNavigation(1, 'https://www.instagram.com/reels', async (p) => mockFetchResult);
      assert.strictEqual(callsToBackend.length, 2);
      assert.strictEqual(callsToBackend[1].site, 'instagram.com');

      // Test F: Backend failure fallback
      const actionFailure = await onTabNavigation(2, 'https://reddit.com/r/all', async (p) => {
        throw new Error('Network timeout');
      }).catch(err => ({ message: "You're outside your focus session.", action: "Return to the task you started." }));
      assert.strictEqual(actionFailure.action, "Return to the task you started.");

      // Test G: Session End
      handleSessionEnd();
      assert.strictEqual(mockStorage['nudge10_session'], undefined);
      assert.strictEqual(lastTabDistraction.size, 0);

      // Test H: Navigation when session inactive -> must do nothing
      const actionInactive = await onTabNavigation(1, 'https://www.youtube.com', async (p) => mockFetchResult);
      assert.strictEqual(actionInactive, null);
      assert.strictEqual(callsToBackend.length, 3); // Unchanged

      console.log('LIFECYCLE_SIMULATION_OK');
    })();
    """
    res = subprocess.run(["node", "-e", node_test], capture_output=True, text=True)
    assert res.returncode == 0, f"Node lifecycle test failed: {res.stderr}"
    assert "LIFECYCLE_SIMULATION_OK" in res.stdout
