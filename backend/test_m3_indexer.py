"""
Milestone 3 verification script — Repo Indexer + Vector Store

Usage:
    python test_m3_indexer.py \
        --token ghp_your_token \
        --repo  owner/repo \
        --query "some keyword or concept to search for"

Steps tested:
  1. Trigger indexing via POST /index
  2. Poll GET /index/status until complete
  3. Query ChromaDB for relevant chunks
  4. Print top results
"""

import argparse
import asyncio
import sys
import time

import httpx

BASE_URL = "http://127.0.0.1:8765"


def ok(label: str, value: str = "") -> None:
    print(f"  [PASS] {label}" + (f": {value}" if value else ""))


def fail(label: str, msg: str) -> None:
    print(f"  [FAIL] {label}: {msg}")


async def run(token: str, repo: str, query: str) -> None:
    print(f"\n=== M3 Indexer + Vector Store Test ===")
    print(f"repo={repo}  query=\"{query}\"\n")

    async with httpx.AsyncClient(timeout=30) as client:

        # 1. Trigger indexing
        print("1. POST /index")
        r = await client.post(f"{BASE_URL}/index", json={
            "repo": repo,
            "github_token": token,
            "force": True,
        })
        if r.status_code != 200:
            fail("POST /index", f"HTTP {r.status_code}: {r.text}")
            return
        data = r.json()
        ok("triggered", data.get("message", data.get("status")))
        print()

        # 2. Poll /index/status until done (timeout: 10 min)
        print("2. GET /index/status (polling...)")
        deadline = time.monotonic() + 600
        last_progress = -1

        while time.monotonic() < deadline:
            r = await client.get(f"{BASE_URL}/index/status", params={"repo": repo})
            status = r.json()
            progress = status.get("progress", 0.0)

            if progress != last_progress:
                print(f"     status={status['status']}  progress={int(progress * 100)}%")
                last_progress = progress

            if status["status"] == "indexed":
                ok("indexed",
                   f"files={status.get('file_count')}  chunks={status.get('chunk_count')}")
                break
            if status["status"] == "error":
                fail("indexing error", status.get("error", "unknown"))
                return

            await asyncio.sleep(3)
        else:
            fail("timeout", "indexing did not complete within 10 minutes")
            return
        print()

        # 3. Query vector store directly
        print("3. Query vector store")
        sys.path.insert(0, ".")
        from services.vector_store import query_relevant_chunks

        chunks = query_relevant_chunks(repo, query, top_k=3)
        if not chunks:
            fail("query_relevant_chunks", "returned 0 results")
            return

        ok("chunks returned", str(len(chunks)))
        print()
        for i, chunk in enumerate(chunks, 1):
            print(f"  Chunk {i}: {chunk.file_path} (lines {chunk.start_line}–{chunk.end_line})")
            preview = chunk.text[:120].replace("\n", " ")
            print(f"    \"{preview}...\"")
        print()

    print("=== All checks complete ===\n")


def main():
    parser = argparse.ArgumentParser(description="M3 indexer test")
    parser.add_argument("--token", required=True, help="GitHub PAT")
    parser.add_argument("--repo",  required=True, help="owner/repo")
    parser.add_argument("--query", default="function definition",
                        help="Semantic search query to test RAG retrieval")
    args = parser.parse_args()
    asyncio.run(run(args.token, args.repo, args.query))


if __name__ == "__main__":
    main()
