"""
Assembles the prompt context sent to Claude for /analyze and /chat.
"""

import os
from typing import List, Optional, Tuple

import config
from services.repo_summary import load_summary
from services.vector_store import query_relevant_chunks

# ── System prompt ─────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert software engineering mentor helping a PR author understand a code review comment.

Your job is NOT to fix the code for the author. Your job is to help them deeply understand:
1. What the reviewer is asking for and WHY it matters
2. Multiple distinct ways they could address the feedback, each with honest tradeoffs

## Output format (always follow this structure)

### What the reviewer means
A plain-English explanation of the reviewer's concern and the underlying engineering principle at stake. 1–3 sentences. No code.

### Ways to address this

For each approach (give 2–4 options):

**Option N: [short name]**
[1–2 sentence description of the approach]
- ✓ Pro: [specific advantage in this codebase/context]
- ✗ Con: [specific disadvantage or tradeoff]

### Which approach fits this codebase
A brief note (1–2 sentences) on which option aligns best with the patterns you can see in the provided context — or acknowledge if you cannot tell from the context given.

## Rules
- Never produce a complete, ready-to-paste code block as your primary output
- You may use short inline code snippets (a few tokens) to illustrate a concept
- If the reviewer's intent is ambiguous, say so and present multiple interpretations
- Reference specific files or patterns from the codebase context when relevant
- Keep your total response under 500 words
"""

# ── Token budget helpers ──────────────────────────────────────────

def _estimate_tokens(text: str) -> int:
    return len(text) // 4


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... [truncated]"


def _truncate_history(history: List[dict], max_tokens: int) -> List[dict]:
    """Keep the first message (original analysis) + as many recent messages as fit."""
    if not history:
        return []

    kept = [history[0]]
    budget = max_tokens - _estimate_tokens(history[0].get("content", ""))

    for msg in reversed(history[1:]):
        tokens = _estimate_tokens(msg.get("content", ""))
        if budget - tokens < 0:
            break
        kept.insert(1, msg)
        budget -= tokens

    return kept


# ── Related PR diff filtering ─────────────────────────────────────

def _filter_related_pr_files(pr_files: List[dict], commented_file_path: str) -> List[dict]:
    """Return PR files in the same directory as the commented file (excluding the file itself)."""
    commented_dir = os.path.dirname(commented_file_path)
    return [
        f for f in pr_files
        if os.path.dirname(f["filename"]) == commented_dir
        and f["filename"] != commented_file_path
    ]


# ── Context builders ──────────────────────────────────────────────

def build_analyze_messages(
    comment_body: str,
    diff_hunk: str,
    file_path: str,
    file_content: str,
    repo: str,
    pr_files: Optional[List[dict]] = None,
    import_deps: Optional[List[Tuple[str, str]]] = None,
) -> List[dict]:
    """Build the messages list for the first-turn /analyze call.

    pr_files: list of {"filename": str, "patch": str} for all PR changed files.
    import_deps: list of (file_path, file_content) for resolved local imports.
    """

    sections = []

    # ── 1. Review comment (primary goal — placed first) ───────────
    sections.append(f"--- REVIEW COMMENT ---\n{comment_body}")

    # ── 2. Diff hunk (pinpoint target — placed second, high attention weight)
    if diff_hunk:
        sections.append(
            f"--- CHANGED LINES (the exact code the reviewer is commenting on) ---\n{diff_hunk}"
        )

    # ── 3. Full file content ──────────────────────────────────────
    if file_content:
        file_truncated = _truncate_to_tokens(file_content, config.MAX_FILE_TOKENS)
        sections.append(f"--- FULL FILE: {file_path} ---\n{file_truncated}")

    # ── 4. Related PR diff (same-directory files) ─────────────────
    if pr_files and file_path:
        related = _filter_related_pr_files(pr_files, file_path)
        if related:
            parts = []
            budget = 2000  # token cap for entire section
            for f in related:
                patch_truncated = _truncate_to_tokens(f["patch"], min(budget, 600))
                token_cost = _estimate_tokens(patch_truncated)
                if budget - token_cost < 0:
                    break
                parts.append(f"// {f['filename']}\n{patch_truncated}")
                budget -= token_cost
            if parts:
                sections.append(
                    "--- RELATED PR CHANGES (other files changed in this PR, same directory) ---\n"
                    + "\n\n".join(parts)
                )

    # ── 5. Shallow import dependencies ────────────────────────────
    if import_deps:
        parts = []
        for dep_path, dep_content in import_deps:
            dep_truncated = _truncate_to_tokens(dep_content, 400)
            parts.append(f"// {dep_path}\n{dep_truncated}")
        if parts:
            sections.append(
                "--- IMPORTED DEPENDENCIES (local files imported by the commented file) ---\n"
                + "\n\n".join(parts)
            )

    # ── 6. RAG chunks (query now includes diff hunk tokens) ───────
    rag_query = f"{comment_body} {diff_hunk[:300]} {file_path}"
    rag_chunks = query_relevant_chunks(repo, rag_query, top_k=config.RAG_TOP_K)
    if rag_chunks:
        parts = []
        for chunk in rag_chunks:
            parts.append(
                f"// {chunk.file_path} (lines {chunk.start_line}–{chunk.end_line})\n{chunk.text}"
            )
        sections.append("--- RELATED CODEBASE CONTEXT ---\n" + "\n\n".join(parts))

    # ── 7. Codebase overview (AI-generated summary from index time)
    summary = load_summary(repo)
    if summary:
        summary_truncated = _truncate_to_tokens(summary, 300)
        sections.append(f"--- CODEBASE OVERVIEW ---\n{summary_truncated}")

    user_message = "\n\n".join(sections)
    return [{"role": "user", "content": user_message}]


def build_chat_messages(
    conversation_history: List[dict],
    user_message: str,
    comment_body: str = "",
    diff_hunk: str = "",
    file_path: str = "",
    file_content: str = "",
) -> List[dict]:
    """Build the messages list for a follow-up /chat turn.

    When comment_body / diff_hunk / file_content are provided, a compact
    pinned context block is prepended so Claude retains code awareness
    across all follow-up turns.
    """
    messages = []

    # Pinned context block — re-injected on every chat turn
    if diff_hunk or file_path:
        file_snippet = _truncate_to_tokens(file_content, 800) if file_content else ""
        pinned_parts = ["[Original context — reference this throughout the conversation]"]
        if comment_body:
            pinned_parts.append(f"Review comment: {comment_body}")
        if file_path:
            pinned_parts.append(f"File: {file_path}")
        if diff_hunk:
            pinned_parts.append(f"Changed lines:\n{diff_hunk}")
        if file_snippet:
            pinned_parts.append(f"File excerpt:\n{file_snippet}")
        pinned_parts.append("---")
        messages.append({"role": "user", "content": "\n".join(pinned_parts)})

    history = _truncate_history(conversation_history, max_tokens=1500)
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})
    return messages
