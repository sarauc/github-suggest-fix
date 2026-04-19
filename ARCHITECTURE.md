# Architecture Design & Implementation Plan
## GitHub PR Review AI Assistant — MVP

**Version:** 1.0
**Date:** April 19, 2026
**Scope:** Local-only prototype. No cloud infrastructure.

---

## 1. System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        github.com (Browser)                     │
│                                                                 │
│   PR Page DOM                                                   │
│   ┌──────────────────────────────────────┐                      │
│   │  Review Comment                      │                      │
│   │  "Consider streaming instead..."     │                      │
│   │                             [✦ AI]  │◄── injected button   │
│   └──────────────────────────────────────┘                      │
│                    │ click                                       │
│                    ▼                                             │
│   ┌──────────────────────────────────────┐                      │
│   │  AI Panel (Option B — dark purple)   │                      │
│   │  ┌─────────────────────────────────┐ │                      │
│   │  │  Streamed analysis + options    │ │                      │
│   │  └─────────────────────────────────┘ │                      │
│   │  [follow-up input]                   │                      │
│   └──────────────────────────────────────┘                      │
│           ▲                                                      │
│           │ SSE stream                                           │
└───────────┼──────────────────────────────────────────────────────┘
            │
            │ HTTP (localhost only)
            │
┌───────────┼──────────────────────────────────────────────────────┐
│           │         Local Backend (FastAPI)                      │
│           ▼                                                      │
│   ┌──────────────┐    ┌───────────────┐    ┌─────────────────┐  │
│   │  /analyze    │    │  /index       │    │  /health        │  │
│   │  /chat       │    │  /index/status│    │                 │  │
│   └──────┬───────┘    └──────┬────────┘    └─────────────────┘  │
│          │                   │                                   │
│          ▼                   ▼                                   │
│   ┌──────────────┐    ┌───────────────┐                         │
│   │  Context     │    │  Indexer      │                         │
│   │  Assembler   │    │  (async bg)   │                         │
│   └──────┬───────┘    └──────┬────────┘                         │
│          │                   │                                   │
│          ▼                   ▼                                   │
│   ┌──────────────┐    ┌───────────────┐    ┌─────────────────┐  │
│   │  ChromaDB    │◄───│  Chunker +    │    │  GitHub API     │  │
│   │  (embedded)  │    │  Embedder     │    │  Client         │  │
│   └──────┬───────┘    └───────────────┘    └────────┬────────┘  │
│          │                                           │           │
│          ▼                                           ▼           │
│   ┌──────────────┐                         ┌─────────────────┐  │
│   │  Anthropic   │                         │  github.com API │  │
│   │  Claude API  │                         │  (external)     │  │
│   └──────────────┘                         └─────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Tech Stack

| Layer | Choice | Rationale |
|---|---|---|
| Browser extension | Chrome MV3, vanilla JS | No bundler complexity for MVP |
| Backend framework | Python 3.8+ + FastAPI | Async-native, easy SSE, fast to iterate |
| ASGI server | Uvicorn | Ships with FastAPI |
| Vector store | ChromaDB (embedded) | Zero-config, runs in-process, no external server |
| Embeddings | `sentence-transformers` (`all-MiniLM-L6-v2`) | Local, free, ~80MB, good quality |
| AI model | `claude-sonnet-4-5` | Best cost/quality balance; configurable |
| Streaming | Server-Sent Events (SSE) | Simple, native browser support, no WebSocket overhead |
| Conversation storage | `localStorage` | Per-PRD requirement; zero backend dependency |
| GitHub auth | GitHub PAT (stored in `chrome.storage.sync`) | Reliable for MVP vs. fragile cookie extraction |

---

## 3. Repository Structure

