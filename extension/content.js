(function () {
  const host = window.location.hostname
  const configured = NUDGE10_CONFIG.DISTRACTION_HOSTS
  if (!configured.some((entry) => host === entry || host.endsWith(`.${entry}`))) return

  let overlayVisible = false

  function showOverlay() {
    if (overlayVisible || document.getElementById('nudge10-overlay')) return
    overlayVisible = true

    const overlay = document.createElement('div')
    overlay.id = 'nudge10-overlay'
    overlay.innerHTML = `
      <div class="n10-card">
        <div class="n10-kicker">NUDGE10</div>
        <div class="n10-title">You were supposed to be working.</div>
        <div class="n10-copy">You don't need a perfect day. You need the next few minutes.</div>
        <div class="n10-row">
          <button id="n10-back">Back to work</button>
          <button id="n10-stay">I actually need this</button>
        </div>
      </div>
    `

    document.documentElement.appendChild(overlay)
    document.getElementById('n10-back')?.addEventListener('click', () => {
      window.location.href = NUDGE10_CONFIG.WEB_APP_URL
    })
    document.getElementById('n10-stay')?.addEventListener('click', () => {
      overlay.remove()
      overlayVisible = false
    })
  }

  setTimeout(showOverlay, 1200)

  if (typeof chrome !== 'undefined' && chrome.runtime?.onMessage) {
    chrome.runtime.onMessage.addListener((message) => {
      if (message && message.type === 'NUDGE10_NAVIGATION') {
        const currentHost = window.location.hostname
        if (configured.some((entry) => currentHost === entry || currentHost.endsWith(`.${entry}`))) {
          setTimeout(showOverlay, 1200)
        }
      }
    })
  }
})()
