# Verification Log

Tracks milestone completion status, verification steps, and results.

---

## Milestone 1 — Backend Scaffold
**Status:** PASSED
**Date:** 2026-04-19

### Steps
```bash
cd backend
bash start.sh
curl http://localhost:8765/health
```

### Result
```json
{"status":"ok","version":"0.1.0"}
```

### Notes
- Encountered Python version check failure — `start.sh` originally required 3.11+, fixed to 3.8+
- Encountered pip 19.2.3 TOML parse error — fixed by adding `pip install --upgrade pip` before deps install
- `.gitignore` was missing — added to exclude `backend/.venv/` and other generated files

---

## Milestone 2 — GitHub API Client
**Status:** PASSED
**Date:** 2026-04-19

### Steps
```bash
cd backend
source .venv/bin/activate
python test_m2_github_client.py \
  --token ghp_... \
  --repo sarauc/code-review-graph \
  --pr 1 \
  --comment-id 3107811549
```

### Result
```
=== M2 GitHub Client Test ===
repo=sarauc/code-review-graph  PR=#1  comment=3107811549

1. get_pr_comment()
  [PASS] comment body: Can you explain what the function is for, and how is it used in the change?
  [PASS] diff_hunk: ...
  [PASS] file_path: code_review_graph/communities.py
  [PASS] commit_id: 97bb8d0d9485

2. get_pr_head_ref()
  [PASS] head SHA: 97bb8d0d9485

3. get_file_content()
  [PASS] file lines: 700
  [PASS] first line: """Community/cluster detection for the code knowledge graph.

4. get_repo_tree()
  [PASS] total files: 185
  [PASS] found commented file in tree: code_review_graph/communities.py

5. get_file_blob()
  [PASS] blob lines: 700

=== All checks complete ===
```

### Notes
- Fixed `int | None` type union syntax (Python 3.10+ only) → replaced with `Optional[int]` from `typing` for 3.8 compatibility

---

## Milestone 3 — Repo Indexer + Vector Store
**Status:** PASSED
**Date:** 2026-04-19

### Steps
```bash
cd backend
# Start server, then run integration test against real repo:
python test_m3_indexer.py \
  --token ghp_... \
  --repo  owner/repo \
  --query "your search term"
```

### Result
```
=== M3 Indexer + Vector Store Test ===
repo=sarauc/code-review-graph  query="community detection"

1. POST /index
  [PASS] triggered: Indexing started

2. GET /index/status (polling...)
     status=indexing  progress=0%
     status=indexing  progress=13%
     status=indexing  progress=42%
     status=indexing  progress=72%
     status=indexing  progress=97%
     status=indexed  progress=0%
  [PASS] indexed: files=237  chunks=1595

3. Query vector store
  [PASS] chunks returned: 3

  Chunk 1: code_review_graph/eval/benchmarks/build_performance.py (lines 1–55)
  Chunk 2: code_review_graph/eval/benchmarks/build_performance.py (lines 52–60)
  Chunk 3: code_review_graph/postprocessing.py (lines 105–134)

=== All checks complete ===
```

### Notes
- ChromaDB dropped — requires sqlite3 >= 3.35.0, not available on macOS Python 3.8
- sentence-transformers dropped — bus error on Python 3.8/macOS
- Replaced with rank_bm25 + numpy (pure Python, zero system deps, sufficient for MVP)
- Tokenizer splits on all non-alphanumeric chars including underscores so "stream_lines" matches "stream"
- `int | None` syntax incompatible with Python 3.8 — use `Optional[int]` from `typing` throughout

---

## Milestone 4 — Claude Integration + Prompt
**Status:** PASSED
**Date:** 2026-04-20

### Steps
```bash
# Terminal 1
cd backend && bash start.sh

# Terminal 2
cd backend && source .venv/bin/activate
python test_m4_claude.py \
  --anthropic-key sk-ant-... \
  --github-token  ghp_... \
  --repo  sarauc/code-review-graph \
  --pr    1 \
  --comment-id 3107811549
```

