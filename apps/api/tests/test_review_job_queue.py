from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from docreview_api.db import Base, create_database_engine, create_session_factory
from docreview_api.db.models import (
    CompanyModel,
    DocumentModel,
    ReviewJobModel,
    ReviewPackReferenceModel,
)
from docreview_api.models.review_job_state import ReviewJobStatus
from docreview_api.services.review_job_queue import DatabaseReviewJobQueue

NOW = datetime(2026, 9, 3, 18, 0, tzinfo=UTC)


def make_sessions(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_database_engine(f"sqlite:///{(tmp_path / 'queue.db').as_posix()}")
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


def seed_jobs(
    sessions: sessionmaker[Session],
    statuses: list[ReviewJobStatus],
) -> list[ReviewJobModel]:
    company_id = uuid4()
    document_id = uuid4()
    pack_id = uuid4()
    jobs: list[ReviewJobModel] = []
    with sessions.begin() as session:
        session.add(CompanyModel(id=company_id, slug=company_id.hex, display_name="Company"))
        session.add(
            DocumentModel(
                id=document_id,
                company_id=company_id,
                original_filename="document.pdf",
                media_type="application/pdf",
                size_bytes=4,
                sha256="a" * 64,
                storage_key="document.pdf",
            )
        )
        session.add(
            ReviewPackReferenceModel(
                id=pack_id,
                company_id=company_id,
                pack_key="requirements",
                version="mock-1.0",
                display_name="Requirements",
                locator="requirements",
            )
        )
        for index, status in enumerate(statuses):
            queued_at = NOW + timedelta(seconds=index)
            job = ReviewJobModel(
                run_id=f"queue-{index}-{uuid4().hex}",
                company_id=company_id,
                document_id=document_id,
                review_pack_reference_id=pack_id,
                status=status,
                queued_at=queued_at,
                started_at=queued_at if status is ReviewJobStatus.RUNNING else None,
                created_at=queued_at,
                updated_at=queued_at,
            )
            session.add(job)
            jobs.append(job)
    return jobs


def test_claim_is_fifo_and_persisted(tmp_path: Path) -> None:
    sessions = make_sessions(tmp_path)
    jobs = seed_jobs(sessions, [ReviewJobStatus.QUEUED, ReviewJobStatus.QUEUED])
    queue = DatabaseReviewJobQueue(sessions, clock=lambda: NOW + timedelta(minutes=1))

    first = queue.claim_next()
    second = queue.claim_next()

    assert first is not None and first.id == jobs[0].id
    assert second is not None and second.id == jobs[1].id
    assert queue.claim_next() is None
    with sessions() as session:
        assert session.get(ReviewJobModel, first.id).status is ReviewJobStatus.RUNNING  # type: ignore[union-attr]


def test_two_workers_never_claim_the_same_job(tmp_path: Path) -> None:
    sessions = make_sessions(tmp_path)
    job = seed_jobs(sessions, [ReviewJobStatus.QUEUED])[0]
    barrier = Barrier(2)

    def claim() -> object:
        barrier.wait()
        return DatabaseReviewJobQueue(
            sessions, clock=lambda: NOW + timedelta(minutes=1)
        ).claim_next()

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: claim(), range(2)))

    claimed_ids = [claim_result.id for claim_result in claims if claim_result is not None]
    assert claimed_ids == [job.id]


def test_restart_recovery_fails_only_stale_running_jobs(tmp_path: Path) -> None:
    sessions = make_sessions(tmp_path)
    stale, fresh, queued = seed_jobs(
        sessions,
        [ReviewJobStatus.RUNNING, ReviewJobStatus.RUNNING, ReviewJobStatus.QUEUED],
    )
    with sessions.begin() as session:
        persisted_fresh = session.get(ReviewJobModel, fresh.id)
        assert persisted_fresh is not None
        persisted_fresh.started_at = NOW + timedelta(minutes=9)
        persisted_fresh.updated_at = NOW + timedelta(minutes=9)

    queue = DatabaseReviewJobQueue(sessions, clock=lambda: NOW + timedelta(minutes=10))
    recovered = queue.recover_stale(stale_after=timedelta(minutes=5))

    assert recovered == (stale.id,)
    with sessions() as session:
        stale_state = session.get(ReviewJobModel, stale.id)
        fresh_state = session.get(ReviewJobModel, fresh.id)
        queued_state = session.get(ReviewJobModel, queued.id)
        assert stale_state is not None and stale_state.status is ReviewJobStatus.FAILED
        assert stale_state.error_code == "WORKER_INTERRUPTED"
        assert stale_state.error_retriable is True
        assert fresh_state is not None and fresh_state.status is ReviewJobStatus.RUNNING
        assert queued_state is not None and queued_state.status is ReviewJobStatus.QUEUED


def test_database_contains_one_running_claim_after_concurrency(tmp_path: Path) -> None:
    sessions = make_sessions(tmp_path)
    seed_jobs(sessions, [ReviewJobStatus.QUEUED])
    queue = DatabaseReviewJobQueue(sessions, clock=lambda: NOW + timedelta(minutes=1))
    queue.claim_next()

    with sessions() as session:
        running = session.scalars(
            select(ReviewJobModel).where(ReviewJobModel.status == ReviewJobStatus.RUNNING)
        ).all()
        assert len(running) == 1
