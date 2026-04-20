"""
Vector store using BM25 (keyword-based retrieval).

Chunks are persisted as JSON per repo under ~/.gh-ai-assistant/indexes/.
BM25 index is rebuilt in-memory from the stored chunks on each query
(fast enough for MVP — typical repos have < 5,000 chunks).
"""

import json
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional

import numpy as np
from rank_bm25 import BM25Okapi

import config

logger = logging.getLogger(__name__)

INDEXES_DIR = config.BASE_DIR / "indexes"


@dataclass
class Chunk:
    text: str
    file_path: str
    start_line: int
    end_line: int
    chunk_index: int


# ── Tokeniser ────────────────────────────────────────────────────

def _tokenize(text: str) -> List[str]:
    """Split on whitespace, underscores, and non-alphanumeric chars; lowercase."""
    return [t for t in re.split(r"[^a-zA-Z0-9]+", text.lower()) if t]


# ── Persistence helpers ──────────────────────────────────────────

def _index_path(repo: str) -> Path:
    safe = repo.replace("/", "__")
    return INDEXES_DIR / f"{safe}.json"


def _save_chunks(repo: str, chunks: List[Chunk]) -> None:
    INDEXES_DIR.mkdir(parents=True, exist_ok=True)
    data = [asdict(c) for c in chunks]
    _index_path(repo).write_text(json.dumps(data))


def _load_chunks(repo: str) -> List[Chunk]:
    path = _index_path(repo)
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return [Chunk(**d) for d in data]


# ── Public API ───────────────────────────────────────────────────

def upsert_chunks(repo: str, chunks: List[Chunk]) -> None:
    """Persist all chunks for a repo (replaces any existing index)."""
    _save_chunks(repo, chunks)
    logger.info(f'"action": "upsert_chunks", "repo": "{repo}", "count": {len(chunks)}')


def query_relevant_chunks(repo: str, query_text: str, top_k: Optional[int] = None) -> List[Chunk]:
    """Return the top-K most relevant chunks for a query using BM25."""
    if top_k is None:
        top_k = config.RAG_TOP_K

    chunks = _load_chunks(repo)
    if not chunks:
        logger.warning(f'"action": "query_chunks", "repo": "{repo}", "error": "no chunks found"')
        return []

    tokenized_corpus = [_tokenize(c.text) for c in chunks]
    bm25 = BM25Okapi(tokenized_corpus)

    query_tokens = _tokenize(query_text)
    scores = bm25.get_scores(query_tokens)

    top_indices = np.argsort(scores)[::-1][:top_k]
    results = [chunks[i] for i in top_indices if scores[i] > 0]

    logger.info(f'"action": "query_chunks", "repo": "{repo}", "returned": {len(results)}')
    return results


def delete_repo_index(repo: str) -> None:
    """Delete the stored chunk index for a repo."""
    path = _index_path(repo)
    if path.exists():
        path.unlink()
    logger.info(f'"action": "delete_index", "repo": "{repo}"')


def repo_chunk_count(repo: str) -> int:
    """Return the number of indexed chunks, or 0 if not indexed."""
    path = _index_path(repo)
    if not path.exists():
        return 0
    try:
        return len(json.loads(path.read_text()))
    except Exception:
        return 0
