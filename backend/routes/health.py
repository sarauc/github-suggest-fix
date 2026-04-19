from fastapi import APIRouter
from config import VERSION

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok", "version": VERSION}