```
github-suggest-fix/
├── extension/                  # Chrome Extension (MV3)
│   ├── manifest.json
│   ├── background.js           # Service worker — relay + health ping
│   ├── content.js              # DOM injection, panel UI, localStorage
│   ├── content.css             # Option B styles (purple/dark)
│   ├── popup.html              # Settings page
│   ├── popup.js
│   ├── popup.css
│   └── icons/
│       ├── icon16.png
│       ├── icon48.png
│       └── icon128.png
│
├── backend/                    # FastAPI local server
│   ├── main.py                 # App entrypoint + route registration
│   ├── routes/
│   │   ├── analyze.py          # POST /analyze, POST /chat
│   │   ├── index.py            # POST /index, GET /index/status
│   │   └── health.py           # GET /health
│   ├── services/
│   │   ├── context_assembler.py  # Builds prompt context
│   │   ├── github_client.py      # GitHub API wrapper
│   │   ├── indexer.py            # Repo fetch + chunk + embed
│   │   ├── vector_store.py       # ChromaDB wrapper
│   │   └── claude_client.py      # Anthropic streaming wrapper
│   ├── models.py               # Pydantic request/response models
│   ├── config.py               # Settings (port, paths, limits)
│   ├── requirements.txt
│   └── start.sh                # One-command startup script
│
├── design/
│   └── ui-exploration.html
├── PRD.md
├── ARCHITECTURE.md
└── README.md
```

---

## 4. Component Design

### 4.1 Chrome Extension

#### `manifest.json`
```json
{
  "manifest_version": 3,
  "name": "PR Review AI Assistant",
  "version": "0.1.0",
  "permissions": ["storage", "activeTab"],
  "host_permissions": [
    "https://github.com/*",
    "http://localhost:8765/*"
  ],
  "background": { "service_worker": "background.js" },
  "content_scripts": [{
    "matches": ["https://github.com/*/pull/*"],
    "js": ["content.js"],
    "css": ["content.css"],
    "run_at": "document_idle"
  }],
  "action": {
    "default_popup": "popup.html",
    "default_icon": "icons/icon48.png"
  }
}
```

#### `background.js` — responsibilities
- On install: store default backend URL (`http://localhost:8765`)
- Relay messages from content script to backend (fetch proxy to avoid CORS issues)
- Ping backend on content script load; cache alive/dead status

#### `content.js` — responsibilities
1. On `DOMContentLoaded`: detect if current page is a PR page
2. Identify PR author from DOM (`[data-hovercard-type="user"]` in the PR header)
3. Compare against current user login (from `meta[name="user-login"]`)
4. If match: scan for all inline review comment elements, inject `[✦ Get AI Help]` button
5. Handle `MutationObserver` for dynamically-loaded comment threads
6. On button click: open/close panel, load from localStorage or trigger analysis
7. Manage single panel instance (close previous on new open)
8. Save conversation to localStorage on panel close

**localStorage key format:**
```
gh-ai:{owner}/{repo}:{pr_number}:{comment_id}
```

**localStorage value:**
```json
[
  { "role": "assistant", "content": "...", "ts": 1713600000 },
  { "role": "user",      "content": "...", "ts": 1713600060 }
]
```

#### `popup.html` — Settings
- GitHub Personal Access Token (PAT) input — stored in `chrome.storage.sync`
- Anthropic API key input — stored in `chrome.storage.sync`
- Backend URL (default: `http://localhost:8765`) — editable
- "Index current repo" manual trigger button
- Backend status indicator (green/red dot)

---

### 4.2 Local Backend

#### Backend port: `8765` (avoids conflicts with common dev ports)

#### API surface

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness check — returns `{"status": "ok", "version": "0.1.0"}` |
| `POST` | `/analyze` | First-turn analysis — streams SSE |
| `POST` | `/chat` | Follow-up turn — streams SSE |
| `POST` | `/index` | Trigger repo indexing (async) |
| `GET` | `/index/status` | Poll indexing progress |

#### `POST /analyze` — request body
```json
{
  "repo": "owner/repo",
  "pr_number": 42,
  "comment_id": "IC_abc123",
  "comment_body": "Consider streaming instead...",
  "diff_hunk": "@@ -10,6 +10,8 @@ ...",
  "file_path": "src/process_data.py",
  "file_content": "...",
  "github_token": "ghp_...",
  "anthropic_key": "sk-ant-..."
}
```

