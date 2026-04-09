import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.logging_setup import configure_logging
from app.routes import candidates, settings as settings_route, poll

configure_logging()
log = logging.getLogger(__name__)


def _run_migrations() -> None:
    """Run `alembic upgrade head` in-process at startup.

    The Docker image already runs this in its CMD, but local dev workflows
    (uvicorn / pytest) don't — and we don't want anyone to have to remember
    to run it after pulling a new migration. Failures are fatal: if the DB
    schema is wrong, the app shouldn't half-start with broken queries.
    """
    from alembic import command
    from alembic.config import Config

    ini_path = Path(__file__).resolve().parent.parent / "alembic.ini"
    if not ini_path.exists():
        log.warning("alembic.ini not found at %s — skipping migrations", ini_path)
        return
    cfg = Config(str(ini_path))
    cfg.set_main_option("script_location", str(ini_path.parent / "alembic"))
    log.info("running alembic upgrade head")
    command.upgrade(cfg, "head")


app = FastAPI(title="AI Candidate Evaluator", version="0.1.0")


@app.on_event("startup")
def _on_startup() -> None:
    if os.getenv("SKIP_STARTUP_MIGRATIONS") == "1":
        log.info("SKIP_STARTUP_MIGRATIONS=1, skipping in-process alembic upgrade")
        return
    _run_migrations()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in prod via env var if desired
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(candidates.router)
app.include_router(settings_route.router)
app.include_router(poll.router)


@app.get("/healthz")
def healthz():
    return {"ok": True}
