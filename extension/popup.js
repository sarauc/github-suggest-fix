const $ = (id) => document.getElementById(id);

const anthropicKeyInput = $("anthropicKey");
const githubTokenInput  = $("githubToken");
const backendUrlInput   = $("backendUrl");
const saveBtn           = $("saveBtn");
const errorMsg          = $("errorMsg");
const savedMsg          = $("savedMsg");
const statusDot         = $("statusDot");
const backendStatusLabel = $("backendStatus");

// ── Load saved settings ───────────────────────────────

chrome.storage.sync.get(["anthropicKey", "githubToken", "backendUrl"], (data) => {
  if (data.anthropicKey)  anthropicKeyInput.value = data.anthropicKey;
  if (data.githubToken)   githubTokenInput.value  = data.githubToken;
  backendUrlInput.value = data.backendUrl || "http://127.0.0.1:8765";
});

// ── Backend status ────────────────────────────────────

chrome.runtime.sendMessage({ type: "GET_BACKEND_STATUS" }, (res) => {
  if (chrome.runtime.lastError) return;
  updateBackendStatus(res?.alive ?? false);
});

function updateBackendStatus(alive) {
  statusDot.className = "status-dot " + (alive ? "alive" : "dead");
  backendStatusLabel.className = "backend-label " + (alive ? "alive" : "dead");
  backendStatusLabel.textContent = alive
    ? "✓ Backend running"
    : "✗ Backend offline — run: bash start.sh";
}

// ── Save ──────────────────────────────────────────────

saveBtn.addEventListener("click", () => {
  const anthropicKey = anthropicKeyInput.value.trim();
  const githubToken  = githubTokenInput.value.trim();
  const backendUrl   = backendUrlInput.value.trim() || "http://127.0.0.1:8765";

  // Validation
  let errors = [];
  if (!anthropicKey) errors.push("Anthropic API key is required.");
  if (!githubToken)  errors.push("GitHub token is required.");
  if (anthropicKey && !anthropicKey.startsWith("sk-ant-"))
    errors.push("Anthropic key should start with sk-ant-");
  if (githubToken && !githubToken.startsWith("ghp_") && !githubToken.startsWith("github_pat_"))
    errors.push("GitHub token should start with ghp_ or github_pat_");

  anthropicKeyInput.classList.toggle("error", !anthropicKey);
  githubTokenInput.classList.toggle("error",  !githubToken);

  if (errors.length > 0) {
    errorMsg.textContent = errors.join(" ");
    errorMsg.hidden = false;
    savedMsg.hidden = true;
    return;
  }

  errorMsg.hidden = true;
  chrome.storage.sync.set({ anthropicKey, githubToken, backendUrl }, () => {
    savedMsg.hidden = false;
    setTimeout(() => { savedMsg.hidden = true; }, 2000);
  });
});

// Clear error state on input
[anthropicKeyInput, githubTokenInput].forEach((el) => {
  el.addEventListener("input", () => {
    el.classList.remove("error");
    errorMsg.hidden = true;
  });
});

// ── Re-index current repo ─────────────────────────────

const reindexBtn    = $("reindexBtn");
const reindexStatus = $("reindexStatus");

function extractRepo(url) {
  const m = url.match(/github\.com\/([^/]+\/[^/]+)\/pull\//);
  return m ? m[1] : null;
}

chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
  const repo = extractRepo(tabs[0]?.url || "");
  if (repo) {
    reindexBtn.textContent = `Re-index ${repo}`;
    reindexBtn.dataset.repo = repo;
    reindexBtn.hidden = false;
  }
});

reindexBtn.addEventListener("click", async () => {
  const repo = reindexBtn.dataset.repo;
  if (!repo) return;

  const data = await new Promise((resolve) =>
    chrome.storage.sync.get(["githubToken", "anthropicKey", "backendUrl"], resolve)
  );

  if (!data.githubToken || !data.anthropicKey) {
    reindexStatus.textContent = "Save your API keys first.";
    reindexStatus.className = "reindex-status error";
    reindexStatus.hidden = false;
    return;
  }

  const backendUrl = data.backendUrl || "http://127.0.0.1:8765";
  reindexBtn.disabled = true;
  reindexStatus.textContent = "Starting re-index…";
  reindexStatus.className = "reindex-status";
  reindexStatus.hidden = false;

  try {
    const res = await fetch(`${backendUrl}/index`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        repo,
        github_token:  data.githubToken,
        anthropic_key: data.anthropicKey,
        force: true,
      }),
    });
    const json = await res.json();
    reindexStatus.textContent = json.status === "indexing"
      ? "Indexing started — check back in a minute."
      : (json.message || "Done.");
  } catch {
    reindexStatus.textContent = "Could not reach backend.";
    reindexStatus.className = "reindex-status error";
  } finally {
    reindexBtn.disabled = false;
  }
});