#### `POST /chat` — request body
```json
{
  "repo": "owner/repo",
  "comment_id": "IC_abc123",
  "user_message": "Can you explain option 2 more?",
  "conversation_history": [
    { "role": "assistant", "content": "..." },
    { "role": "user",      "content": "..." }
  ],
  "anthropic_key": "sk-ant-..."
}
```

#### SSE stream format
```
data: {"type": "token", "content": "The reviewer"}
data: {"type": "token", "content": " is concerned"}
data: {"type": "done"}
data: {"type": "error", "message": "Rate limited"}
```

---

### 4.3 Context Assembler (`services/context_assembler.py`)

Builds the full prompt context for the first analysis turn:

```
[System prompt]
  — role definition
  — output format instructions (interpretation → options → pros/cons)
  — constraint: do not write a ready-to-paste fix

[User message]
  --- REVIEW COMMENT ---
  {comment_body}

  --- FILE: {file_path} ---
  {file_content}  (truncated to 8K tokens if needed)

  --- DIFF HUNK ---
  {diff_hunk}

  --- RELATED CONTEXT (from codebase) ---
  {top_5_rag_chunks}  (omitted if repo not yet indexed)
```

**Token budget (approximate):**
| Section | Max tokens |
|---|---|
| System prompt | 800 |
| Review comment | 500 |
| File content | 8,000 |
| Diff hunk | 1,000 |
| RAG chunks (5 × 400) | 2,000 |
| Conversation history | 2,000 |
| Response budget | 1,500 |
| **Total** | **~15,800** |

Fits comfortably within claude-sonnet-4-5's 200K context window.

---

### 4.4 GitHub Client (`services/github_client.py`)

Thin wrapper around GitHub REST API v3. All calls use the PAT from the request.

```python
# Key methods
get_pr_comment(repo, comment_id) → CommentData
get_file_content(repo, file_path, ref) → str
get_repo_tree(repo, ref) → list[TreeEntry]
get_file_blob(repo, blob_sha) → bytes
```

**Rate limiting:** GitHub allows 5,000 req/hr for authenticated requests. Indexing a 1,000-file repo ≈ 1,000 API calls (one per file blob). Within limit.

---

### 4.5 Indexer (`services/indexer.py`)

Runs as an async background task — does not block the API response.

**Indexing pipeline:**
```
1. fetch_repo_tree()         — get all file paths + SHAs via GitHub API
2. filter_files()            — skip binary, generated, >200KB files
3. fetch_blobs()             — download text content in batches of 10
4. chunk_files()             — split into ~400-token chunks with 50-token overlap
5. embed_chunks()            — sentence-transformers inference (local, CPU)
6. upsert_to_chromadb()      — store embeddings + metadata
```

**File filtering rules (skip if any match):**
- Extension in: `.png .jpg .gif .ico .svg .pdf .zip .tar .gz .lock .min.js .min.css`
- Path matches: `**/node_modules/**`, `**/.git/**`, `**/dist/**`, `**/build/**`
- File size > 200KB

**Chunking strategy:**
- Python/JS/TS: attempt AST-based splitting at function/class boundaries
- All others: fixed 400-token chunks, 50-token overlap
- Chunk metadata stored: `{repo, file_path, start_line, end_line, chunk_index}`

**Indexing state** (in-memory + persisted to `~/.gh-ai-assistant/index_state.json`):
```json
{
  "owner/repo": {
    "status": "indexed",
    "indexed_at": "2026-04-19T10:00:00Z",
    "file_count": 342,
    "chunk_count": 1840
  }
}
```

---

### 4.6 Vector Store (`services/vector_store.py`)

ChromaDB in embedded (in-process) mode. No separate server.

```python
# Storage path: ~/.gh-ai-assistant/chroma/
# Collection naming: "repo_{owner}_{repo_name}"

query_relevant_chunks(repo, query_text, top_k=5) → list[Chunk]
upsert_chunks(repo, chunks) → None
delete_repo_index(repo) → None
```

