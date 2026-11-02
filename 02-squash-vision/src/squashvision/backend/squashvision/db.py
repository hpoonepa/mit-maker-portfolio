from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import URL, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from squashvision.settings import Settings


class Database:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._sessions = sessionmaker(
            bind=engine,
            class_=Session,
            expire_on_commit=False,
        )

    @classmethod
    def open(cls, settings: Settings, *, migrate: bool = True) -> Database:
        if settings.database_path is None:
            raise ValueError("settings.database_path must be configured")
        database_path = Path(settings.database_path).expanduser().resolve(strict=False)
        database_path.parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(
            URL.create("sqlite+pysqlite", database=str(database_path)),
            future=True,
        )
        cls._install_sqlite_pragmas(engine)
        if migrate:
            cls._upgrade(engine)
        return cls(engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self._sessions()
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    @staticmethod
    def _install_sqlite_pragmas(engine: Engine) -> None:
        @event.listens_for(engine, "connect")
        def configure_sqlite_connection(
            dbapi_connection: sqlite3.Connection, _connection_record: object
        ) -> None:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=5000")
            finally:
                cursor.close()

    @staticmethod
    def _upgrade(engine: Engine) -> None:
        backend_root = Path(__file__).resolve().parents[1]
        config = Config(str(backend_root / "alembic.ini"))
        config.set_main_option("script_location", str(backend_root / "migrations"))
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
