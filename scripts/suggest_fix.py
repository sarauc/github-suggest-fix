"""
Milestone 1 — GitHub Action MVP (author-triggered flow)

New UX:
  1. Reviewer leaves an inline review comment describing an issue.
  2. PR author replies to that comment with /suggest-fix.
  3. This script fetches the reviewer's ORIGINAL comment (path, line, body),
     calls Claude, and posts a suggestion block back into the same thread.

The feature now serves the PR author on demand, not the reviewer.
"""

import base64
import os
import sys

import anthropic
import requests

# ---------------------------------------------------------------------------
# Env vars injected by the GitHub Actions workflow
# ---------------------------------------------------------------------------
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
REPLY_COMMENT_ID = int(os.environ["REPLY_COMMENT_ID"])   # the /suggest-fix reply
PARENT_COMMENT_ID = int(os.environ["PARENT_COMMENT_ID"]) # reviewer's root comment
PR_NUMBER = int(os.environ["PR_NUMBER"])
REPO = os.environ["REPO"]

GITHUB_HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

CONTEXT_WINDOW = 20  # lines above and below the commented line


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fetch_parent_comment() -> dict:
    """
    Fetch the reviewer's original (root) comment by ID.
    Returns the full comment object which includes body, path, and line.
    """
    url = f"https://api.github.com/repos/{REPO}/pulls/comments/{PARENT_COMMENT_ID}"
    resp = requests.get(url, headers=GITHUB_HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json()


def fetch_file_context(file_path: str, target_line: int) -> tuple[str, int]:
    """
    Returns (numbered_snippet, offset_of_target_within_snippet).
    offset is 0-indexed relative to the snippet start.
    """
    url = f"https://api.github.com/repos/{REPO}/contents/{file_path}"
    resp = requests.get(url, headers=GITHUB_HEADERS, timeout=15)
    resp.raise_for_status()

    content = base64.b64decode(resp.json()["content"]).decode("utf-8")
    lines = content.splitlines()

    # GitHub line numbers are 1-based
    start = max(0, target_line - CONTEXT_WINDOW - 1)
    end = min(len(lines), target_line + CONTEXT_WINDOW)

    snippet_lines = lines[start:end]
    numbered = "\n".join(
        f"{start + i + 1}: {line}" for i, line in enumerate(snippet_lines)
    )
    offset = target_line - start - 1  # 0-indexed position of target in snippet
    return numbered, offset


def detect_language(file_path: str) -> str:
    ext_map = {
        ".py": "python", ".ts": "typescript", ".tsx": "typescript",
        ".js": "javascript", ".jsx": "javascript", ".go": "go",
        ".rs": "rust", ".java": "java", ".rb": "ruby", ".cs": "csharp",
        ".cpp": "cpp", ".c": "c", ".php": "php", ".swift": "swift",
        ".kt": "kotlin", ".sh": "bash",
    }
    ext = "." + file_path.rsplit(".", 1)[-1] if "." in file_path else ""
    return ext_map.get(ext, "")


def generate_suggestion(review_comment: str, code_context: str, file_path: str, target_line: int) -> str:
    language = detect_language(file_path)
    lang_hint = f" ({language})" if language else ""

    prompt = f"""You are an expert code reviewer assistant helping PR authors understand and act on reviewer feedback.

A reviewer left the following comment on a pull request:
---
{review_comment}
---

File: {file_path}{lang_hint}
Code context (line numbers shown, target is line {target_line}):
```{language}
{code_context}
```

Your response must have three parts in this exact order:

**1. Reviewer's perspective**
In 2-3 sentences, explain what the reviewer is concerned about and *why* it matters — the underlying principle, risk, or convention they are pointing to. Write this for the PR author so they genuinely understand the feedback, not just the surface request.

**2. Suggested fix**
A minimal, correct code change — only alter what is strictly necessary. Use a GitHub suggestion block so the author can apply it in one click. Do NOT include unchanged surrounding lines inside the block.

```suggestion
<replacement line(s) for line {target_line} only>
```

**3. One-line rationale**
A single sentence explaining what the fix does differently and why that resolves the reviewer's concern.

If the comment is too ambiguous to produce a safe fix, skip parts 2 and 3 and explain why in part 1."""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def post_reply(in_reply_to: int, body: str) -> None:
    url = f"https://api.github.com/repos/{REPO}/pulls/{PR_NUMBER}/comments"
    resp = requests.post(
        url,
        headers=GITHUB_HEADERS,
        json={"body": body, "in_reply_to": in_reply_to},
        timeout=15,
    )
    if not resp.ok:
        print(f"GitHub API error {resp.status_code}: {resp.text}", file=sys.stderr)
        resp.raise_for_status()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"Fetching reviewer's comment {PARENT_COMMENT_ID} ...")
    parent = fetch_parent_comment()

    review_comment_body = parent.get("body", "")
    file_path = parent.get("path")
    # `line` is the new-file line; fall back to `original_line` for unchanged lines
    line = parent.get("line") or parent.get("original_line")

    if not file_path or not line:
        print("Skipping: parent comment has no file path or line number (e.g. top-level PR comment).")
        sys.exit(0)

    print(f"  Reviewer comment on {file_path}:{line}")
    print(f"  Reviewer said: {review_comment_body[:120]!r}{'...' if len(review_comment_body) > 120 else ''}")

    code_context, _offset = fetch_file_context(file_path, line)
    print(f"  Fetched ±{CONTEXT_WINDOW} lines of context.")

    suggestion_text = generate_suggestion(review_comment_body, code_context, file_path, line)
    print("  Claude response received.")

    reply_body = (
        "🤖 **AI Suggested Fix** *(auto-generated — please review before applying)*\n\n"
        + suggestion_text
    )
    # Reply to the reviewer's root comment so the suggestion sits in the right thread
    post_reply(PARENT_COMMENT_ID, reply_body)
    print("  Suggestion posted successfully.")


if __name__ == "__main__":
    main()
