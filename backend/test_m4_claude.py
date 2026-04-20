"""
Milestone 4 verification script — Claude Integration + Prompt

Usage:
    python test_m4_claude.py \
        --anthropic-key sk-ant-... \
        --github-token  ghp_... \
        --repo          owner/repo \
        --pr            42 \
        --comment-id    123456789

Tests:
  1. POST /analyze  — streams a first-turn analysis
  2. POST /chat     — streams a follow-up response
  3. Error handling — invalid API key returns structured error
"""

import argparse
import asyncio
import json

import httpx

BASE_URL = "http://127.0.0.1:8765"


def ok(label: str, value: str = "") -> None:
    print(f"  [PASS] {label}" + (f": {value}" if value else ""))


def fail(label: str, msg: str) -> None:
    print(f"  [FAIL] {label}: {msg}")


async def collect_sse(response: httpx.Response) -> tuple:
    """Collect all SSE tokens into a full text string. Return (full_text, last_event)."""
    full_text = []
    last_event = None
    async for line in response.aiter_lines():
        if line.startswith("data: "):
            event = json.loads(line[6:])
            last_event = event
            if event.get("type") == "token":
                full_text.append(event["content"])
    return "".join(full_text), last_event


async def run(anthropic_key: str, github_token: str, repo: str, pr: int, comment_id: int):
    print(f"\n=== M4 Claude Integration Test ===")
    print(f"repo={repo}  PR=#{pr}  comment={comment_id}\n")

    # Fetch real comment data for a realistic test
    import sys
    sys.path.insert(0, ".")
    from services.github_client import get_pr_comment, get_file_content, get_pr_head_ref

    print("Fetching comment data from GitHub...")
    comment = await get_pr_comment(repo, comment_id, github_token)
    head_sha = await get_pr_head_ref(repo, pr, github_token)
    file_content = await get_file_content(repo, comment.file_path, head_sha, github_token)
    print(f"  comment: {comment.body[:60]}...")
    print(f"  file:    {comment.file_path} ({len(file_content.splitlines())} lines)\n")

    async with httpx.AsyncClient(timeout=120) as client:

        # ── Test 1: POST /analyze ────────────────────────────────
        print("1. POST /analyze (streaming...)")
        async with client.stream("POST", f"{BASE_URL}/analyze", json={
            "repo": repo,
            "pr_number": pr,
            "comment_id": str(comment_id),
            "comment_body": comment.body,
            "diff_hunk": comment.diff_hunk,
            "file_path": comment.file_path,
            "file_content": file_content,
            "github_token": github_token,
            "anthropic_key": anthropic_key,
        }) as response:
            if response.status_code != 200:
                fail("POST /analyze", f"HTTP {response.status_code}")
                return
            full_text, last_event = await collect_sse(response)

        if last_event and last_event.get("type") == "error":
            fail("stream completed with error", last_event.get("message", ""))
            return

        if not full_text:
            fail("POST /analyze", "received empty response")
            return

        ok("streamed response", f"{len(full_text)} chars")

        # Verify expected structure sections appear in the response
        lower = full_text.lower()
        if "reviewer" in lower or "mean" in lower or "concern" in lower:
            ok("contains reviewer interpretation")
        else:
            fail("missing interpretation section", "expected reviewer explanation")

        if "option" in lower or "approach" in lower or "way" in lower:
            ok("contains multiple options/approaches")
        else:
            fail("missing options section", "expected multiple approaches")

        print(f"\n  --- Response preview (first 400 chars) ---")
        print(f"  {full_text[:400].replace(chr(10), chr(10) + '  ')}")
        print(f"  ---\n")

        first_assistant_message = {"role": "assistant", "content": full_text}

        # ── Test 2: POST /chat ───────────────────────────────────
        print("2. POST /chat (follow-up, streaming...)")
        async with client.stream("POST", f"{BASE_URL}/chat", json={
            "repo": repo,
            "comment_id": str(comment_id),
            "user_message": "Can you elaborate on the first option you mentioned?",
            "conversation_history": [first_assistant_message],
            "anthropic_key": anthropic_key,
        }) as response:
            if response.status_code != 200:
                fail("POST /chat", f"HTTP {response.status_code}")
                return
            chat_text, last_event = await collect_sse(response)

        if last_event and last_event.get("type") == "error":
            fail("chat error", last_event.get("message", ""))
            return

        ok("chat follow-up streamed", f"{len(chat_text)} chars")
        print(f"\n  --- Chat preview (first 200 chars) ---")
        print(f"  {chat_text[:200].replace(chr(10), chr(10) + '  ')}")
        print(f"  ---\n")

        # ── Test 3: Error handling — invalid key ─────────────────
        print("3. Error handling — invalid API key")
        async with client.stream("POST", f"{BASE_URL}/analyze", json={
            "repo": repo,
            "pr_number": pr,
            "comment_id": str(comment_id),
            "comment_body": comment.body,
            "diff_hunk": comment.diff_hunk,
            "file_path": comment.file_path,
            "file_content": "short content",
            "github_token": github_token,
            "anthropic_key": "sk-ant-INVALID",
        }) as response:
            _, error_event = await collect_sse(response)

        if error_event and error_event.get("type") == "error":
            ok("structured error returned", f"code={error_event.get('code')}")
        else:
            fail("expected error event", f"got: {error_event}")

    print("\n=== All M4 checks complete ===\n")


def main():
    parser = argparse.ArgumentParser(description="M4 Claude integration test")
    parser.add_argument("--anthropic-key", required=True, dest="anthropic_key")
    parser.add_argument("--github-token",  required=True, dest="github_token")
    parser.add_argument("--repo",          required=True)
    parser.add_argument("--pr",            required=True, type=int)
    parser.add_argument("--comment-id",    required=True, type=int, dest="comment_id")
    args = parser.parse_args()

    asyncio.run(run(
        args.anthropic_key, args.github_token,
        args.repo, args.pr, args.comment_id,
    ))


if __name__ == "__main__":
    main()
