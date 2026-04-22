import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from services.indexer import get_index_status, index_repo, is_indexed

logger = logging.getLogger(__name__)
router = APIRouter()


class IndexRequest(BaseModel):
    repo: str         # "owner/repo"
    github_token: str
    force: bool = False   # re-index even if already indexed
    anthropic_key: str = ""   # used to generate AI codebase summary after indexing


@router.post("/index")
async def start_index(body: IndexRequest, background_tasks: BackgroundTasks):
    status = get_index_status(body.repo)

    if status.get("status") == "indexing":
        return {"status": "indexing", "message": "Already in progress"}

    if is_indexed(body.repo) and not body.force:
        return {"status": "indexed", "message": "Already indexed. Pass force=true to re-index."}

    background_tasks.add_task(index_repo, body.repo, body.github_token, body.anthropic_key)
    logger.info(f'"action": "index_triggered", "repo": "{body.repo}"')
    return {"status": "indexing", "message": "Indexing started"}


@router.get("/index/status")
async def index_status(repo: str):
    return get_index_status(repo)
