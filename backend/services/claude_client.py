"""
Async Claude API wrapper with SSE streaming.
Yields structured events: {"type": "token", "content": "..."} or {"type": "done"} or {"type": "error", ...}
"""

import json
import logging
from typing import AsyncGenerator, List

import anthropic

import config

logger = logging.getLogger(__name__)


def _map_error(e: Exception) -> dict:
    msg = str(e)
    if isinstance(e, anthropic.AuthenticationError):
        return {"type": "error", "code": "invalid_key",
                "message": "Your Anthropic API key is invalid. Please check your settings."}
    if isinstance(e, anthropic.RateLimitError):
        return {"type": "error", "code": "rate_limit",
                "message": "You've hit the Anthropic API rate limit. Please try again shortly."}
    if isinstance(e, anthropic.BadRequestError) and "context_length" in msg.lower():
        return {"type": "error", "code": "context_too_long",
                "message": "The context is too large for the model. Try a smaller file."}
    return {"type": "error", "code": "unknown", "message": f"Unexpected error: {msg}"}


async def stream_response(
    system_prompt: str,
    messages: List[dict],
    api_key: str,
    model: str = None,
) -> AsyncGenerator[str, None]:
    """Stream a Claude response as SSE-formatted lines.

    Each yielded string is a complete SSE line, e.g.:
        'data: {"type": "token", "content": "Hello"}\n\n'
    """
    if model is None:
        model = config.DEFAULT_MODEL

    client = anthropic.AsyncAnthropic(api_key=api_key)

    try:
        async with client.messages.stream(
            model=model,
            max_tokens=config.MAX_OUTPUT_TOKENS,
            system=system_prompt,
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                payload = json.dumps({"type": "token", "content": text})
                yield f"data: {payload}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"
        logger.info(f'"action": "claude_stream_complete", "model": "{model}"')

    except Exception as e:
        error = _map_error(e)
        logger.error(f'"action": "claude_error", "code": "{error["code"]}", "detail": "{e}"')
        yield f"data: {json.dumps(error)}\n\n"
