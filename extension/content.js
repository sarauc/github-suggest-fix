// ── Constants ─────────────────────────────────────────────────────

const BUTTON_CLASS   = "gh-ai-help-btn";
const INJECTED_ATTR  = "data-ai-injected";
const BACKEND_URL    = "http://127.0.0.1:8765";

// ── State ─────────────────────────────────────────────────────────

let backendAlive        = false;
let currentUserLogin    = null;
let prAuthorLogin       = null;
let activeCommentId     = null;
let activeCommentBody   = "";   // saved for chat context re-injection
let conversationHistory = [];   // [{role, content}] for current comment
let currentReader       = null; // active SSE reader — aborted on panel close
let panelListenerActive = false; // ensures gh-ai:open listener is registered only once

// ── Initialise ────────────────────────────────────────────────────

async function init() {
  if (!isPRPage()) return;

  currentUserLogin = getCurrentUserLogin();
  prAuthorLogin    = getPRAuthorLogin();

  if (!currentUserLogin || !prAuthorLogin) return;
  if (currentUserLogin !== prAuthorLogin) return;

  createPanel();

  chrome.runtime.sendMessage({ type: "GET_BACKEND_STATUS" }, (res) => {
    backendAlive = res?.alive ?? false;
    injectButtons();
  });

  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === "BACKEND_STATUS") {
      backendAlive = msg.alive;
      document.querySelectorAll(`.${BUTTON_CLASS}`).forEach(updateButtonState);
    }
  });

  if (!panelListenerActive) {
    document.addEventListener("gh-ai:open", (e) => openPanel(e.detail));
    panelListenerActive = true;
  }

  const observer = new MutationObserver(debounce(injectButtons, 300));
  observer.observe(document.body, { childList: true, subtree: true });
}

// ── Page / user detection ─────────────────────────────────────────

function isPRPage() {
  return /\/pull\/\d+/.test(window.location.pathname);
}

function getCurrentUserLogin() {
  return document.querySelector('meta[name="user-login"]')?.getAttribute("content") || null;
}

function getPRAuthorLogin() {
  const selectors = [
    ".gh-header-meta a.author",
    ".pull-request-tab-content a.author",
    'a[data-hovercard-type="user"].author',
    ".js-issue-sidebar-form a[data-hovercard-type='user']",
  ];
  for (const sel of selectors) {
    const el = document.querySelector(sel);
    if (el?.textContent?.trim()) return el.textContent.trim();
  }
  return null;
}

function getPRInfo() {
  // pathname: /owner/repo/pull/123
  const parts = window.location.pathname.split("/").filter(Boolean);
  return {
    repo:     `${parts[0]}/${parts[1]}`,
    prNumber: parseInt(parts[3], 10),
  };
}

// ── Button injection ──────────────────────────────────────────────

function findUninjectedActionBars() {
  return document.querySelectorAll(
    `.timeline-comment-actions:not([${INJECTED_ATTR}])`
  );
}

function extractCommentId(actionBarEl) {
  const container = actionBarEl.closest(
    ".review-comment, .js-comment, [id^='discussion_r'], .timeline-comment"
  );
  if (!container) return null;

  const deleteForm = container.querySelector('form[action*="review_comment"]');
  if (deleteForm) {
    const m = deleteForm.action.match(/review_comment\/(\d+)/);
    if (m) return m[1];
  }

  const hiddenInput = container.querySelector('input[name="input[id]"]');
  if (hiddenInput?.value) return hiddenInput.value;

  const permalink = container.querySelector('a[href*="#discussion_r"], a[id*="discussion_r"]');
  if (permalink) {
    const m = (permalink.href || permalink.id).match(/discussion_r(\d+)/);
    if (m) return m[1];
  }

  const m = (container.id || "").match(/\d+/);
  return m ? m[0] : null;
}

function extractCommentBody(actionBarEl) {
  const container = actionBarEl.closest(".review-comment, .js-comment, .timeline-comment");
  return container?.querySelector(".comment-body")?.innerText?.trim() || "";
}

