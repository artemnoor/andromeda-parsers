from __future__ import annotations

import logging

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


logger = logging.getLogger("andromeda.infrastructure.database")


def create_engine_for_url(
    database_url: str,
    *,
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_timeout: int = 30,
    pool_recycle: int = 1800,
) -> Engine:
    dialect = make_url(database_url).get_backend_name()
    connect_args = {"check_same_thread": False} if dialect == "sqlite" else {}
    engine_options: dict[str, object] = {"future": True, "connect_args": connect_args}
    if dialect != "sqlite":
        engine_options.update(
            pool_pre_ping=True,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
            pool_recycle=pool_recycle,
        )
    engine = create_engine(database_url, **engine_options)
    if dialect == "sqlite":
        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection: object, connection_record: object) -> None:
            del connection_record
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
        logger.debug("engine_initialized dialect=sqlite foreign_keys=on")
    else:
        logger.debug(
            "engine_initialized dialect=%s pool_size=%d max_overflow=%d pool_timeout=%d pool_recycle=%d",
            dialect,
            pool_size,
            max_overflow,
            pool_timeout,
            pool_recycle,
        )
    return engine
