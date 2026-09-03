"""FastAPI dependencies for database access."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session, sessionmaker

from docreview_api.config import Settings, get_settings
from docreview_api.db.session import create_database_engine, create_session_factory


@lru_cache(maxsize=8)
def _session_factory_for_url(database_url: str) -> sessionmaker[Session]:
    engine = create_database_engine(database_url)
    return create_session_factory(engine)


def get_session_factory(
    settings: Annotated[Settings, Depends(get_settings)],
) -> sessionmaker[Session]:
    """Reuse one engine/session factory for each configured database URL."""

    return _session_factory_for_url(settings.database_url)
