# Issue: AI Cites Wrong Function + Loses Context in Follow-up Chat

**Severity:** High — core product value is degraded in both first-turn and multi-turn usage
**Observed after:** M8 (context enrichment live)
**Status:** Open — fix planned for M9

---

## Observed behaviour

### Bug 1 — Wrong function cited

The reviewer's comment was attached to `_build_adjacency` (lines 199–206). The model opened its response by analyzing `_is_test_community` — a different function entirely.

### Bug 2 — Lost context in follow-up chat

In the same session, the user sent a follow-up question. The model responded:

> "I don't actually know which function the reviewer is referring to … could you clarify which function …"

The model forgot everything from the first turn: the review comment, the diff hunk, and the file content.

---

## Root cause analysis

### Bug 1 — Wrong function cited

**What the prompt looks like today (`build_analyze_messages`):**

```
--- REVIEW COMMENT ---
<comment text>

--- FILE: path/to/file.py ---
<entire file, up to MAX_FILE_TOKENS characters>

--- DIFF HUNK ---
<diff hunk from get_pr_comment()>

--- RELATED CODEBASE CONTEXT ---
<BM25 RAG chunks>
```

Three problems compound here:

1. **File content overshadows the diff hunk.** The full file (~700 lines) is presented *before* the diff hunk. Claude's attention naturally anchors on early, large context blocks. The specific changed lines (the diff hunk) appear late and may be de-prioritised.

2. **The diff hunk has no explicit pointer to the commented lines.** `get_pr_comment()` returns the hunk as raw unified-diff text. There is no annotation saying "the reviewer's comment is attached to line 202" or "focus on the `+` lines". The model has to infer which lines triggered the comment.

3. **RAG may surface the wrong function.** The BM25 query is `"{comment_body} {file_path}"`. If the comment uses words that appear more frequently in `_is_test_community` than in `_build_adjacency`, the top-k chunks returned will be from the wrong function — and Claude will cite what it sees prominently in the RAG results.

**Consequence:** The model reads a 700-line file, a raw diff, and RAG chunks that may include an unrelated function, and picks the wrong one.

---

### Bug 2 — Lost context in follow-up chat

**What `build_chat_messages` sends to Claude on follow-up turns:**

```python
def build_chat_messages(conversation_history, user_message):
    truncated_history = _truncate_history(conversation_history, max_tokens=2000)
    return truncated_history + [{"role": "user", "content": user_message}]
```

The `conversation_history` stored in localStorage contains only the **rendered assistant response** and the **user's follow-up text** — not the original code context. The original `diff_hunk`, `file_content`, `file_path`, and `comment_body` that were in the first-turn user message are **never stored in history and never re-sent**.

`_truncate_history` keeps `history[0]` (the first assistant message — the analysis) plus recent turns. But `history[0]` is the *assistant's reply*, not the *user's first message with all the code*. The code context is silently dropped.

**Consequence:** By the second turn, Claude has its own previous analysis (words only) but zero access to the actual code. It cannot answer specific questions about lines or functions because it no longer has them.

---

## Data flow diagrams

### First turn (`/analyze`) — current

```
comment_id → get_pr_comment() → diff_hunk, file_path, commit_id
                               → get_file_content() → file_content
                               ↓
build_analyze_messages()
  user_message = [review comment] + [full file] + [diff hunk] + [RAG chunks]
                                                                        ↓
                                                                   Claude API
```

**Problem:** Ordering puts the pinpoint signal (diff hunk) after a wall of file content.

### Follow-up turn (`/chat`) — current

```
localStorage history = [
  { role: "assistant", content: "<Claude's first analysis>" },
  { role: "user",      content: "<follow-up question>" },
]

build_chat_messages() → history + new user message → Claude API
```

**Problem:** Original code context (diff hunk, file content) is absent from all chat turns.

---

## Fix plan

### Fix 1 — Reorder and annotate the prompt

