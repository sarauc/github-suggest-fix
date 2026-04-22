import logging
import os
import re
from typing import List, Optional, Tuple

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services.claude_client import stream_response
from services.context_assembler import (
    SYSTEM_PROMPT,
    build_analyze_messages,
    build_chat_messages,
)
from services.github_client import (
    GitHubError,
    get_file_content,
    get_pr_comment,
    get_pr_files,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class Message(BaseModel):
    role: str
    content: str


class AnalyzeRequest(BaseModel):
    repo: str
    pr_number: int
    comment_id: str
    comment_body: str
    github_token: str
    anthropic_key: str
    # Optional — backend fetches these if empty
    diff_hunk:    str = ""
    file_path:    str = ""
    file_content: str = ""


class ChatRequest(BaseModel):
    repo: str
    comment_id: str
    user_message: str
    conversation_history: List[Message]
    anthropic_key: str
    # Original context — re-fetched by backend to pin into every chat turn
    github_token:  str = ""
    comment_body:  str = ""


# ── Import parser (shallow, 1 level) ─────────────────────────────

def _parse_local_imports(file_path: str, content: str) -> List[str]:
    """Return resolved repo-relative paths for local imports (up to 3)."""
    ext = os.path.splitext(file_path)[1].lower()
    base_dir = os.path.dirname(file_path)
    results = []

    if ext == ".py":
        # Match: from .module import X  (single-level relative only)
        for m in re.finditer(r'^from\s+\.([\w]+)\s+import', content, re.MULTILINE):
            module_name = m.group(1)
            candidate = "/".join(filter(None, [base_dir, module_name + ".py"]))
            if candidate not in results:
                results.append(candidate)
            if len(results) >= 3:
                break

    elif ext in (".js", ".ts", ".jsx", ".tsx"):
        # Match: import ... from './path' or '../path'
        for m in re.finditer(r'''from\s+['"](\.[^'"]+)['"]''', content, re.MULTILINE):
            rel = m.group(1)
            resolved = os.path.normpath(os.path.join(base_dir or ".", rel)).replace("\\", "/")
            # Try the path as-is first, then with common extensions
            for candidate in (resolved, resolved + ".ts", resolved + ".js",
                               resolved + ".tsx", resolved + ".jsx"):
                if candidate not in results:
                    results.append(candidate)
                    break
            if len(results) >= 3:
                break

    return results[:3]


async def _fetch_import_deps(
    repo: str,
    file_path: str,
    file_content: str,
    ref: str,
    token: str,
) -> List[Tuple[str, str]]:
    """Fetch up to 3 local import dependencies; silently skip failures."""
    paths = _parse_local_imports(file_path, file_content)
    deps = []
    for dep_path in paths:
        try:
            content = await get_file_content(repo, dep_path, ref, token)
            deps.append((dep_path, content))
        except GitHubError:
            pass
    return deps


# ── Full context enrichment ───────────────────────────────────────

async def _fetch_full_context(body: AnalyzeRequest):
    """Fetch all context needed for the analyze prompt.

    Returns (enriched_body, pr_files, import_deps).
    """
    diff_hunk    = body.diff_hunk
    file_path    = body.file_path
    file_content = body.file_content
    commit_id    = ""

    # 1. Fetch comment data + file content if not provided
    if not file_content:
        try:
            comment = await get_pr_comment(body.repo, int(body.comment_id), body.github_token)
            file_content = await get_file_content(
                body.repo, comment.file_path, comment.commit_id, body.github_token
            )
            diff_hunk  = comment.diff_hunk
            file_path  = comment.file_path
            commit_id  = comment.commit_id
        except GitHubError as e:
            logger.warning(f'"action": "enrich_context_failed", "error": "{e}"')

    # 2. Fetch all PR changed files (for related-diff section)
    pr_files = []
    try:
        raw_files = await get_pr_files(body.repo, body.pr_number, body.github_token)
        pr_files = [{"filename": f.filename, "patch": f.patch} for f in raw_files]
    except GitHubError as e:
        logger.warning(f'"action": "get_pr_files_failed", "error": "{e}"')

    # 3. Shallow import tracing
    import_deps = []
    if file_content and file_path and body.github_token:
        try:
            import_deps = await _fetch_import_deps(
                body.repo, file_path, file_content,
                commit_id or "HEAD", body.github_token,
            )
        except Exception as e:
            logger.warning(f'"action": "import_deps_failed", "error": "{e}"')

    enriched = body.copy(update={
        "diff_hunk":    diff_hunk,
        "file_path":    file_path,
        "file_content": file_content,
    })
    return enriched, pr_files, import_deps


async def _fetch_chat_context(
    repo: str, comment_id: str, github_token: str
) -> Tuple[str, str, str]:
    """Re-fetch diff_hunk, file_path, file_content for pinning into chat turns."""
    try:
        comment = await get_pr_comment(repo, int(comment_id), github_token)
        file_content = await get_file_content(
            repo, comment.file_path, comment.commit_id, github_token
        )
        return comment.diff_hunk, comment.file_path, file_content
    except GitHubError as e:
        logger.warning(f'"action": "chat_context_failed", "error": "{e}"')
        return "", "", ""


# ── Routes ────────────────────────────────────────────────────────

@router.post("/analyze")
async def analyze(body: AnalyzeRequest):
    logger.info(f'"action": "analyze", "repo": "{body.repo}", "comment": "{body.comment_id}"')

    body, pr_files, import_deps = await _fetch_full_context(body)

    messages = build_analyze_messages(
        comment_body=body.comment_body,
        diff_hunk=body.diff_hunk,
        file_path=body.file_path,
        file_content=body.file_content,
        repo=body.repo,
        pr_files=pr_files,
        import_deps=import_deps,
    )
    return StreamingResponse(
        stream_response(SYSTEM_PROMPT, messages, body.anthropic_key),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat")
async def chat(body: ChatRequest):
    logger.info(f'"action": "chat", "repo": "{body.repo}", "comment": "{body.comment_id}"')

    history = [{"role": m.role, "content": m.content} for m in body.conversation_history]

    # Re-fetch code context to pin into the chat turn
    diff_hunk = file_path = file_content = ""
    if body.github_token and body.comment_id:
        diff_hunk, file_path, file_content = await _fetch_chat_context(
            body.repo, body.comment_id, body.github_token
        )

    messages = build_chat_messages(
        conversation_history=history,
        user_message=body.user_message,
        comment_body=body.comment_body,
        diff_hunk=diff_hunk,
        file_path=file_path,
        file_content=file_content,
    )
    return StreamingResponse(
        stream_response(SYSTEM_PROMPT, messages, body.anthropic_key),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
