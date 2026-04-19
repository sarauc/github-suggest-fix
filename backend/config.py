import os
from pathlib import Path

# Server
HOST = "127.0.0.1"
PORT = 8765
VERSION = "0.1.0"

# Storage — all data lives under ~/.gh-ai-assistant/
BASE_DIR = Path.home() / ".gh-ai-assistant"
CHROMA_DIR = BASE_DIR / "chroma"
INDEX_STATE_FILE = BASE_DIR / "index_state.json"
LOG_FILE = BASE_DIR / "server.log"
LOG_MAX_BYTES = 10 * 1024 * 1024  # 10 MB

# RAG
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
CHUNK_SIZE_TOKENS = 400
CHUNK_OVERLAP_TOKENS = 50
RAG_TOP_K = 5

# Claude
DEFAULT_MODEL = "claude-sonnet-4-5"
MAX_OUTPUT_TOKENS = 1500
MAX_FILE_TOKENS = 8000

# Indexing
MAX_FILE_SIZE_BYTES = 200 * 1024  # 200 KB
INDEXING_TIMEOUT_SECONDS = 300    # 5 min before falling back to non-RAG

SKIP_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".pdf",
    ".zip", ".tar", ".gz", ".bz2", ".7z",
    ".lock", ".min.js", ".min.css",
    ".woff", ".woff2", ".ttf", ".eot",
    ".pyc", ".pyo", ".class", ".o", ".so", ".dll", ".exe",
    ".db", ".sqlite", ".sqlite3",
}

SKIP_PATH_PATTERNS = [
    "node_modules/", ".git/", "dist/", "build/", "__pycache__/",
    ".next/", "vendor/", "coverage/", ".venv/", "venv/",
]