function injectButtons() {
  findUninjectedActionBars().forEach((bar) => {
    if (bar.querySelector(`.${BUTTON_CLASS}`)) {
      bar.setAttribute(INJECTED_ATTR, "true");
      return;
    }
    const commentId = extractCommentId(bar);
    bar.setAttribute(INJECTED_ATTR, "true");
    if (!commentId) return;

    const btn = createHelpButton(commentId, bar);
    bar.appendChild(btn);
  });
}

function createHelpButton(commentId, actionBarEl) {
  const btn = document.createElement("button");
  btn.className = BUTTON_CLASS;
  btn.dataset.commentId = commentId;
  btn.type = "button";
  btn.innerHTML = `<span class="gh-ai-sparkle">✦</span> Get AI Help`;
  updateButtonState(btn);

  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    if (btn.classList.contains("gh-ai-offline")) return;
    document.dispatchEvent(new CustomEvent("gh-ai:open", {
      detail: {
        commentId,
        commentBody: extractCommentBody(actionBarEl),
      }
    }));
  });

  return btn;
}

function updateButtonState(btn) {
  btn.title = backendAlive
    ? "Get AI help understanding this comment"
    : "Backend offline — run: bash start.sh";
  btn.classList.toggle("gh-ai-offline", !backendAlive);
  btn.setAttribute("aria-disabled", String(!backendAlive));
}

// ── Panel DOM ─────────────────────────────────────────────────────

function createPanel() {
  if (document.getElementById("gh-ai-panel")) return;

  const panel = document.createElement("div");
  panel.id = "gh-ai-panel";
  panel.className = "gh-ai-panel-hidden";
  panel.innerHTML = `
    <div class="gh-ai-panel-inner">
      <div class="gh-ai-panel-header">
        <div class="gh-ai-orb">✦</div>
        <div class="gh-ai-panel-title-block">
          <div class="gh-ai-panel-title">AI Code Reviewer</div>
          <div class="gh-ai-panel-subtitle" id="gh-ai-subtitle"></div>
        </div>
        <button class="gh-ai-panel-close" id="gh-ai-close" title="Close">×</button>
      </div>

      <div class="gh-ai-panel-body" id="gh-ai-body">
        <div class="gh-ai-loading" id="gh-ai-loading">
          <div class="gh-ai-spinner"></div>
          <span>Analyzing comment…</span>
        </div>
        <div class="gh-ai-messages" id="gh-ai-messages"></div>
      </div>

      <div class="gh-ai-input-row" id="gh-ai-input-row">
        <input
          id="gh-ai-input"
          class="gh-ai-input"
          type="text"
          placeholder="Ask a follow-up question…"
          autocomplete="off"
        />
        <button id="gh-ai-send" class="gh-ai-send-btn" title="Send">↑</button>
      </div>
    </div>
  `;

  document.body.appendChild(panel);

  document.getElementById("gh-ai-close").addEventListener("click", closePanel);

  const input = document.getElementById("gh-ai-input");
  document.getElementById("gh-ai-send").addEventListener("click", () => sendFollowUp());
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendFollowUp(); }
  });
}

// ── localStorage persistence ──────────────────────────────────────

function storageKey(repo, prNumber, commentId) {
  return `gh-ai:${repo}:${prNumber}:${commentId}`;
}

function saveConversation(repo, prNumber, commentId, history) {
  if (!history.length) return;
  try {
    localStorage.setItem(storageKey(repo, prNumber, commentId), JSON.stringify(history));
  } catch { /* storage full — silently skip */ }
}

function loadConversation(repo, prNumber, commentId) {
  try {
    const raw = localStorage.getItem(storageKey(repo, prNumber, commentId));
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

// ── Indexing flow ─────────────────────────────────────────────────

async function ensureIndexed(repo, settings) {
  // Check current index status
  const res = await fetch(
    `${settings.backendUrl}/index/status?repo=${encodeURIComponent(repo)}`
  );
  const status = await res.json();

  if (status.status === "indexed") return true;
  if (status.status === "indexing") {
    showIndexingProgress(status.progress || 0);
    return await pollUntilIndexed(repo, settings);
  }

  // Not indexed yet — trigger it
  await fetch(`${settings.backendUrl}/index`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      repo,
      github_token:  settings.githubToken,
      anthropic_key: settings.anthropicKey,
    }),
  });

  showIndexingProgress(0);
  return await pollUntilIndexed(repo, settings);
}

