"""Domain vocabulary for analyst decisions on findings."""

from enum import StrEnum


class FeedbackDecision(StrEnum):
    """Closed decision set used for quality evaluation."""

    ACCEPTED = "accepted"
    FALSE_POSITIVE = "false_positive"
    ALLOWED_EXCEPTION = "allowed_exception"
    ALREADY_DESCRIBED = "already_described"
    NOT_RELEVANT = "not_relevant"