In `build_analyze_messages()`, restructure the user message so the **diff hunk comes first** (highest attention weight) and is explicitly annotated with the comment target:

```
--- REVIEW COMMENT ---
<comment_body>

--- CHANGED LINES (diff hunk — this is what the reviewer is commenting on) ---
<diff_hunk>

--- FULL FILE: <file_path> ---
<file_content, truncated>

--- RELATED CODEBASE CONTEXT ---
<RAG chunks>
```

Additionally, improve the RAG query to be more specific:

```python
# Use diff hunk tokens as primary signal, not just the comment + file path
rag_query = f"{comment_body} {diff_hunk[:300]} {file_path}"
```

This ensures BM25 retrieves chunks that share vocabulary with the *actual changed lines*, not just the comment text.

---

### Fix 2 — Pin code context into every chat turn

The `/chat` endpoint must receive and re-inject the original code context on every follow-up turn. Two changes are needed:

**A. Extension (`content.js`) — store context block in localStorage**

When the first analysis completes, save a `context_block` alongside the conversation history:

```js
const contextBlock = {
  comment_body: commentBody,
  diff_hunk:    "",  // returned by backend in analysis response headers, or re-fetched
  file_path:    "",  // same
};
localStorage.setItem(storageKey + ":ctx", JSON.stringify(contextBlock));
```

A simpler alternative: have the content script save whatever it *does* know at click time (`comment_body`, `repo`, `comment_id`) and let the backend re-fetch the rest on chat turns.

**B. Backend (`routes/analyze.py` + `context_assembler.py`) — accept and inject context on `/chat`**

Extend `ChatRequest` to accept the original context fields:

```python
class ChatRequest(BaseModel):
    repo:         str
    comment_id:   str
    user_message: str
    conversation_history: List[Message]
    anthropic_key: str
    # Original context — re-injected as a pinned block
    comment_body: str = ""
    diff_hunk:    str = ""
    file_path:    str = ""
    file_content: str = ""
```

In `build_chat_messages()`, prepend a compact pinned context block to the message list so Claude always has the code in view:

```python
def build_chat_messages(conversation_history, user_message,
                        comment_body="", diff_hunk="", file_path="", file_content=""):
    pinned = ""
    if diff_hunk or file_path:
        file_snippet = _truncate_to_tokens(file_content, max_tokens=800)
        pinned = f"""[CONTEXT — do not forget this across turns]
Review comment: {comment_body}
File: {file_path}
Changed lines:
{diff_hunk}
File snippet:
{file_snippet}
---
"""
    history = _truncate_history(conversation_history, max_tokens=1500)
    base = [{"role": "user", "content": pinned}] if pinned else []
    return base + history + [{"role": "user", "content": user_message}]
```

> Note: Injecting as a synthetic first user message is one approach. An alternative is to prepend it to the system prompt as a "CONTEXT" section. Either works; a synthetic user turn is simpler and keeps the system prompt static.

---

## Files to change

| File | Change |
|---|---|
| `backend/services/context_assembler.py` | Reorder `build_analyze_messages()` to put diff hunk first; improve RAG query; add context params to `build_chat_messages()` |
| `backend/routes/analyze.py` | Extend `ChatRequest` with optional context fields; pass them to `build_chat_messages()` |
| `extension/content.js` | On first analysis, save `comment_body` + `comment_id` to localStorage; send them with every `/chat` request |

`backend/services/github_client.py` and `backend/services/vector_store.py` are **unchanged**.

---

## Expected result after fix

| Scenario | Before fix | After fix |
|---|---|---|
| First turn — which function is cited | Wrong function (highest BM25 match) | Correct function (diff hunk is the primary signal) |
| Follow-up turn — code context | Completely lost | Pinned context block re-injected on every turn |
| Follow-up turn — "which function?" | Model asks user to clarify | Model references exact lines from the diff |
