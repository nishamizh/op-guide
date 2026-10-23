from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

_engine = None
_Session = None


def get_engine():
    global _engine, _Session
    if _engine is None:
        settings = get_settings()
        connect_args = {}
        if "sslmode=" not in settings.database_url and settings.db_sslmode:
            connect_args["sslmode"] = settings.db_sslmode
        _engine = create_engine(
            settings.database_url,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
        _Session = sessionmaker(bind=_engine, expire_on_commit=False, class_=Session)
    return _engine


def session_factory() -> sessionmaker[Session]:
    get_engine()
    assert _Session is not None
    return _Session


@contextmanager
def session_scope() -> Iterator[Session]:
    db = session_factory()()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def check_database() -> dict:
    settings = get_settings()
    with session_scope() as db:
        db.execute(text("SELECT 1"))
        ext = db.execute(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")).scalar()
        if not ext:
            raise RuntimeError("pgvector extension is not installed")
        typmod = db.execute(
            text(
                """
                SELECT a.atttypmod
                FROM pg_attribute a
                JOIN pg_class c ON a.attrelid = c.oid
                JOIN pg_namespace n ON c.relnamespace = n.oid
                WHERE c.relname = 'document_chunks'
                  AND a.attname = 'embedding'
                  AND NOT a.attisdropped
                """
            )
        ).scalar()
        version = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    return {
        "database": "ok",
        "pgvector": ext,
        "embedding_typmod": typmod,
        "alembic_version": version,
        "sslmode": settings.db_sslmode,
    }
