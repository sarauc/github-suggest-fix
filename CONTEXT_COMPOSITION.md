# Context Composition — How We Build the Claude Prompt

This document describes exactly what context Claude receives, in what order, how each piece is sized, and how RAG retrieval works.

---

## 1. System prompt (static, every call)

**Source:** `context_assembler.py` — `SYSTEM_PROMPT` constant
**Sent as:** the `system` parameter on every Anthropic API call (both `/analyze` and `/chat`)
**Size:** ~350 tokens (fixed)

Content:
- Role definition: "expert software engineering mentor"
- Goal constraint: explain reviewer intent and tradeoffs, never auto-fix
- Required output structure: three sections (What the reviewer means / Ways to address this / Which approach fits)
- Hard rules: no full code blocks, keep under 500 words, cite codebase patterns when visible

This never changes between calls. It is the only context that `/chat` turns share with `/analyze`.

---

## 2. First-turn user message (`/analyze`)

**Built by:** `build_analyze_messages()` in `context_assembler.py`
**Sent as:** a single `{"role": "user", "content": "..."}` message

The message is assembled by concatenating four sections in this order:

```
--- REVIEW COMMENT ---
<comment_body>

--- FILE: <file_path> ---
<file_content, truncated to MAX_FILE_TOKENS>

--- DIFF HUNK ---
<diff_hunk>

--- RELATED CODEBASE CONTEXT ---   ← only present if RAG returns results
// path/to/file.py (lines N–M)
<chunk text>

// path/to/other.py (lines N–M)
<chunk text>
```

### Token budget per section

| Section | Budget | Config key | Notes |
|---|---|---|---|
| Review comment | unbounded | — | typically < 200 tokens |
| File content | **8,000 tokens** | `MAX_FILE_TOKENS` | hard-truncated with `... [truncated]` marker |
| Diff hunk | unbounded | — | GitHub returns ≤ ~100 lines; usually < 500 tokens |
| RAG chunks | sum of top-K chunks | `RAG_TOP_K = 5` | each chunk ≤ 400 tokens; total ≤ ~2,000 tokens |

**Effective ordering / attention weight:**

The sections appear in the order listed above. LLMs give more weight to content that appears earlier and content that appears later (primacy and recency). The current ordering places the **full file in the middle** and the **diff hunk near the end** — which means the specific changed lines are de-prioritised relative to the full file. This is a known issue documented in `ISSUE_context_quality.md`.

---

## 3. Follow-up turns (`/chat`)

**Built by:** `build_chat_messages()` in `context_assembler.py`
**Sent as:** a sequence of `{"role": "...", "content": "..."}` messages

```
[history[0]]            ← first assistant message (Claude's original analysis)
[history[1..n-1]]       ← recent history, up to 2,000-token budget
[{"role": "user", "content": user_message}]   ← new question
```

### History truncation logic (`_truncate_history`)

1. **Always keep** `history[0]` — the first assistant message (the analysis).
2. Start a budget of **2,000 tokens** minus the token cost of `history[0]`.
3. Walk `history[1:]` in **reverse** (newest first), adding each message while budget allows.
4. Stop at the first message that would exceed the budget.

**Critical gap:** The original first-turn *user* message (which contained the diff hunk, file content, and review comment) is **not stored** in the localStorage history — only assistant and user-visible messages are kept. As a result, the code context is completely absent from all chat turns. This is the root cause of Bug 2 in `ISSUE_context_quality.md`.

---

## 4. RAG — retrieval strategy

### Index structure

The repo is indexed at first use. Each source file is split into overlapping fixed-size chunks:

| Parameter | Value | Config key |
|---|---|---|
| Target chunk size | **400 tokens** (~1,600 chars) | `CHUNK_SIZE_TOKENS` |
| Overlap between chunks | **50 tokens** (~200 chars) | `CHUNK_OVERLAP_TOKENS` |
| Max file size | 200 KB | `MAX_FILE_SIZE_BYTES` |

