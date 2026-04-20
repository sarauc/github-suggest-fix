import logging
import logging.handlers
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import config
from routes.health import router as health_router
from routes.index import router as index_router


# ── Logging setup ─────────────────────────────────────────────────
def setup_logging():
    config.BASE_DIR.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        '{"time": "%(asctime)s", "level": "%(levelname)s", "msg": %(message)s}',
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    # Rotating file handler
    file_handler = logging.handlers.RotatingFileHandler(
        config.LOG_FILE,
        maxBytes=config.LOG_MAX_BYTES,
        backupCount=2,
    )
    file_handler.setFormatter(fmt)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter("%(levelname)s  %(message)s"))

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console_handler)


setup_logging()
logger = logging.getLogger(__name__)

# ── App ───────────────────────────────────────────────────────────
app = FastAPI(title="PR Review AI Assistant", version=config.VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://github.com", "http://localhost"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

app.include_router(health_router)
app.include_router(index_router)


@app.on_event("startup")
async def on_startup():
    logger.info(f'"Server started at http://{config.HOST}:{config.PORT}"')
