import logging
import threading
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import text

from app.config import get_settings
from app.db import session_scope
from app.ingestion.pipeline import process_job
from app.models import ChatSession

logger = logging.getLogger(__name__)
_stop = threading.Event()
_thread: threading.Thread | None = None


def claim_job_id() -> uuid.UUID | None:
    with session_scope() as db:
        row = db.execute(
            text(
                """
                UPDATE ingestion_jobs
                SET status = 'running', locked_at = now(), started_at = COALESCE(started_at, now())
                WHERE id = (
                    SELECT id FROM ingestion_jobs
                    WHERE status = 'queued'
                    ORDER BY created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                RETURNING id
                """
            )
        ).first()
        if row is None:
            return None
        return row[0]


def run_once() -> bool:
    job_id = claim_job_id()
    if job_id is None:
        return False
    try:
        with session_scope() as db:
            process_job(db, job_id)
    except Exception:
        logger.exception("ingestion job failed", extra={"job_id": str(job_id)})
    return True


def purge_expired() -> int:
    with session_scope() as db:
        expired = (
            db.query(ChatSession)
            .filter(ChatSession.retain_until < datetime.now(UTC))
            .all()
        )
        count = len(expired)
        for session in expired:
            db.delete(session)
        return count


def _loop() -> None:
    ticks = 0
    while not _stop.is_set():
        worked = False
        try:
            worked = run_once()
            ticks += 1
            if ticks % 120 == 0:
                purge_expired()
        except Exception:
            logger.exception("worker loop error")
        if not worked:
            _stop.wait(1.0)


def start_worker() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="manualmind-worker", daemon=True)
    _thread.start()


def stop_worker() -> None:
    _stop.set()


def worker_main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    logger.info("ingestion worker started")
    while True:
        try:
            if not run_once():
                time.sleep(1)
        except Exception:
            logger.exception("worker iteration failed")
            time.sleep(2)
