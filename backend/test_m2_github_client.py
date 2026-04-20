"""
Milestone 2 verification script — GitHub API Client

Usage:
    python test_m2_github_client.py \
        --token  ghp_your_token \
        --repo   owner/repo \
        --pr     42 \
        --comment-id  123456789

All four client methods are called and results printed.
"""

import argparse
import asyncio
import sys

# Make sure we can import from the backend package
sys.path.insert(0, ".")

from services.github_client import (
    GitHubAuthError,
    GitHubNotFoundError,
    GitHubRateLimitError,
    get_file_blob,
    get_file_content,
    get_pr_comment,
    get_pr_head_ref,
    get_repo_tree,
)


def ok(label: str, value: str = "") -> None:
    print(f"  [PASS] {label}" + (f": {value}" if value else ""))


def fail(label: str, err: Exception) -> None:
    print(f"  [FAIL] {label}: {err}")


async def run(token: str, repo: str, pr_number: int, comment_id: int) -> None:
    print(f"\n=== M2 GitHub Client Test ===")
    print(f"repo={repo}  PR=#{pr_number}  comment={comment_id}\n")

    # 1. get_pr_comment
    print("1. get_pr_comment()")
    try:
        comment = await get_pr_comment(repo, comment_id, token)
        ok("comment body",    comment.body[:80].replace("\n", " "))
        ok("diff_hunk",       comment.diff_hunk[:60].replace("\n", " ") + "...")
        ok("file_path",       comment.file_path)
        ok("commit_id",       comment.commit_id[:12])
    except (GitHubAuthError, GitHubRateLimitError, GitHubNotFoundError) as e:
        fail("get_pr_comment", e)
        print("\nAborting — cannot continue without a valid comment.")
        return
    print()

    # 2. get_pr_head_ref
    print("2. get_pr_head_ref()")
    try:
        head_sha = await get_pr_head_ref(repo, pr_number, token)
        ok("head SHA", head_sha[:12])
    except Exception as e:
        fail("get_pr_head_ref", e)
        head_sha = comment.commit_id   # fallback to comment's commit
    print()

    # 3. get_file_content
    print("3. get_file_content()")
    try:
        content = await get_file_content(repo, comment.file_path, head_sha, token)
        lines = content.splitlines()
        ok("file lines",    str(len(lines)))
        ok("first line",    lines[0][:80] if lines else "(empty)")
    except GitHubNotFoundError as e:
        fail("get_file_content (may be binary)", e)
    except Exception as e:
        fail("get_file_content", e)
    print()

    # 4. get_repo_tree + get_file_blob
    print("4. get_repo_tree()")
    try:
        tree = await get_repo_tree(repo, head_sha, token)
        ok("total files", str(len(tree)))

        # Find the commented file in the tree for blob test
        target = next((e for e in tree if e.path == comment.file_path), None)
        if target:
            ok("found commented file in tree", target.path)

            print("\n5. get_file_blob()")
            blob_text = await get_file_blob(repo, target.sha, token)
            ok("blob lines", str(len(blob_text.splitlines())))
        else:
            print("  [SKIP] get_file_blob — file not found in tree")
    except Exception as e:
        fail("get_repo_tree", e)

    print("\n=== All checks complete ===\n")


def main():
    parser = argparse.ArgumentParser(description="M2 GitHub client test")
    parser.add_argument("--token",      required=True, help="GitHub PAT")
    parser.add_argument("--repo",       required=True, help="owner/repo")
    parser.add_argument("--pr",         required=True, type=int, help="PR number")
    parser.add_argument("--comment-id", required=True, type=int, dest="comment_id",
                        help="PR review comment ID")
    args = parser.parse_args()

    asyncio.run(run(args.token, args.repo, args.pr, args.comment_id))


if __name__ == "__main__":
    main()