**Query strategy:** Embed the review comment text + file path as the search query. Top-5 chunks by cosine similarity are included in the prompt.

---

### 4.7 Claude Client (`services/claude_client.py`)

Streams tokens back via SSE. Uses Anthropic's Python SDK.

```python
async def stream_analysis(prompt, api_key, model) -> AsyncGenerator[str, None]:
    async with anthropic.AsyncAnthropic(api_key=api_key) as client:
        async with client.messages.stream(...) as stream:
            async for text in stream.text_stream:
                yield text
```

**Model:** `claude-sonnet-4-5` (default). Configurable via settings.
**Max output tokens:** 1,500 (sufficient for analysis + 3 options with pros/cons).

---

## 5. Data Models (`models.py`)

```python
class AnalyzeRequest(BaseModel):
    repo: str                    # "owner/repo"
    pr_number: int
    comment_id: str
    comment_body: str
    diff_hunk: str
    file_path: str
    file_content: str
    github_token: str
    anthropic_key: str

class ChatRequest(BaseModel):
    repo: str
    comment_id: str
    user_message: str
    conversation_history: list[Message]
    anthropic_key: str

class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str

class IndexRequest(BaseModel):
    repo: str                    # "owner/repo"
    github_token: str

class IndexStatus(BaseModel):
    repo: str
    status: Literal["not_indexed", "indexing", "indexed", "error"]
    progress: float              # 0.0 – 1.0
    file_count: int | None
    error: str | None
```

---

## 6. Security

> MVP threat model: the only attacker is a malicious website trying to abuse the extension or backend. The user is trusted.

| Risk | Mitigation |
|---|---|
| Backend accessible to any process | Bind only to `127.0.0.1:8765`, never `0.0.0.0` |
| CORS abuse from malicious sites | Backend CORS allowlist: `["https://github.com"]` only |
| GitHub PAT exfiltration | PAT stored in `chrome.storage.sync` (encrypted by Chrome), forwarded only to localhost, never logged |
| Anthropic key exfiltration | Same as above — forwarded per-request to localhost, never persisted in backend |
| Prompt injection via comment body | Comment content is placed in a clearly delimited user-turn block; system prompt is fixed and not user-influenced |
| Extension XSS | Panel HTML is constructed via DOM APIs (`createElement`, `textContent`), never `innerHTML` with untrusted data |
| ChromaDB data leakage | Stored at `~/.gh-ai-assistant/chroma/` — local filesystem, user-owned |

---

## 7. Performance

| Concern | Approach |
|---|---|
| First analysis latency | Target < 3s to first token. SSE streaming makes perceived latency low. |
| Indexing blocking UI | Indexer runs in `asyncio` background task. Panel shows live progress via polling `/index/status` every 2s. |
| Large file truncation | Files > 8K tokens truncated from the bottom before sending to Claude |
| Embedding inference speed | `all-MiniLM-L6-v2` processes ~1,000 chunks/min on CPU. 1,000-file repo indexes in ~2–5 min. |
| Repeated RAG queries | ChromaDB query is in-memory — typically < 50ms |
| Conversation context growth | Rolling window: always keep first AI message + last 6 message pairs |

---

## 8. Observability

Minimal but sufficient for a local prototype:

- **Structured logging:** Python `logging` module, JSON format, written to `~/.gh-ai-assistant/server.log`
- **Log levels:** INFO for request/response lifecycle, DEBUG for context assembly details, ERROR for failures
- **What gets logged:** request type, repo, comment_id, context token count, Claude response token count, latency, errors
- **What is never logged:** GitHub PAT, Anthropic key, file content, comment body (PII/sensitive)
- **Backend startup:** Print URL + version to stdout so the user sees the server is running

```
[INFO]  Server started at http://127.0.0.1:8765
[INFO]  analyze  repo=owner/repo comment=IC_abc  ctx_tokens=4821  latency=2.3s
[INFO]  index    repo=owner/repo files=342 chunks=1840 duration=183s
[ERROR] analyze  repo=owner/repo comment=IC_def  error=anthropic_rate_limit
```

