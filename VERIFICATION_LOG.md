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
**Status:** PENDING

---

## Milestone 5 — Chrome Extension Scaffold + Settings
**Status:** PENDING

---

## Milestone 6 — Content Script: Button Injection
**Status:** PENDING

---

## Milestone 7 — Panel UI (Option B)
**Status:** PENDING

---

## Milestone 8 — End-to-End Flow + Persistence
**Status:** PENDING

---

## Milestone 9 — Error Handling + Corner Cases
**Status:** PENDING

---

## Milestone 10 — Polish + README
**Status:** PENDING
