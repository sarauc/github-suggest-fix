# Issue: AI Analysis Missing Diff and File Context

**Severity:** High — core product value is broken without this context
**Affects:** M7 panel (current), fixed in M8

---

## What is wrong

The AI panel opens and calls `/analyze`, but passes **empty strings** for the three most important context fields:

```js
// content.js — streamAnalyze()
diff_hunk:    "",   // ← empty
file_path:    "",   // ← empty
file_content: "",   // ← empty
```

These were intentionally left as stubs in M7 (marked "enriched in M8") but the panel is already live, so the model is flying blind. It has no idea:
- **Which file** the comment is on
- **Which lines changed** (the diff hunk)
- **What the full file looks like** (for broader context)

This explains the observed behaviour: the model asked the user to manually tell it which function was changed — information that should have been retrieved automatically.

---

## Why it happens

The milestone split was:
- **M7** — build the panel UI and streaming (done)
- **M8** — wire up real context: settings → index check → GitHub API fetch → analyze

The `diff_hunk`, `file_path`, and `file_content` fields were deferred to M8. But M7 exposed the panel to the user before M8 was built, making the missing context observable immediately.

---

## Where the fix lives

The fix belongs entirely in the **backend** (`routes/analyze.py`).

The content script already passes `comment_id`, `repo`, `pr_number`, and `github_token`. That is enough for the backend to self-fetch all missing context using the existing `github_client.py` functions that were built in M2.

The content script does **not** need to change.

---

## Fix plan

### Step 1 — Auto-fetch context in `routes/analyze.py`

When `file_content` is empty (i.e. not supplied by the caller), the `/analyze` route should fetch the missing fields before assembling the prompt:

```
comment_id + github_token
        │
        ▼
get_pr_comment()          → diff_hunk, file_path, commit_id
        │
        ▼
get_file_content()        → file_content  (full file at that commit)
        │
        ▼
context_assembler         → prompt with full context
        │
        ▼
Claude API                → streamed analysis
```

Concretely, add a prefetch step inside the `analyze()` route handler:

```python
# routes/analyze.py — inside analyze()

if not body.file_content:
    comment_data = await get_pr_comment(body.repo, int(body.comment_id), body.github_token)
    file_content = await get_file_content(
        body.repo, comment_data.file_path, comment_data.commit_id, body.github_token
    )
    # Overwrite the empty fields from the request
    body = body.copy(update={
        "diff_hunk":    comment_data.diff_hunk,
        "file_path":    comment_data.file_path,
        "file_content": file_content,
    })
```

### Step 2 — Remove the empty-string stubs in `content.js`

Once the backend self-fetches, the content script can simply omit these fields (or keep sending empty strings — both work). For clarity, remove the stub comments:

```js
// content.js — streamAnalyze() — remove these three lines:
diff_hunk:    "",   // enriched in M8
file_path:    "",   // enriched in M8
file_content: "",   // enriched in M8
```

### Step 3 — Update `AnalyzeRequest` model to make fields optional

In `backend/routes/analyze.py`, the Pydantic model currently requires all fields. Make the context fields optional with empty defaults so the route can accept the leaner payload from the content script:

```python
class AnalyzeRequest(BaseModel):
    repo:          str
    pr_number:     int
    comment_id:    str
    comment_body:  str
    github_token:  str
    anthropic_key: str
    diff_hunk:     str = ""     # fetched by backend if empty
    file_path:     str = ""     # fetched by backend if empty
    file_content:  str = ""     # fetched by backend if empty
```

---

## Files to change

| File | Change |
|---|---|
| `backend/routes/analyze.py` | Add GitHub API prefetch when `file_content` is empty; make context fields optional in `AnalyzeRequest` |
| `extension/content.js` | Remove empty-string stubs from `streamAnalyze()` |

`backend/services/github_client.py`, `backend/services/context_assembler.py`, and all other files are **unchanged** — they already handle the data correctly once it's populated.

---

## Expected result after fix

When the user clicks "Get AI Help" on a review comment, the model will have:

| Context | Source |
|---|---|
| Review comment text | DOM (already working) |
| Diff hunk (changed lines ± context) | GitHub API → `get_pr_comment()` |
| Full file content | GitHub API → `get_file_content()` |
| Related codebase chunks | BM25 index (already working) |

The model should be able to reference the specific function, the exact lines changed, and patterns from the broader codebase — without asking the user for information it should already have.