---

## 9. Implementation Plan

Milestones are ordered by dependency. Each milestone should be independently testable.

---

### Milestone 1 — Backend Scaffold
**Goal:** A running FastAPI server with health check.

- [ ] Create `backend/` directory structure
- [ ] `requirements.txt`: `fastapi`, `uvicorn`, `anthropic`, `chromadb`, `sentence-transformers`, `httpx`, `python-dotenv`
- [ ] `main.py`: app init, CORS config (`127.0.0.1` only), route registration
- [ ] `GET /health` → `{"status": "ok"}`
- [ ] `config.py`: port (8765), ChromaDB path, log path
- [ ] `start.sh`: `uvicorn main:app --host 127.0.0.1 --port 8765`
- **Test:** `curl http://localhost:8765/health` returns 200

---

### Milestone 2 — GitHub API Client
**Goal:** Backend can fetch PR comment, file content, and repo tree.

- [ ] `services/github_client.py` with `httpx.AsyncClient`
- [ ] `get_pr_comment(repo, comment_id, token)` → comment body, diff hunk, file path
- [ ] `get_file_content(repo, file_path, ref, token)` → raw file string
- [ ] `get_repo_tree(repo, ref, token)` → flat list of `{path, sha, size, type}`
- [ ] `get_file_blob(repo, sha, token)` → decoded text
- [ ] Error handling: 401 (bad token), 403 (rate limit), 404 (not found)
- **Test:** Python script that calls each method against a real repo

---

### Milestone 3 — Repo Indexer + Vector Store
**Goal:** Backend can index a repo and answer semantic queries.

- [ ] `services/vector_store.py`: ChromaDB init, `upsert_chunks`, `query_relevant_chunks`, `delete_repo_index`
- [ ] `services/indexer.py`: pipeline (tree → filter → fetch → chunk → embed → upsert)
- [ ] File filter rules implemented
- [ ] Chunking: fixed-size with overlap (AST chunking deferred to post-MVP)
- [ ] `POST /index` → starts background task, returns `{"status": "indexing"}`
- [ ] `GET /index/status?repo=owner/repo` → returns `IndexStatus`
- [ ] Index state persisted to `~/.gh-ai-assistant/index_state.json`
- **Test:** Index a small public repo, query for a keyword, verify relevant chunks returned

---

### Milestone 4 — Claude Integration + Prompt
**Goal:** Backend can call Claude and stream a response.

- [ ] `services/claude_client.py`: async SSE streaming wrapper
- [ ] `services/context_assembler.py`: assemble prompt from comment + file + diff + RAG chunks
- [ ] System prompt written and tested (interpretation → options → pros/cons format)
- [ ] Token budget enforcement (truncate file content if needed)
- [ ] `POST /analyze` route: assembles context → streams Claude response as SSE
- [ ] `POST /chat` route: appends user message to history → streams response
- [ ] Error types mapped: `invalid_key`, `rate_limit`, `context_too_long`, `unknown`
- **Test:** POST a sample analyze request, verify streamed response matches expected format

---

### Milestone 5 — Chrome Extension Scaffold + Settings
**Goal:** Extension loads in Chrome, settings page works.

- [ ] `manifest.json` with correct permissions and content script match pattern
- [ ] `popup.html` + `popup.js`: GitHub PAT input, Anthropic key input, save to `chrome.storage.sync`
- [ ] `popup.css`: Option B dark styling for settings page
- [ ] `background.js`: backend health ping on startup, expose `isBackendAlive` state
- [ ] Settings validation: show error if either key is empty on save
- **Test:** Load unpacked extension, open popup, save keys, verify stored in `chrome.storage.sync`

---

### Milestone 6 — Content Script: Button Injection
**Goal:** "Get AI Help" button appears next to review comments when user is PR author.

