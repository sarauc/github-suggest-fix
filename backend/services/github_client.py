import base64
import logging
from dataclasses import dataclass
from typing import List, Optional

import httpx

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
API_VERSION = "2022-11-28"


# ── Exceptions ────────────────────────────────────────────────────

class GitHubError(Exception):
    """Base error for GitHub API failures."""
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


class GitHubAuthError(GitHubError):
    """401 — token missing or invalid."""


class GitHubRateLimitError(GitHubError):
    """403 — rate limit exceeded."""


class GitHubNotFoundError(GitHubError):
    """404 — resource does not exist."""


# ── Return types ──────────────────────────────────────────────────

@dataclass
class PRComment:
    comment_id: int
    body: str
    diff_hunk: str
    file_path: str        # path field from GitHub
    line: Optional[int]   # line in the file (None for top-level PR comments)
    commit_id: str


@dataclass
class TreeEntry:
    path: str
    sha: str
    size: int             # 0 for directories
    entry_type: str       # "blob" | "tree"


# ── Client ────────────────────────────────────────────────────────

def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": API_VERSION,
    }


def _raise_for_status(response: httpx.Response, context: str) -> None:
    if response.status_code == 401:
        raise GitHubAuthError(
            f"GitHub token is invalid or missing ({context})", 401
        )
    if response.status_code == 403:
        raise GitHubRateLimitError(
            f"GitHub rate limit exceeded ({context})", 403
        )
    if response.status_code == 404:
        raise GitHubNotFoundError(
            f"GitHub resource not found ({context})", 404
        )
    if response.status_code >= 400:
        raise GitHubError(
            f"GitHub API error {response.status_code} ({context}): {response.text}",
            response.status_code,
        )


async def get_pr_comment(repo: str, comment_id: int, token: str) -> PRComment:
    """Fetch a single PR review comment by ID.

    Returns the comment body, diff hunk, file path, and commit SHA.
    """
    url = f"{GITHUB_API}/repos/{repo}/pulls/comments/{comment_id}"
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(url, headers=_headers(token))

    _raise_for_status(response, f"get_pr_comment {comment_id}")
    data = response.json()

    logger.info(f'"action": "get_pr_comment", "repo": "{repo}", "comment_id": {comment_id}')
    return PRComment(
        comment_id=data["id"],
        body=data["body"],
        diff_hunk=data.get("diff_hunk", ""),
        file_path=data["path"],
        line=data.get("line") or data.get("original_line"),
        commit_id=data["commit_id"],
    )


async def get_file_content(repo: str, file_path: str, ref: str, token: str) -> str:
    """Fetch the raw text content of a file at a given ref (commit SHA or branch).

    Returns the decoded file content as a string.
    Raises GitHubNotFoundError for binary files or missing files.
    """
    url = f"{GITHUB_API}/repos/{repo}/contents/{file_path}"
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(url, headers=_headers(token), params={"ref": ref})

    _raise_for_status(response, f"get_file_content {file_path}@{ref}")
    data = response.json()

    if data.get("encoding") != "base64":
        raise GitHubNotFoundError(
            f"Unexpected encoding for {file_path}: {data.get('encoding')}"
        )

    raw = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    logger.info(f'"action": "get_file_content", "repo": "{repo}", "path": "{file_path}", "bytes": {len(raw)}')
    return raw


async def get_repo_tree(repo: str, ref: str, token: str) -> List[TreeEntry]:
    """Fetch the full recursive file tree of a repo at a given ref.

    Returns a flat list of TreeEntry for all blobs (files) in the tree.
    Directories (type=tree) are excluded.
    """
    url = f"{GITHUB_API}/repos/{repo}/git/trees/{ref}"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            url, headers=_headers(token), params={"recursive": "1"}
        )

    _raise_for_status(response, f"get_repo_tree {repo}@{ref}")
    data = response.json()

    if data.get("truncated"):
        logger.warning(f'"action": "get_repo_tree", "repo": "{repo}", "truncated": true')

    entries = [
        TreeEntry(
            path=item["path"],
            sha=item["sha"],
            size=item.get("size", 0),
            entry_type=item["type"],
        )
        for item in data.get("tree", [])
        if item["type"] == "blob"
    ]

    logger.info(f'"action": "get_repo_tree", "repo": "{repo}", "file_count": {len(entries)}')
    return entries


async def get_file_blob(repo: str, blob_sha: str, token: str) -> str:
    """Fetch and decode a file blob by its SHA.

    Returns the decoded text content.
    Raises GitHubNotFoundError if the blob is binary or cannot be decoded.
    """
    url = f"{GITHUB_API}/repos/{repo}/git/blobs/{blob_sha}"
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(url, headers=_headers(token))

    _raise_for_status(response, f"get_file_blob {blob_sha}")
    data = response.json()

    if data.get("encoding") != "base64":
        raise GitHubNotFoundError(
            f"Unexpected blob encoding: {data.get('encoding')}"
        )

    return base64.b64decode(data["content"]).decode("utf-8", errors="replace")


async def get_pr_head_ref(repo: str, pr_number: int, token: str) -> str:
    """Return the head commit SHA of a pull request."""
    url = f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}"
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(url, headers=_headers(token))

    _raise_for_status(response, f"get_pr_head_ref PR#{pr_number}")
    data = response.json()
    return data["head"]["sha"]
