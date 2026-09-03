from datetime import UTC, datetime, timedelta

import pytest

from docreview_api.models import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATUSES,
    InvalidReviewJobState,
    InvalidReviewJobTransition,
    ReviewJobFailure,
    ReviewJobLifecycle,
    ReviewJobStatus,
)

CREATED_AT = datetime(2026, 9, 3, 9, 0, tzinfo=UTC)
FAILURE = ReviewJobFailure(
    error_code="MODEL_UNAVAILABLE",
    user_message="Сервис анализа временно недоступен.",
    diagnostic_message="connection refused: private model endpoint",
    retriable=True,
)


def running_job() -> ReviewJobLifecycle:
    return ReviewJobLifecycle.queued(CREATED_AT).transition_to(
        ReviewJobStatus.RUNNING,
        at=CREATED_AT + timedelta(seconds=1),
    )


def terminal_job(status: ReviewJobStatus) -> ReviewJobLifecycle:
    running = running_job()
    failure = FAILURE if status is not ReviewJobStatus.COMPLETED else None
    return running.transition_to(
        status,
        at=CREATED_AT + timedelta(seconds=2),
        failure=failure,
    )


def test_state_machine_declares_only_expected_transitions() -> None:
    assert {
        ReviewJobStatus.QUEUED: {
            ReviewJobStatus.RUNNING,
            ReviewJobStatus.CANCELLED,
        },
        ReviewJobStatus.RUNNING: {
            ReviewJobStatus.COMPLETED,
            ReviewJobStatus.FAILED,
            ReviewJobStatus.TIMED_OUT,
            ReviewJobStatus.CANCELLED,
        },
        ReviewJobStatus.COMPLETED: set(),
        ReviewJobStatus.FAILED: set(),
        ReviewJobStatus.TIMED_OUT: set(),
        ReviewJobStatus.CANCELLED: set(),
    } == ALLOWED_TRANSITIONS


def test_queued_and_running_timestamps_are_preserved() -> None:
    queued = ReviewJobLifecycle.queued(CREATED_AT)
    started_at = CREATED_AT + timedelta(seconds=3)
    running = queued.transition_to(ReviewJobStatus.RUNNING, at=started_at)

    assert queued.status is ReviewJobStatus.QUEUED
    assert queued.queued_at == CREATED_AT
    assert queued.updated_at == CREATED_AT
    assert queued.started_at is None
    assert queued.finished_at is None
    assert running.status is ReviewJobStatus.RUNNING
    assert running.queued_at == CREATED_AT
    assert running.started_at == started_at
    assert running.updated_at == started_at
    assert running.finished_at is None


@pytest.mark.parametrize("status", sorted(TERMINAL_STATUSES, key=str))
def test_each_terminal_status_records_its_own_timestamp(status: ReviewJobStatus) -> None:
    terminal = terminal_job(status)
    expected = CREATED_AT + timedelta(seconds=2)

    assert terminal.status is status
    assert terminal.finished_at == expected
    assert terminal.updated_at == expected
    assert terminal.completed_at == (expected if status is ReviewJobStatus.COMPLETED else None)
    assert terminal.failed_at == (expected if status is ReviewJobStatus.FAILED else None)
    assert terminal.timed_out_at == (expected if status is ReviewJobStatus.TIMED_OUT else None)
    assert terminal.cancelled_at == (expected if status is ReviewJobStatus.CANCELLED else None)


def test_queued_job_can_be_cancelled_before_start() -> None:
    cancelled = ReviewJobLifecycle.queued(CREATED_AT).transition_to(
        ReviewJobStatus.CANCELLED,
        at=CREATED_AT + timedelta(seconds=1),
        failure=ReviewJobFailure(
            error_code="ANALYSIS_CANCELLED",
            user_message="Проверка отменена.",
        ),
    )

    assert cancelled.started_at is None
    assert cancelled.finished_at == CREATED_AT + timedelta(seconds=1)


@pytest.mark.parametrize("status", sorted(TERMINAL_STATUSES, key=str))
def test_terminal_job_cannot_be_reopened_or_retried_in_place(status: ReviewJobStatus) -> None:
    terminal = terminal_job(status)

    for target in ReviewJobStatus:
        with pytest.raises(InvalidReviewJobTransition):
            terminal.transition_to(target, at=CREATED_AT + timedelta(seconds=3))


def test_repeat_is_a_new_queued_lifecycle() -> None:
    failed = terminal_job(ReviewJobStatus.FAILED)
    retry_created_at = CREATED_AT + timedelta(minutes=1)

    with pytest.raises(InvalidReviewJobTransition):
        failed.transition_to(ReviewJobStatus.QUEUED, at=retry_created_at)

    retry = ReviewJobLifecycle.queued(retry_created_at)
    assert retry.status is ReviewJobStatus.QUEUED
    assert retry.queued_at != failed.queued_at


def test_failure_keeps_machine_user_and_diagnostic_information_separate() -> None:
    failed = terminal_job(ReviewJobStatus.FAILED)

    assert failed.failure is not None
    assert failed.failure.error_code == "MODEL_UNAVAILABLE"
    assert failed.failure.user_message == "Сервис анализа временно недоступен."
    assert failed.failure.diagnostic_message == "connection refused: private model endpoint"
    assert failed.failure.retriable is True


def test_failure_details_are_required_only_for_unsuccessful_terminal_states() -> None:
    running = running_job()
    finished_at = CREATED_AT + timedelta(seconds=2)

    with pytest.raises(InvalidReviewJobState, match="requires failure"):
        running.transition_to(ReviewJobStatus.FAILED, at=finished_at)
    with pytest.raises(InvalidReviewJobState, match="cannot include failure"):
        running.transition_to(ReviewJobStatus.COMPLETED, at=finished_at, failure=FAILURE)


@pytest.mark.parametrize("error_code", ["", "model_unavailable", "HAS-DASH", "1INVALID"])
def test_error_code_must_be_a_stable_machine_code(error_code: str) -> None:
    with pytest.raises(InvalidReviewJobState, match="error_code"):
        ReviewJobFailure(error_code=error_code, user_message="Понятное сообщение")


def test_user_message_must_not_be_empty() -> None:
    with pytest.raises(InvalidReviewJobState, match="user_message"):
        ReviewJobFailure(error_code="INTERNAL_ERROR", user_message="  ")


def test_transition_timestamps_must_be_monotonic_utc() -> None:
    queued = ReviewJobLifecycle.queued(CREATED_AT)

    with pytest.raises(InvalidReviewJobState, match="timezone-aware UTC"):
        queued.transition_to(ReviewJobStatus.RUNNING, at=datetime(2026, 9, 3, 10, 0))
    with pytest.raises(InvalidReviewJobState, match="move backwards"):
        queued.transition_to(
            ReviewJobStatus.RUNNING,
            at=CREATED_AT - timedelta(microseconds=1),
        )


def test_direct_construction_rejects_inconsistent_state() -> None:
    with pytest.raises(InvalidReviewJobState, match="must have started_at"):
        ReviewJobLifecycle(
            status=ReviewJobStatus.RUNNING,
            queued_at=CREATED_AT,
            updated_at=CREATED_AT,
        )
    with pytest.raises(InvalidReviewJobState, match="terminal timestamp"):
        ReviewJobLifecycle(
            status=ReviewJobStatus.COMPLETED,
            queued_at=CREATED_AT,
            updated_at=CREATED_AT + timedelta(seconds=1),
            started_at=CREATED_AT,
        )
