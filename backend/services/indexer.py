import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Dict, List

import config
from services.github_client import GitHubError, get_file_blob, get_file_content, get_repo_tree
from services.repo_summary import generate_summary, save_summary
from services.vector_store import Chunk, upsert_chunks

logger = logging.getLogger(__name__)

# ── In-memory index state (also persisted to disk) ───────────────

_index_state: Dict[str, dict] = {}


def _load_state() -> None:
    if config.INDEX_STATE_FILE.exists():
        try:
            _index_state.update(json.loads(config.INDEX_STATE_FILE.read_text()))
        except Exception:
            pass


def _save_state() -> None:
    config.BASE_DIR.mkdir(parents=True, exist_ok=True)
    config.INDEX_STATE_FILE.write_text(json.dumps(_index_state, indent=2))


_load_state()


# ── Public state accessors ────────────────────────────────────────

def get_index_status(repo: str) -> dict:
    return _index_state.get(repo, {"status": "not_indexed", "progress": 0.0})


def is_indexed(repo: str) -> bool:
    return _index_state.get(repo, {}).get("status") == "indexed"


# ── File filter ───────────────────────────────────────────────────

def _should_skip(path: str, size: int) -> bool:
    if size > config.MAX_FILE_SIZE_BYTES:
        return True
    lower = path.lower()
    for pattern in config.SKIP_PATH_PATTERNS:
        if pattern in lower:
            return True
    for ext in config.SKIP_EXTENSIONS:
        if lower.endswith(ext):
            return True
    return False


# ── Chunker ───────────────────────────────────────────────────────

def _estimate_tokens(text: str) -> int:
    # Rough approximation: 1 token ≈ 4 characters
    return len(text) // 4


def _chunk_text(file_path: str, content: str) -> List[Chunk]:
    """Split file content into fixed-size token chunks with overlap."""
    lines = content.splitlines()
    chunk_size = config.CHUNK_SIZE_TOKENS
    overlap = config.CHUNK_OVERLAP_TOKENS

    chunks: List[Chunk] = []
    chunk_index = 0
    current_lines: List[str] = []
    current_tokens = 0
    start_line = 1

    for line_num, line in enumerate(lines, start=1):
        line_tokens = _estimate_tokens(line)
        current_lines.append(line)
        current_tokens += line_tokens

        if current_tokens >= chunk_size:
            text = "\n".join(current_lines)
            chunks.append(Chunk(
                text=text,
                file_path=file_path,
                start_line=start_line,
                end_line=line_num,
                chunk_index=chunk_index,
            ))
            chunk_index += 1

            # Keep overlap lines for next chunk
            overlap_tokens = 0
            keep_lines: List[str] = []
            for l in reversed(current_lines):
                overlap_tokens += _estimate_tokens(l)
                if overlap_tokens > overlap:
                    break
                keep_lines.insert(0, l)

            current_lines = keep_lines
            current_tokens = sum(_estimate_tokens(l) for l in current_lines)
            start_line = line_num - len(keep_lines) + 1

    # Flush remaining lines
    if current_lines:
        chunks.append(Chunk(
            text="\n".join(current_lines),
            file_path=file_path,
            start_line=start_line,
            end_line=len(lines),
            chunk_index=chunk_index,
        ))

    return chunks


# ── Main indexing pipeline ────────────────────────────────────────

async def index_repo(repo: str, token: str, anthropic_key: str = "") -> None:
    """Full indexing pipeline. Runs as a background task."""
    logger.info(f'"action": "index_start", "repo": "{repo}"')
    _index_state[repo] = {"status": "indexing", "progress": 0.0}
    _save_state()

    start_time = time.monotonic()

    try:
        # 1. Fetch repo tree
        head_ref = await _get_default_branch_sha(repo, token)
        tree = await get_repo_tree(repo, head_ref, token)

        # 2. Filter files
        files_to_index = [
            e for e in tree
            if not _should_skip(e.path, e.size)
        ]
        total = len(files_to_index)
        logger.info(f'"action": "index_filter", "repo": "{repo}", "total_files": {total}')

        if total == 0:
            _index_state[repo] = {
                "status": "indexed",
                "indexed_at": _now(),
                "file_count": 0,
                "chunk_count": 0,
            }
            _save_state()
            return

        # 3. Fetch blobs and chunk in batches of 10
        all_chunks: List[Chunk] = []
        processed = 0
        batch_size = 10

        for i in range(0, total, batch_size):
            batch = files_to_index[i : i + batch_size]
            blob_tasks = [get_file_blob(repo, e.sha, token) for e in batch]

            results = await asyncio.gather(*blob_tasks, return_exceptions=True)

            for entry, result in zip(batch, results):
                if isinstance(result, Exception):
                    logger.warning(f'"action": "index_skip", "file": "{entry.path}", "error": "{result}"')
                    continue
                chunks = _chunk_text(entry.path, result)
                all_chunks.extend(chunks)

            processed += len(batch)
            progress = processed / total
            _index_state[repo]["progress"] = round(progress, 2)
            _save_state()

            # Small yield to keep the event loop responsive
            await asyncio.sleep(0)

        # 4. Upsert all chunks
        upsert_chunks(repo, all_chunks)

        # 5. Generate AI codebase summary (if API key provided)
        if anthropic_key:
            try:
                tree_paths = [e.path for e in files_to_index]
                readme = await _fetch_readme(repo, head_ref, token)
                summary = await generate_summary(repo, tree_paths, readme, anthropic_key)
                save_summary(repo, summary)
            except Exception as e:
                logger.warning(f'"action": "summary_failed", "repo": "{repo}", "error": "{e}"')

        duration = round(time.monotonic() - start_time, 1)
        _index_state[repo] = {
            "status": "indexed",
            "indexed_at": _now(),
            "file_count": processed,
            "chunk_count": len(all_chunks),
        }
        _save_state()
        logger.info(
            f'"action": "index_complete", "repo": "{repo}", '
            f'"files": {processed}, "chunks": {len(all_chunks)}, "duration_s": {duration}'
        )

    except Exception as e:
        logger.error(f'"action": "index_error", "repo": "{repo}", "error": "{e}"')
        _index_state[repo] = {"status": "error", "progress": 0.0, "error": str(e)}
        _save_state()


async def _fetch_readme(repo: str, ref: str, token: str) -> str:
    """Try to fetch README.md content; return empty string if not found."""
    for candidate in ("README.md", "readme.md", "README.rst", "README"):
        try:
            return await get_file_content(repo, candidate, ref, token)
        except GitHubError:
            continue
    return ""


async def _get_default_branch_sha(repo: str, token: str) -> str:
    """Fetch the SHA of the default branch HEAD."""
    import httpx
    from services.github_client import _headers, _raise_for_status, GITHUB_API
    url = f"{GITHUB_API}/repos/{repo}"
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, headers=_headers(token))
    _raise_for_status(r, "get_default_branch")
    default_branch = r.json()["default_branch"]

    url = f"{GITHUB_API}/repos/{repo}/git/ref/heads/{default_branch}"
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, headers=_headers(token))
    _raise_for_status(r, "get_branch_sha")
    return r.json()["object"]["sha"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