async function pollUntilIndexed(repo, settings) {
  const deadline = Date.now() + 5 * 60 * 1000; // 5 min timeout

  while (Date.now() < deadline) {
    await sleep(3000);
    const res = await fetch(
      `${settings.backendUrl}/index/status?repo=${encodeURIComponent(repo)}`
    );
    const status = await res.json();
    showIndexingProgress(status.progress || 0);

    if (status.status === "indexed") return true;
    if (status.status === "error") {
      showIndexingProgress(null, status.error || "Indexing failed");
      return false; // proceed without RAG
    }
  }

  // Timeout — proceed without RAG (fallback)
  showIndexingProgress(null, "Indexing timed out — analyzing without full codebase context");
  return false;
}

function showIndexingProgress(progress, errorMsg) {
  const loadingEl = document.getElementById("gh-ai-loading");
  if (errorMsg) {
    loadingEl.innerHTML = `<span style="color:#f85149;font-size:12px">${escapeHtml(errorMsg)}</span>`;
    setTimeout(() => {
      loadingEl.innerHTML = `<div class="gh-ai-spinner"></div><span>Analyzing comment…</span>`;
    }, 3000);
    return;
  }
  const pct = Math.round((progress || 0) * 100);
  loadingEl.innerHTML = `
    <div class="gh-ai-spinner"></div>
    <span>Indexing repo… ${pct}%</span>
  `;
}

// ── Panel open / close ────────────────────────────────────────────

async function openPanel({ commentId, commentBody }) {
  abortCurrentStream();

  const { repo, prNumber } = getPRInfo();
  activeCommentId   = commentId;
  activeCommentBody = commentBody;

  const panel = document.getElementById("gh-ai-panel");
  panel.classList.remove("gh-ai-panel-hidden");
  panel.classList.add("gh-ai-panel-visible");

  document.getElementById("gh-ai-subtitle").textContent =
    commentBody ? `"${commentBody.slice(0, 60)}…"` : `Comment #${commentId}`;

  document.getElementById("gh-ai-loading").style.display = "flex";
  document.getElementById("gh-ai-loading").innerHTML =
    `<div class="gh-ai-spinner"></div><span>Analyzing comment…</span>`;
  document.getElementById("gh-ai-messages").innerHTML = "";
  document.getElementById("gh-ai-input").value = "";
  document.getElementById("gh-ai-input-row").style.display = "none";

  const settings = await getSettings();
  if (!settings.anthropicKey || !settings.githubToken) {
    showError("Please add your Anthropic API key and GitHub token in the extension settings.");
    return;
  }

  // ── Restore prior conversation if exists ──────────────────────
  const saved = loadConversation(repo, prNumber, commentId);
  if (saved && saved.length > 0) {
    conversationHistory = saved;
    document.getElementById("gh-ai-loading").style.display = "none";
    showRestoredConversation(saved);
    document.getElementById("gh-ai-input-row").style.display = "flex";
    document.getElementById("gh-ai-input").focus();
    return;
  }

  conversationHistory = [];

  // ── Ensure repo is indexed (trigger if needed) ─────────────────
  await ensureIndexed(repo, settings);

  // Reset loading label before streaming
  document.getElementById("gh-ai-loading").innerHTML =
    `<div class="gh-ai-spinner"></div><span>Analyzing comment…</span>`;

  await streamAnalyze({ repo, prNumber, commentId, commentBody, settings });
}

