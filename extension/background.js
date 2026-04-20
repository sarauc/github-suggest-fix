const BACKEND_URL = "http://127.0.0.1:8765";
const PING_INTERVAL_MS = 30_000;

let backendAlive = false;

async function pingBackend() {
  try {
    const res = await fetch(`${BACKEND_URL}/health`, { signal: AbortSignal.timeout(2000) });
    backendAlive = res.ok;
  } catch {
    backendAlive = false;
  }
  // Broadcast to all content scripts
  chrome.tabs.query({ url: "https://github.com/*/pull/*" }, (tabs) => {
    for (const tab of tabs) {
      chrome.tabs.sendMessage(tab.id, {
        type: "BACKEND_STATUS",
        alive: backendAlive,
      }).catch(() => {}); // tab may not have content script yet
    }
  });
}

// Ping on startup and on interval
pingBackend();
setInterval(pingBackend, PING_INTERVAL_MS);

// Handle messages from content scripts
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === "GET_BACKEND_STATUS") {
    sendResponse({ alive: backendAlive });
    return true;
  }

  if (msg.type === "GET_SETTINGS") {
    chrome.storage.sync.get(["githubToken", "anthropicKey", "backendUrl"], (data) => {
      sendResponse({
        githubToken:  data.githubToken  || "",
        anthropicKey: data.anthropicKey || "",
        backendUrl:   data.backendUrl   || BACKEND_URL,
      });
    });
    return true; // keep channel open for async response
  }
});
