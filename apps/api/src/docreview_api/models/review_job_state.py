"""Review job lifecycle rules independent from HTTP and persistence layers."""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


class ReviewJobStatus(StrEnum):
    """Persisted states of one immutable review attempt."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = frozenset(
    {
        ReviewJobStatus.COMPLETED,
        ReviewJobStatus.FAILED,
        ReviewJobStatus.TIMED_OUT,
        ReviewJobStatus.CANCELLED,
    }
)
FAILED_STATUSES = frozenset(
    {
        ReviewJobStatus.FAILED,
        ReviewJobStatus.TIMED_OUT,
        ReviewJobStatus.CANCELLED,
    }
)
ALLOWED_TRANSITIONS = {
    ReviewJobStatus.QUEUED: frozenset({ReviewJobStatus.RUNNING, ReviewJobStatus.CANCELLED}),
    ReviewJobStatus.RUNNING: frozenset(
        {
            ReviewJobStatus.COMPLETED,
            ReviewJobStatus.FAILED,
            ReviewJobStatus.TIMED_OUT,
            ReviewJobStatus.CANCELLED,
        }
    ),
    ReviewJobStatus.COMPLETED: frozenset(),
    ReviewJobStatus.FAILED: frozenset(),
    ReviewJobStatus.TIMED_OUT: frozenset(),
    ReviewJobStatus.CANCELLED: frozenset(),
}

_ERROR_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
_TERMINAL_TIMESTAMP_FIELD = {
    ReviewJobStatus.COMPLETED: "completed_at",
    ReviewJobStatus.FAILED: "failed_at",
    ReviewJobStatus.TIMED_OUT: "timed_out_at",
    ReviewJobStatus.CANCELLED: "cancelled_at",
}


class InvalidReviewJobTransition(ValueError):
    """Raised when a requested lifecycle transition is forbidden."""


class InvalidReviewJobState(ValueError):
    """Raised when lifecycle data violates timestamp or error invariants."""


def _require_utc(value: datetime, field_name: str) -> None:
    offset = value.utcoffset()
    if offset is None or offset != timedelta(0):
        raise InvalidReviewJobState(f"{field_name} must be a timezone-aware UTC datetime")


@dataclass(frozen=True)
class ReviewJobFailure:
    """Separated machine, user-facing, and internal failure information."""

    error_code: str
    user_message: str
    diagnostic_message: str | None = None
    retriable: bool = False

    def __post_init__(self) -> None:
        if not _ERROR_CODE_PATTERN.fullmatch(self.error_code):
            raise InvalidReviewJobState("error_code must be an uppercase machine code")
        if not self.user_message.strip():
            raise InvalidReviewJobState("user_message must not be empty")


@dataclass(frozen=True)
class ReviewJobLifecycle:
    """Immutable lifecycle snapshot; transitions return a new snapshot."""

    status: ReviewJobStatus
    queued_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failed_at: datetime | None = None
    timed_out_at: datetime | None = None
    cancelled_at: datetime | None = None
    failure: ReviewJobFailure | None = None

    def __post_init__(self) -> None:
        timestamps = {
            "queued_at": self.queued_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "failed_at": self.failed_at,
            "timed_out_at": self.timed_out_at,
            "cancelled_at": self.cancelled_at,
        }
        for field_name, value in timestamps.items():
            if value is not None:
                _require_utc(value, field_name)
                if value < self.queued_at:
                    raise InvalidReviewJobState(f"{field_name} cannot precede queued_at")
                if value > self.updated_at:
                    raise InvalidReviewJobState(f"{field_name} cannot follow updated_at")

        if self.status is ReviewJobStatus.QUEUED and self.started_at is not None:
            raise InvalidReviewJobState("queued job cannot have started_at")
        if (
            self.status not in {ReviewJobStatus.QUEUED, ReviewJobStatus.CANCELLED}
            and self.started_at is None
        ):
            raise InvalidReviewJobState(f"{self.status} job must have started_at")

        populated_terminal_fields = {
            field_name
            for field_name in _TERMINAL_TIMESTAMP_FIELD.values()
            if getattr(self, field_name) is not None
        }
        expected_terminal_field = _TERMINAL_TIMESTAMP_FIELD.get(self.status)
        expected_fields = set() if expected_terminal_field is None else {expected_terminal_field}
        if populated_terminal_fields != expected_fields:
            raise InvalidReviewJobState("terminal timestamp must match current status")

        if self.status in FAILED_STATUSES and self.failure is None:
            raise InvalidReviewJobState(f"{self.status} job must have failure details")
        if self.status not in FAILED_STATUSES and self.failure is not None:
            raise InvalidReviewJobState(f"{self.status} job cannot have failure details")

    @classmethod
    def queued(cls, at: datetime) -> "ReviewJobLifecycle":
        """Create the initial state of a new job."""

        return cls(status=ReviewJobStatus.QUEUED, queued_at=at, updated_at=at)

    @property
    def finished_at(self) -> datetime | None:
        """Return the timestamp of the current terminal state, if any."""

        terminal_field = _TERMINAL_TIMESTAMP_FIELD.get(self.status)
        return None if terminal_field is None else getattr(self, terminal_field)

    def transition_to(
        self,
        target: ReviewJobStatus,
        *,
        at: datetime,
        failure: ReviewJobFailure | None = None,
    ) -> "ReviewJobLifecycle":
        """Return the next valid state or reject the transition."""

        if target not in ALLOWED_TRANSITIONS[self.status]:
            raise InvalidReviewJobTransition(f"cannot transition from {self.status} to {target}")
        _require_utc(at, "transition timestamp")
        if at < self.updated_at:
            raise InvalidReviewJobState("transition timestamp cannot move backwards")
        if target in FAILED_STATUSES and failure is None:
            raise InvalidReviewJobState(f"transition to {target} requires failure details")
        if target not in FAILED_STATUSES and failure is not None:
            raise InvalidReviewJobState(f"transition to {target} cannot include failure details")

        return ReviewJobLifecycle(
            status=target,
            queued_at=self.queued_at,
            updated_at=at,
            started_at=at if target is ReviewJobStatus.RUNNING else self.started_at,
            completed_at=at if target is ReviewJobStatus.COMPLETED else None,
            failed_at=at if target is ReviewJobStatus.FAILED else None,
            timed_out_at=at if target is ReviewJobStatus.TIMED_OUT else None,
            cancelled_at=at if target is ReviewJobStatus.CANCELLED else None,
            failure=failure,
        )