function closePanel() {
  abortCurrentStream();

  // Persist conversation before closing
  if (activeCommentId && conversationHistory.length) {
    const { repo, prNumber } = getPRInfo();
    saveConversation(repo, prNumber, activeCommentId, conversationHistory);
  }

  const panel = document.getElementById("gh-ai-panel");
  if (!panel) return;
  panel.classList.remove("gh-ai-panel-visible");
  panel.classList.add("gh-ai-panel-hidden");
  activeCommentId = null;
}

function abortCurrentStream() {
  if (currentReader) {
    currentReader.cancel();
    currentReader = null;
  }
}

// ── Settings ──────────────────────────────────────────────────────

function getSettings() {
  return new Promise((resolve) => {
    chrome.storage.sync.get(["anthropicKey", "githubToken", "backendUrl"], (data) => {
      resolve({
        anthropicKey: data.anthropicKey  || "",
        githubToken:  data.githubToken   || "",
        backendUrl:   data.backendUrl    || BACKEND_URL,
      });
    });
  });
}

// ── SSE streaming ─────────────────────────────────────────────────

async function streamAnalyze({ repo, prNumber, commentId, commentBody, settings }) {
  try {
    const response = await fetch(`${settings.backendUrl}/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        repo,
        pr_number:     prNumber,
        comment_id:    commentId,
        comment_body:  commentBody,
        github_token:  settings.githubToken,
        anthropic_key: settings.anthropicKey,
        // diff_hunk, file_path, file_content — fetched by backend automatically
      }),
    });

    if (!response.ok) {
      showError(`Backend error: HTTP ${response.status}`);
      return;
    }

    document.getElementById("gh-ai-loading").style.display = "none";
    const msgEl = appendMessage("assistant");

    await readSSEStream(response, (token) => {
      appendToken(msgEl, token);
    });

    // Save to conversation history
    conversationHistory.push({
      role: "assistant",
      content: msgEl.dataset.raw || msgEl.innerText,
    });

    // Show input bar
    document.getElementById("gh-ai-input-row").style.display = "flex";
    document.getElementById("gh-ai-input").focus();

  } catch (err) {
    showError(`Could not reach backend: ${err.message}`);
  }
}

async function streamChat(userMessage, settings) {
  try {
    const response = await fetch(`${settings.backendUrl}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        repo:                 getPRInfo().repo,
        comment_id:           activeCommentId,
        user_message:         userMessage,
        conversation_history: conversationHistory,
        anthropic_key:        settings.anthropicKey,
        github_token:         settings.githubToken,
        comment_body:         activeCommentBody,
      }),
    });

    if (!response.ok) {
      showError(`Backend error: HTTP ${response.status}`);
      return;
    }

    const msgEl = appendMessage("assistant");

    await readSSEStream(response, (token) => {
      appendToken(msgEl, token);
    });

    conversationHistory.push({
      role: "assistant",
      content: msgEl.dataset.raw || msgEl.innerText,
    });

  } catch (err) {
    showError(`Could not reach backend: ${err.message}`);
  }
}

async function readSSEStream(response, onToken) {
  const reader = response.body.getReader();
  currentReader = reader;
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop(); // keep incomplete last line

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        try {
          const event = JSON.parse(line.slice(6));
          if (event.type === "token") onToken(event.content);
          if (event.type === "error") { showError(event.message); return; }
          if (event.type === "done")  return;
        } catch { /* skip malformed lines */ }
      }
    }
  } finally {
    currentReader = null;
  }
}

// ── Follow-up ─────────────────────────────────────────────────────

async function sendFollowUp() {
  const input = document.getElementById("gh-ai-input");
  const text = input.value.trim();
  if (!text) return;

  abortCurrentStream();
  input.value = "";

  // Show user message
  const userEl = appendMessage("user");
  userEl.innerHTML = escapeHtml(text);
  conversationHistory.push({ role: "user", content: text });

  const settings = await getSettings();
  await streamChat(text, settings);
}

// ── Message rendering ─────────────────────────────────────────────

