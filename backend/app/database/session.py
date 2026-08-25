"""SQLAlchemy engine and session helpers."""

from __future__ import annotations

from collections.abc import Generator, Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _ensure_sqlite_directory(url: str) -> None:
    """Create the folder a SQLite file lives in, if it is missing."""
    from pathlib import Path as _Path

    if ":memory:" in url:
        return
    _, _, path_part = url.partition("///")
    path_part = path_part.split("?", 1)[0]
    if not path_part:
        return
    target = _Path(path_part)
    if target.parent and not target.parent.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Created the database directory", extra={"path": str(target.parent)})


def _build_engine() -> Engine:
    settings = get_settings()
    url = settings.database_url
    kwargs: dict = {"echo": settings.db_echo, "future": True}

    if url.startswith("sqlite"):
        # SQLite will not create a missing directory: it reports "unable to open
        # database file", which reads like a permissions problem rather than a
        # missing folder. On a fresh checkout backend/data does not exist,
        # because the directory is gitignored along with the database itself.
        _ensure_sqlite_directory(url)
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url:
            kwargs["poolclass"] = StaticPool
    else:
        kwargs.update(
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            pool_recycle=1800,
        )
    return create_engine(url, **kwargs)


engine: Engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:  # pragma: no cover
    """Tune SQLite for a long running writer next to live readers.

    A matrix backtest commits once per grid cell - thousands of small writes -
    while the dashboard keeps polling and the trading engine keeps journalling.
    In SQLite's default rollback journal a writer blocks every reader, so that
    combination produces "database is locked" errors. WAL lets readers carry on
    during a write, and busy_timeout makes the remaining collisions wait instead
    of failing.
    """
    module = type(dbapi_connection).__module__
    if "sqlite" not in module:
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a request-scoped database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context manager providing a transactional session for background tasks."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
