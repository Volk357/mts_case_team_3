"""Process-local upload metrics without document content or storage paths."""

from collections import Counter
from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True)
class UploadMetricsSnapshot:
    successful_uploads: int
    uploaded_bytes: int
    failed_uploads: int
    failures_by_reason: dict[str, int]


class UploadMetrics:
    """Thread-safe counters ready to be adapted to a production metrics backend."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._successful_uploads = 0
        self._uploaded_bytes = 0
        self._failures: Counter[str] = Counter()

    def record_success(self, size_bytes: int) -> None:
        with self._lock:
            self._successful_uploads += 1
            self._uploaded_bytes += size_bytes

    def record_failure(self, reason: str) -> None:
        with self._lock:
            self._failures[reason] += 1

    def snapshot(self) -> UploadMetricsSnapshot:
        with self._lock:
            failures = dict(self._failures)
            return UploadMetricsSnapshot(
                successful_uploads=self._successful_uploads,
                uploaded_bytes=self._uploaded_bytes,
                failed_uploads=sum(failures.values()),
                failures_by_reason=failures,
            )


upload_metrics = UploadMetrics()


def get_upload_metrics() -> UploadMetrics:
    """Return the process-local recorder for dependency injection."""

    return upload_metrics