function appendMessage(role) {
  const messages = document.getElementById("gh-ai-messages");
  const el = document.createElement("div");
  el.className = `gh-ai-message gh-ai-message-${role}`;
  el.dataset.raw = "";
  messages.appendChild(el);
  // Scroll to bottom
  const body = document.getElementById("gh-ai-body");
  body.scrollTop = body.scrollHeight;
  return el;
}

function appendToken(msgEl, token) {
  msgEl.dataset.raw += token;
  msgEl.innerHTML = renderMarkdown(msgEl.dataset.raw);
  // Keep scrolled to bottom
  const body = document.getElementById("gh-ai-body");
  body.scrollTop = body.scrollHeight;
}

// Lightweight regex markdown renderer
function renderMarkdown(text) {
  return text
    .split("\n")
    .map((line) => {
      // Headers
      if (line.startsWith("#### ")) return `<h4>${esc(line.slice(5))}</h4>`;
      if (line.startsWith("### "))  return `<h3>${esc(line.slice(4))}</h3>`;
      if (line.startsWith("## "))   return `<h2>${esc(line.slice(3))}</h2>`;
      // List items
      if (/^[-*] /.test(line))      return `<li>${inlineMarkdown(line.slice(2))}</li>`;
      if (/^✓ |^- ✓ /.test(line))   return `<li class="pro">${inlineMarkdown(line.replace(/^[-*]?\s?✓\s?/, ""))}</li>`;
      if (/^✗ |^- ✗ /.test(line))   return `<li class="con">${inlineMarkdown(line.replace(/^[-*]?\s?✗\s?/, ""))}</li>`;
      // Blank lines
      if (line.trim() === "")       return "<br>";
      return `<p>${inlineMarkdown(line)}</p>`;
    })
    .join("");
}

function inlineMarkdown(text) {
  return esc(text)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g,     "<em>$1</em>")
    .replace(/`(.+?)`/g,       "<code>$1</code>");
}

function esc(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function escapeHtml(str) { return esc(str); }

function showError(msg) {
  document.getElementById("gh-ai-loading").style.display = "none";
  document.getElementById("gh-ai-input-row").style.display = "none";
  const messages = document.getElementById("gh-ai-messages");
  messages.innerHTML = `<div class="gh-ai-error">${escapeHtml(msg)}</div>`;
}

// ── Restored conversation ─────────────────────────────────────────

function showRestoredConversation(history) {
  const messages = document.getElementById("gh-ai-messages");
  messages.innerHTML = "";

  // "Continue conversation" banner
  const banner = document.createElement("div");
  banner.className = "gh-ai-continue-banner";
  banner.textContent = "↩ Previous conversation restored";
  messages.appendChild(banner);

  for (const msg of history) {
    const el = appendMessage(msg.role);
    el.dataset.raw = msg.content;
    el.innerHTML = msg.role === "assistant"
      ? renderMarkdown(msg.content)
      : escapeHtml(msg.content);
  }

  // Add "Start fresh" link
  const fresh = document.createElement("button");
  fresh.className = "gh-ai-start-fresh";
  fresh.textContent = "Start fresh analysis";
  fresh.addEventListener("click", async () => {
    const { repo, prNumber } = getPRInfo();
    localStorage.removeItem(storageKey(repo, prNumber, activeCommentId));
    conversationHistory = [];
    messages.innerHTML = "";
    document.getElementById("gh-ai-loading").style.display = "flex";
    document.getElementById("gh-ai-input-row").style.display = "none";
    const settings = await getSettings();
    await streamAnalyze({
      repo, prNumber,
      commentId: activeCommentId,
      commentBody: "",
      settings,
    });
  });
  messages.appendChild(fresh);

  // Scroll to bottom
  document.getElementById("gh-ai-body").scrollTop = 9999;
}

// ── Utilities ─────────────────────────────────────────────────────

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

function debounce(fn, ms) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

// ── Boot ──────────────────────────────────────────────────────────

let lastPath = location.pathname;
new MutationObserver(debounce(() => {
  if (location.pathname !== lastPath) {
    lastPath = location.pathname;
    closePanel();
    init();
  }
}, 500)).observe(document.body, { childList: true, subtree: true });

init();
