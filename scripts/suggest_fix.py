"""
Milestone 1 — GitHub Action MVP
Reads a pull_request_review_comment event, fetches code context,
calls Claude, and posts a GitHub suggestion block as a reply.
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
COMMENT_BODY = os.environ["COMMENT_BODY"]
COMMENT_ID = int(os.environ["COMMENT_ID"])
FILE_PATH = os.environ["FILE_PATH"]
LINE = int(os.environ["LINE"])
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


def generate_suggestion(comment: str, code_context: str, file_path: str, target_line: int) -> str:
    language = detect_language(file_path)
    lang_hint = f" ({language})" if language else ""

    prompt = f"""You are an expert code reviewer assistant helping developers fix issues identified in pull request reviews.

A reviewer left the following comment on a pull request:
---
{comment}
---

File: {file_path}{lang_hint}
Code context (line numbers shown, target is line {target_line}):
```{language}
{code_context}
```

Instructions:
- Understand what the reviewer is asking to fix.
- Generate a minimal, correct fix — only change what is strictly necessary.
- Output ONLY a suggestion block containing the replacement line(s) for line {target_line}.
- Do NOT include unchanged surrounding lines in the suggestion block.
- After the suggestion block add exactly one sentence explaining what changed.
- If the comment is ambiguous or you cannot determine a safe fix, say so explicitly instead of guessing.

Respond in this exact format:
```suggestion
<replacement line(s) here>
```
<one-sentence explanation>"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def post_reply(comment_id: int, body: str) -> None:
    url = f"https://api.github.com/repos/{REPO}/pulls/{PR_NUMBER}/comments"
    resp = requests.post(
        url,
        headers=GITHUB_HEADERS,
        json={"body": body, "in_reply_to": comment_id},
        timeout=15,
    )
    if not resp.ok:
        print(f"GitHub API error {resp.status_code}: {resp.text}", file=sys.stderr)
        resp.raise_for_status()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"Processing comment {COMMENT_ID} on {REPO} PR#{PR_NUMBER}")
    print(f"  File: {FILE_PATH}, line: {LINE}")

    code_context, offset = fetch_file_context(FILE_PATH, LINE)
    print(f"  Fetched {CONTEXT_WINDOW*2} lines of context (target offset: {offset})")

    suggestion_text = generate_suggestion(COMMENT_BODY, code_context, FILE_PATH, LINE)
    print("  Claude response received.")

    reply_body = (
        "🤖 **AI Suggested Fix** *(auto-generated — please review before applying)*\n\n"
        + suggestion_text
    )
    post_reply(COMMENT_ID, reply_body)
    print("  Reply posted successfully.")


if __name__ == "__main__":
    main()