### Result
```
=== M4 Claude Integration Test ===
repo=sarauc/code-review-graph  PR=#1  comment=3107811549

Fetching comment data from GitHub...
  comment: Can you explain what the function is for, and how is it used...
  file:    code_review_graph/communities.py (700 lines)

1. POST /analyze (streaming...)
  [PASS] streamed response: 2858 chars
  [PASS] contains reviewer interpretation
  [PASS] contains multiple options/approaches

2. POST /chat (follow-up, streaming...)
  [PASS] chat follow-up streamed: 2710 chars

3. Error handling — invalid API key
  [PASS] structured error returned: code=invalid_key

=== All M4 checks complete ===
```

### Notes
- Prompt structure (interpretation → options → tradeoffs) working correctly
- SSE streaming working end-to-end
- Error codes mapped correctly (invalid_key, rate_limit, etc.)

---

## Milestone 5 — Chrome Extension Scaffold + Settings
**Status:** PASSED
**Date:** 2026-04-20

### Steps
1. Go to `chrome://extensions`, enable Developer mode
2. Click Load unpacked → select `extension/` folder
3. Click extension icon → popup opens
4. Enter Anthropic key + GitHub PAT → Save Settings
5. Right-click popup → Inspect → Application → Extension Storage → Sync
6. Run `chrome.storage.sync.get(null, console.log)` in Console

### Result
- All 3 values saved in sync storage: `anthropicKey`, `githubToken`, `backendUrl`
- Backend status showed "offline" initially — expected due to 30s ping interval
- Two `GET /health 200 OK` entries visible in server log confirming background.js is pinging correctly

### Notes
- "Backend offline" on first popup open is expected — background service worker pings every 30s; reopening after 30s shows "✓ Backend running"
- Placeholder content.js and content.css stubs added to satisfy manifest (filled in M6)

---

## Milestone 6 — Content Script: Button Injection
**Status:** PASSED
**Date:** 2026-04-20

### Steps
1. Reload extension at `chrome://extensions`
2. Navigate to a GitHub PR where you are the author
3. Verify one `✦ Get AI Help` button appears per inline and overall review comment
4. Stop backend → button turns grey with tooltip "Backend offline — run: bash start.sh"
5. Start backend → button becomes active and clickable

### Result
- One button per comment (inline and overall) ✓
- Button active when backend running ✓
- Button grey + unclickable when backend offline ✓
- Tooltip visible on hover when offline ✓

### Notes
- Initial attempt used both `.review-comment` and `.js-comment` selectors — caused duplicate buttons; fixed by targeting `.timeline-comment-actions` directly
- Comment ID extraction from DOM `id` attributes was unreliable; fixed to read from delete form action URL (`/review_comment/12345`)
- `btn.disabled = true` prevents Chrome from showing `title` tooltips; fixed by using `aria-disabled` + CSS class instead
- MutationObserver debounced at 300ms to prevent rapid-fire re-injection

---

## Milestone 7 — Panel UI (Option B)
**Status:** PASSED
**Date:** 2026-04-20

### Steps
1. Reload extension, navigate to a GitHub PR where you are the author
2. Click `✦ Get AI Help` on any review comment
3. Verify panel slides in from the right with dark purple styling
4. Verify streaming response renders with markdown (bold, italic, inline code, lists)
5. Verify follow-up input bar appears after analysis completes
6. Verify closing the panel and reopening restores the prior conversation

### Result
- Panel slides in/out with animation ✓
- Option B styling: dark purple/black, gradient header, AI orb ✓
- Token streaming renders in real time ✓
- Markdown (headers, bold, italic, code, lists, ✓/✗ items) renders correctly ✓
- Follow-up input visible after first response ✓
- "Continue conversation" banner shown on re-open ✓
- "Start fresh" button clears history and re-analyzes ✓

### Notes
- Initial analysis sent empty `diff_hunk`, `file_path`, `file_content` — context enrichment deferred to M8
- Model asked user to clarify which function was changed — expected for M7, addressed in M8

---

