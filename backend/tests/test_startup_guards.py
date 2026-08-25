"""Startup failures should say what to change.

The database URL default used to point at "db", the PostgreSQL service name
inside docker compose. Outside a container it resolves nowhere, and the failure
surfaced as a hundred lines of psycopg2 and SQLAlchemy traceback ending in
"could not translate host name" - accurate, and useless to anyone trying to fix
it. A .env is not in version control either, so a stale one survives every pull
and the same wall gets hit again after the defaults are corrected.
"""

from __future__ import annotations

import pytest

from app.database.session import _check_docker_only_host, _ensure_sqlite_directory


class TestDockerHostnameGuard:
    def test_the_compose_hostname_is_refused_with_instructions(self) -> None:
        with pytest.raises(RuntimeError) as excinfo:
            _check_docker_only_host("postgresql+psycopg2://trader:pw@db:5432/trading")
        message = str(excinfo.value)
        assert "sqlite+pysqlite" in message, "the message must contain the line to paste"
        assert "localhost" in message, "and the alternative for a real PostgreSQL"
        assert "git pull" in message, "and why pulling does not fix it"

    def test_sqlite_passes(self) -> None:
        _check_docker_only_host("sqlite+pysqlite:///./data/dev.db")

    def test_a_real_postgres_host_passes(self) -> None:
        _check_docker_only_host("postgresql+psycopg2://t:p@localhost:5432/trading")

    def test_a_database_actually_named_db_is_not_confused_for_the_host(self) -> None:
        """The check looks for the host position, not the word anywhere."""
        _check_docker_only_host("postgresql+psycopg2://t:p@localhost:5432/db")

    def test_inside_docker_it_stays_quiet(self, monkeypatch) -> None:
        monkeypatch.setenv("RUNNING_IN_DOCKER", "1")
        _check_docker_only_host("postgresql+psycopg2://trader:pw@db:5432/trading")


class TestSqliteDirectory:
    def test_a_missing_directory_is_created(self, tmp_path) -> None:
        """SQLite reports "unable to open database file" for a missing folder,
        which reads like a permissions problem."""
        target = tmp_path / "nested" / "deeper" / "dev.db"
        _ensure_sqlite_directory(f"sqlite+pysqlite:///{target.as_posix()}")
        assert target.parent.is_dir()

    def test_an_existing_directory_is_left_alone(self, tmp_path) -> None:
        target = tmp_path / "dev.db"
        _ensure_sqlite_directory(f"sqlite+pysqlite:///{target.as_posix()}")
        assert tmp_path.is_dir()

    def test_in_memory_needs_no_directory(self) -> None:
        _ensure_sqlite_directory("sqlite+pysqlite:///:memory:")