Chunking is **line-boundary aware**: the chunker accumulates lines until the token budget is reached, then emits a chunk and keeps the last `CHUNK_OVERLAP_TOKENS` worth of lines as the start of the next chunk. Token counts use the 1 token ≈ 4 chars approximation.

Chunks are serialised to disk as JSON at `~/.gh-ai-assistant/indexes/<owner>__<repo>.json`.

Files are excluded if they match any of:
- Binary/asset extensions (images, fonts, zips, compiled objects, `.lock`, `.min.js`, etc.)
- Path patterns: `node_modules/`, `.git/`, `dist/`, `build/`, `__pycache__/`, `.venv/`, etc.

### Retrieval algorithm

**Algorithm:** BM25-Okapi (`rank_bm25` library)
**No embeddings** — keyword-based only (sentence-transformers/ChromaDB were dropped due to Python 3.8/macOS incompatibility)

**Query construction** (in `build_analyze_messages`):
```python
rag_query = f"{comment_body} {file_path}"
```
The query is the review comment text concatenated with the file path of the commented file. The file path contributes tokens like the filename and directory names, which loosely biases retrieval toward the same file or related files.

**Tokenisation** (in `vector_store.py`):
```python
def _tokenize(text: str) -> List[str]:
    return [t for t in re.split(r"[^a-zA-Z0-9]+", text.lower()) if t]
```
Splits on any non-alphanumeric character (spaces, underscores, dots, dashes) and lowercases. This means `_build_adjacency` → `["build", "adjacency"]` and `graph_utils.py` → `["graph", "utils", "py"]`.

**Scoring:**
1. At query time, all chunks are loaded from disk into memory.
2. A fresh `BM25Okapi` index is built in-memory from all chunk texts.
3. BM25 scores every chunk against the query tokens.
4. Chunks are ranked by score (descending).
5. The top `RAG_TOP_K = 5` chunks with score > 0 are returned. Chunks scoring exactly 0 (no query token appears in the chunk at all) are filtered out.

**Result format:**
```
// path/to/file.py (lines N–M)
<chunk text>
```

### Known weaknesses of the current RAG strategy

| Weakness | Description |
|---|---|
| **Query doesn't use diff hunk tokens** | The query is `comment_body + file_path`. Tokens from the actual changed lines (the diff hunk) are not included, so BM25 matches on what the reviewer *said*, not what the code *contains*. |
| **BM25 is term-frequency only** | No semantic understanding. A comment saying "this is too slow" will not retrieve chunks about `O(n²)` loops unless those words appear literally. |
| **No file-proximity bias** | All chunks across the entire repo compete equally. A chunk in an unrelated file with high term overlap beats a chunk in the exact commented file with lower overlap. |
| **Index is repo-HEAD, not PR branch** | The index is built from the default branch HEAD, not the PR branch. If the PR adds new functions, they are not indexed. |
| **In-memory BM25 rebuilt on every query** | No caching. For repos with 5,000+ chunks this is still fast (< 100 ms), but it scales linearly. |

---

## 5. Full context assembly summary

```
SYSTEM PROMPT (~350 tokens, static)
│
├── /analyze (first turn)
│   └── user message:
│       ├── [1] Review comment        (unbounded, ~< 200 tok)
│       ├── [2] Full file content     (capped at 8,000 tok)   ← largest block
│       ├── [3] Diff hunk             (unbounded, ~< 500 tok) ← pinpoint signal, placed late
│       └── [4] RAG chunks × 5       (≤ ~2,000 tok total)
│
└── /chat (follow-up turns)
    └── message list:
        ├── [1] First assistant reply (kept always)
        ├── [2..n] Recent history     (2,000-tok budget, newest-first fill)
        └── [n+1] New user message
        ← NO diff hunk, NO file content, NO review comment re-injected
```

Total maximum context sent on a first `/analyze` call (excluding system prompt):
`~200 + 8,000 + 500 + 2,000 = ~10,700 tokens`

The model used (`claude-sonnet-4-5`) has a 200K token context window, so we are well within limits. The bottleneck is retrieval quality and prompt ordering, not context length.
