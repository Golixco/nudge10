chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status !== 'complete' || !tab.url) return

  let host
  try {
    host = new URL(tab.url).hostname
  } catch {
    return
  }

  chrome.tabs.sendMessage(tabId, {
    type: 'NUDGE10_NAVIGATION',
    host
  }).catch(() => {})
})