## Milestone 8 — End-to-End Flow + Persistence
**Status:** PASSED
**Date:** 2026-04-20

### Steps
1. Clear storage: `rm -rf ~/.gh-ai-assistant/`
2. Clear localStorage in browser console: `Object.keys(localStorage).filter(k => k.startsWith("gh-ai:")).forEach(k => localStorage.removeItem(k))`
3. Reload extension + refresh PR page
4. Click `✦ Get AI Help` — verify indexing progress shown, then analysis streams
5. Close panel, reopen same comment — verify conversation restored
6. Click "Start fresh" — verify re-analysis triggered
7. Send a follow-up message — verify chat works

### Result
- First click triggers indexing; progress % shown in panel ✓
- Analysis streams after indexing completes ✓
- Conversation persists across panel close/open ✓
- "Continue conversation" banner shown on restore ✓
- Follow-up chat working ✓

### Notes
- Backend returned `422 Unprocessable Entity` on first test — old backend still running with required context fields; fixed by restarting backend to load updated optional-field `AnalyzeRequest`
- Context fields (`diff_hunk`, `file_path`, `file_content`) now auto-fetched by backend via `_enrich_context`
- Two observed post-M8 issues documented in `ISSUE_context_quality.md`: (1) model cited wrong function, (2) follow-up chat lost all code context — addressed in M8.5

---

## Milestone 8.5 — Context Quality
**Status:** PASSED
**Date:** 2026-04-21

### Changes shipped
- Prompt reordered: diff hunk now appears before full file content (higher attention weight)
- RAG query enriched with first 300 chars of diff hunk (better chunk relevance)
- Related PR diff (same-directory files) included with 2,000-token cap
- Shallow import tracing: up to 3 local dependencies fetched and included
- AI-generated codebase summary generated at index time via Claude; injected as `CODEBASE OVERVIEW` section
- Chat context pinned: `diff_hunk`, `file_path`, `file_content` re-fetched and prepended on every `/chat` turn
- `anthropic_key` forwarded to `/index` so summary generation works on first index

### Notes
- Fixed `Uncaught TypeError: Cannot read properties of null (reading 'classList')` — `closePanel()` called by nav observer before panel was created; fixed with null guard
- Fixed duplicate analysis blocks — GitHub SPA navigation caused `init()` to run multiple times, registering multiple `gh-ai:open` listeners; fixed with `panelListenerActive` flag

---

## Milestone 9 — Error Handling + Corner Cases
**Status:** PASSED
**Date:** 2026-04-21

### Corner cases implemented

| CC | Description | Implementation |
|---|---|---|
| 7.1 | Non-PR-author | Buttons not injected (M6) |
| 7.2 | Repo not indexed | Indexing state shown, polls `/index/status` (M8) |
| 7.3 | Large repo (>5 min) | `pollUntilIndexed` 5-min deadline; falls back to no-RAG analysis (M8) |
| 7.4 | Missing GitHub token | Specific panel error with instruction to open settings |
| 7.5 | Missing Anthropic key | Specific panel error with instruction to open settings |
| 7.6 | Invalid/rate-limited key | `claude_client.py` maps errors to `invalid_key` / `rate_limit` messages; GitHub 401 now surfaces as SSE error event instead of silent fallback |
| 7.7 | Backend offline | Button disabled with tooltip (M6) |
| 7.9 | Long conversation | `_truncate_history`: always keeps first assistant message + fills 1,500-token budget newest-first |
| 7.10 | Large PR diff | Only comment's diff hunk used; same-dir PR files capped at 2,000 tokens (M8.5) |
| 7.11 | Outdated comment | `get_pr_comment` + `get_pr_head_ref` run in parallel; `commit_id != head_sha` → annotates diff hunk section in prompt |
| 7.12 | Navigation mid-analysis | `abortCurrentStream()` called by nav observer (M8) |
| 7.13 | Multiple comment clicks | Single panel; `abortCurrentStream()` on each `openPanel` call (M7) |

---

## Milestone 10 — Polish + README
**Status:** PENDING