- [ ] PR author detection (compare DOM user login vs PR author)
- [ ] Comment thread selector (target GitHub's inline review comment container)
- [ ] Inject `[✦ Get AI Help]` button per comment (Option B pill style: purple gradient)
- [ ] `MutationObserver` to catch dynamically-loaded comment threads
- [ ] Backend offline state: button shows "Backend offline" tooltip, disabled
- **Test:** Navigate to a GitHub PR, verify button appears next to each review comment

---

### Milestone 7 — Panel UI (Option B)
**Goal:** Clicking the button opens the bold dark panel with correct UX.

- [ ] Panel HTML structure injected into DOM (single instance, right-side anchored)
- [ ] Option B styles: dark purple/black, gradient header, AI orb, card-based approach layout
- [ ] Panel open/close animation (slide in from right)
- [ ] Loading state: "Analyzing..." spinner while waiting for first token
- [ ] SSE token streaming → append tokens to panel content in real time
- [ ] Markdown rendering for response (bold, italic, inline code — no external library, regex-based for MVP)
- [ ] Follow-up input bar at bottom
- [ ] Single-panel rule: opening a new panel closes the current one
- **Test:** Visual review against Option B mockup in `design/ui-exploration.html`

---

### Milestone 8 — End-to-End Flow + Persistence
**Goal:** Full workflow works: click → index (if needed) → analyze → chat → persist.

- [ ] Content script reads keys from `chrome.storage.sync`, forwards to backend per request
- [ ] First click on new repo: show "Indexing..." state, poll `/index/status`, switch to analysis when done
- [ ] First-time analysis triggers `/analyze` → streams into panel
- [ ] Follow-up sends `/chat` with full conversation history
- [ ] Panel close → serialize conversation to `localStorage`
- [ ] Panel re-open on same comment → restore from `localStorage`, show "Continue conversation" affordance
- **Test:** Full end-to-end on a real GitHub PR with a real review comment

---

### Milestone 9 — Error Handling + Corner Cases
**Goal:** All corner cases from PRD §7 are handled gracefully.

- [ ] CC 7.4: No GitHub token → panel error message
- [ ] CC 7.5: No Anthropic key → panel prompt to open settings
- [ ] CC 7.6: Invalid key / rate limit → specific error messages in panel
- [ ] CC 7.7: Backend not running → button disabled with tooltip
- [ ] CC 7.3: Large repo (>5 min indexing) → fallback to non-RAG analysis after timeout
- [ ] CC 7.9: Long conversation → rolling context window (keep first message + last 6 pairs)
- [ ] CC 7.11: Outdated comment → note in prompt
- [ ] CC 7.12: Navigation away mid-analysis → abort in-flight SSE connection
- [ ] CC 7.13: Multiple comment clicks → single panel instance rule enforced

---

### Milestone 10 — Polish + README
**Goal:** Someone else can clone the repo and run it in 5 minutes.

- [ ] `README.md`: setup steps (backend deps, Chrome unpacked extension install, API keys)
- [ ] `start.sh`: checks Python version, installs deps if needed, starts server
- [ ] Extension icon assets (16, 48, 128px)
- [ ] Manual re-index button in popup actually works
- [ ] "Clear conversation" button in panel
- [ ] Log file rotation (cap at 10MB)

---

## 10. Dependency Graph

```
M1 (Backend scaffold)
  └─► M2 (GitHub client)
        └─► M3 (Indexer + vector store)
              └─► M4 (Claude integration)  ◄─── M5 (Extension scaffold)
                    └─► M6 (Button injection)
                          └─► M7 (Panel UI)
                                └─► M8 (E2E + persistence)
                                      └─► M9 (Error handling)
                                            └─► M10 (Polish)
```

M5 (extension scaffold) can be built in parallel with M2–M4.

---

## 11. Out of Scope (do not build for MVP)

- OAuth or GitHub App installation flows
- Cloud deployment of any component
- Firefox support
- Auto re-indexing when repo changes
- AST-based chunking (use fixed-size chunks)
- Multiple AI provider support
- Extension sync across machines
- Posting anything back to GitHub