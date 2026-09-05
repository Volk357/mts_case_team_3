"""Service health endpoint."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from docreview_api import __version__
from docreview_api.api.schemas.system import HealthResponse
from docreview_api.config import Settings, get_settings
from docreview_api.db.dependencies import get_session_factory
from docreview_api.db.models import ReviewJobModel

router = APIRouter(tags=["system"])


def _database_check(session_factory: sessionmaker[Session]) -> str:
    """Читает из базы, а не пингует соединение: пул может отдать живой
    сокет к базе, в которой нет схемы."""

    try:
        with session_factory() as session:
            session.execute(select(ReviewJobModel.id).limit(1)).first()
    except Exception:  # наружу идёт только статус, без деталей
        return "failed"
    return "ok"


def _worker_check(settings: Settings) -> str:
    """Жив ли воркер — по его собственной отметке, а не по длине очереди.

    Очередь живость не показывает: при пустой очереди остановившийся воркер
    неотличим от простаивающего, а это ровно предполётный сценарий перед
    демонстрацией. Воркер отмечается на каждом цикле опроса, поэтому свежесть
    отметки — прямой признак того, что процесс крутится.
    """

    path = settings.worker_heartbeat_path
    try:
        stamp = datetime.fromisoformat(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return "failed"
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    # Воркер отмечается не реже, чем раз в 5 секунд (и чаще, если опрос
    # частый), независимо от того, занят он анализом или ждёт задачу.
    heartbeat_interval = max(0.1, min(settings.worker_poll_interval_seconds, 5.0))
    tolerance = timedelta(seconds=heartbeat_interval * settings.worker_heartbeat_tolerance)
    return "ok" if datetime.now(UTC) - stamp <= tolerance else "failed"


@router.get("/health", response_model=HealthResponse)
def health(
    settings: Annotated[Settings, Depends(get_settings)],
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> HealthResponse:
    """Report whether the service can actually serve a review right now."""

    checks = {
        "database": _database_check(session_factory),
        "worker": _worker_check(settings),
    }
    return HealthResponse(
        status="ok" if all(value == "ok" for value in checks.values()) else "degraded",
        service=settings.app_name,
        environment=settings.environment,
        version=__version__,
        checks=checks,
    )
