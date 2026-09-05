"""Database engine and session factory construction."""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def create_database_engine(database_url: str, *, echo: bool = False) -> Engine:
    """Create a configured SQLAlchemy engine without creating the schema.

    Только PostgreSQL (см. Settings.validate_database_url). Отдельных обходных
    путей под другую СУБД здесь нет намеренно: блокировка строки в удалении
    документа и `SELECT ... FOR UPDATE` при постановке проверки — настоящие,
    а не эмулированные сериализацией всех писателей.

    `pool_pre_ping` отсеивает соединения, разорванные простоем или перезапуском
    сервера: без него первый запрос после паузы падал бы на мёртвом соединении.
    """

    return create_engine(database_url, echo=echo, pool_pre_ping=True)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return sessions with explicit transaction boundaries and usable results."""

    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
