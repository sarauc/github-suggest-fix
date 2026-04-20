import logging
from typing import List, Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services.claude_client import stream_response
from services.context_assembler import (
    SYSTEM_PROMPT,
    build_analyze_messages,
    build_chat_messages,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class Message(BaseModel):
    role: str    # "user" | "assistant"
    content: str


class AnalyzeRequest(BaseModel):
    repo: str
    pr_number: int
    comment_id: str
    comment_body: str
    diff_hunk: str
    file_path: str
    file_content: str
    github_token: str
    anthropic_key: str


class ChatRequest(BaseModel):
    repo: str
    comment_id: str
    user_message: str
    conversation_history: List[Message]
    anthropic_key: str


@router.post("/analyze")
async def analyze(body: AnalyzeRequest):
    logger.info(
        f'"action": "analyze", "repo": "{body.repo}", "comment": "{body.comment_id}"'
    )
    messages = build_analyze_messages(
        comment_body=body.comment_body,
        diff_hunk=body.diff_hunk,
        file_path=body.file_path,
        file_content=body.file_content,
        repo=body.repo,
    )
    return StreamingResponse(
        stream_response(SYSTEM_PROMPT, messages, body.anthropic_key),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat")
async def chat(body: ChatRequest):
    logger.info(
        f'"action": "chat", "repo": "{body.repo}", "comment": "{body.comment_id}"'
    )
    history = [{"role": m.role, "content": m.content} for m in body.conversation_history]
    messages = build_chat_messages(history, body.user_message)
    return StreamingResponse(
        stream_response(SYSTEM_PROMPT, messages, body.anthropic_key),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
