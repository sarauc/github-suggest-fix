"""
Assembles the prompt context sent to Claude for /analyze and /chat.
"""

from typing import List, Optional

import config
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

    # Always keep the first assistant message (original analysis)
    kept = [history[0]]
    budget = max_tokens - _estimate_tokens(history[0].get("content", ""))

    # Add recent messages in reverse until budget runs out
    for msg in reversed(history[1:]):
        tokens = _estimate_tokens(msg.get("content", ""))
        if budget - tokens < 0:
            break
        kept.insert(1, msg)
        budget -= tokens

    return kept


# ── Context builders ──────────────────────────────────────────────

def build_analyze_messages(
    comment_body: str,
    diff_hunk: str,
    file_path: str,
    file_content: str,
    repo: str,
) -> List[dict]:
    """Build the messages list for the first-turn /analyze call."""

    # Truncate file content to budget
    file_truncated = _truncate_to_tokens(file_content, config.MAX_FILE_TOKENS)

    # RAG: query with comment + file path as context signal
    rag_query = f"{comment_body} {file_path}"
    rag_chunks = query_relevant_chunks(repo, rag_query, top_k=config.RAG_TOP_K)

    rag_section = ""
    if rag_chunks:
        parts = []
        for chunk in rag_chunks:
            parts.append(
                f"// {chunk.file_path} (lines {chunk.start_line}–{chunk.end_line})\n{chunk.text}"
            )
        rag_section = "\n\n--- RELATED CODEBASE CONTEXT ---\n" + "\n\n".join(parts)

    user_message = f"""--- REVIEW COMMENT ---
{comment_body}

--- FILE: {file_path} ---
{file_truncated}

--- DIFF HUNK ---
{diff_hunk}{rag_section}"""

    return [{"role": "user", "content": user_message}]


def build_chat_messages(
    conversation_history: List[dict],
    user_message: str,
) -> List[dict]:
    """Build the messages list for a follow-up /chat turn."""
    truncated_history = _truncate_history(
        conversation_history, max_tokens=2000
    )
    return truncated_history + [{"role": "user", "content": user_message}]
