// ── Constants ─────────────────────────────────────────────────────

const BUTTON_CLASS  = "gh-ai-help-btn";
const INJECTED_ATTR = "data-ai-injected";

// ── State ─────────────────────────────────────────────────────────

let backendAlive = false;
let currentUserLogin = null;
let prAuthorLogin = null;

// ── Initialise ────────────────────────────────────────────────────

async function init() {
  if (!isPRPage()) return;

  currentUserLogin = getCurrentUserLogin();
  prAuthorLogin    = getPRAuthorLogin();

  if (!currentUserLogin || !prAuthorLogin) return;
  if (currentUserLogin !== prAuthorLogin) return;

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

  // Watch for dynamically loaded comment threads
  const observer = new MutationObserver(debounce(injectButtons, 300));
  observer.observe(document.body, { childList: true, subtree: true });
}

// ── Page detection ────────────────────────────────────────────────

function isPRPage() {
  return /\/pull\/\d+/.test(window.location.pathname);
}

function getCurrentUserLogin() {
  return document.querySelector('meta[name="user-login"]')?.getAttribute("content") || null;
}

function getPRAuthorLogin() {
  // Try multiple selectors GitHub uses across its UI versions
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

// ── Comment selectors ─────────────────────────────────────────────

function findUninjectedActionBars() {
  // Target the action bar directly — this avoids double-matching nested elements.
  // GitHub uses .timeline-comment-actions for inline review comments.
  return document.querySelectorAll(
    `.timeline-comment-actions:not([${INJECTED_ATTR}])`
  );
}

// ── Comment ID extraction ─────────────────────────────────────────

function extractCommentId(actionBarEl) {
  const commentContainer = actionBarEl.closest(
    ".review-comment, .js-comment, [id^='discussion_r'], .timeline-comment"
  );
  if (!commentContainer) return null;

  // 1. Look for delete form — action="/repo/pull/1/review_comment/12345"
  const deleteForm = commentContainer.querySelector(
    'form[action*="review_comment"]'
  );
  if (deleteForm) {
    const match = deleteForm.action.match(/review_comment\/(\d+)/);
    if (match) return match[1];
  }

  // 2. Look for a hidden input with the comment ID value
  const hiddenInput = commentContainer.querySelector('input[name="input[id]"]');
  if (hiddenInput?.value) return hiddenInput.value;

  // 3. Look for permalink anchor — href="#discussion_r12345"
  const permalink = commentContainer.querySelector(
    'a[href*="#discussion_r"], a[id*="discussion_r"]'
  );
  if (permalink) {
    const match = (permalink.href || permalink.id).match(/discussion_r(\d+)/);
    if (match) return match[1];
  }

  // 4. Fall back to container's own id attribute
  const id = commentContainer.id || "";
  const match = id.match(/\d+/);
  return match ? match[0] : null;
}

// ── Button injection ──────────────────────────────────────────────

function injectButtons() {
  const actionBars = findUninjectedActionBars();
  actionBars.forEach((actionBar) => {
    // Guard: skip if a button already exists in this bar
    if (actionBar.querySelector(`.${BUTTON_CLASS}`)) {
      actionBar.setAttribute(INJECTED_ATTR, "true");
      return;
    }

    const commentId = extractCommentId(actionBar);
    if (!commentId) {
      actionBar.setAttribute(INJECTED_ATTR, "true"); // skip permanently
      return;
    }

    actionBar.setAttribute(INJECTED_ATTR, "true");

    const btn = createHelpButton(commentId, actionBar);
    actionBar.appendChild(btn);
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
  // Don't use btn.disabled — disabled elements don't show tooltips in Chrome
  btn.title = backendAlive
    ? "Get AI help understanding this comment"
    : "Backend offline — run: bash start.sh";
  btn.classList.toggle("gh-ai-offline", !backendAlive);
  btn.setAttribute("aria-disabled", String(!backendAlive));
}

function extractCommentBody(actionBarEl) {
  const container = actionBarEl.closest(
    ".review-comment, .js-comment, .timeline-comment"
  );
  return container?.querySelector(".comment-body")?.innerText?.trim() || "";
}

// ── Utilities ─────────────────────────────────────────────────────

function debounce(fn, ms) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

// ── Boot ──────────────────────────────────────────────────────────

// Re-init on GitHub SPA navigation
let lastPath = location.pathname;
new MutationObserver(debounce(() => {
  if (location.pathname !== lastPath) {
    lastPath = location.pathname;
    init();
  }
}, 500)).observe(document.body, { childList: true, subtree: true });

init();
