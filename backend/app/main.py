import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.logging_setup import configure_logging
from app.routes import candidates, logs as logs_route, settings as settings_route, poll

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


def _run_worker_loop(stop_event: threading.Event) -> None:
    """Run the job worker loop in a background thread.

    Mirrors app.jobs.worker.main() but uses a threading.Event for shutdown
    instead of signal handlers (which only work in the main thread).
    Auto-restarts on unexpected errors with a brief delay.
    """
    from app.config import get_settings
    from app.db import SessionLocal
    from app.jobs import queue
    from app.jobs.worker import maybe_poll_inbox, run_one_job

    s = get_settings()
    state: dict = {"last_poll_at": 0}
    log.info("embedded worker started (poll_interval=%ss)", s.worker_poll_interval_seconds)

    while not stop_event.is_set():
        try:
            maybe_poll_inbox(state)
            db = SessionLocal()
            try:
                jobs = queue.claim_due(db, limit=5)
            finally:
                db.close()
            if not jobs:
                stop_event.wait(timeout=s.worker_poll_interval_seconds)
                continue
            log.info("worker: claimed %d job(s): %s", len(jobs), [j.type for j in jobs])
            for j in jobs:
                run_one_job(j)
        except Exception:
            log.exception("worker loop error — restarting in 5s")
            stop_event.wait(timeout=5)

    log.info("embedded worker stopped")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: run migrations
    if os.getenv("SKIP_STARTUP_MIGRATIONS") != "1":
        _run_migrations()

    # Start embedded worker thread
    stop_event = threading.Event()
    worker_thread = threading.Thread(
        target=_run_worker_loop,
        args=(stop_event,),
        daemon=True,
        name="worker",
    )
    worker_thread.start()

    yield

    # Shutdown: stop worker gracefully
    stop_event.set()
    worker_thread.join(timeout=10)


app = FastAPI(title="AI Candidate Evaluator", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in prod via env var if desired
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(candidates.router)
app.include_router(logs_route.router)
app.include_router(settings_route.router)
app.include_router(poll.router)


@app.get("/healthz")
def healthz():
    return {"ok": True}
