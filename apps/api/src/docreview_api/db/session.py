"""Database engine and session factory construction."""

from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool


def _ensure_sqlite_directory(database_url: str) -> None:
    url = make_url(database_url)
    database = url.database
    if url.get_backend_name() != "sqlite" or database in {None, ":memory:"}:
        return
    if database is None:  # pragma: no cover - narrowed by the condition above
        return
    Path(database).parent.mkdir(parents=True, exist_ok=True)


def create_database_engine(database_url: str, *, echo: bool = False) -> Engine:
    """Create a configured SQLAlchemy engine without creating the schema."""

    _ensure_sqlite_directory(database_url)
    if make_url(database_url).get_backend_name() == "sqlite":
        engine = create_engine(database_url, echo=echo, poolclass=NullPool)
    else:
        engine = create_engine(database_url, echo=echo)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def enable_sqlite_foreign_keys(dbapi_connection: object, _: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return sessions with explicit transaction boundaries and usable results."""

    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
