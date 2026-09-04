"""Small ASGI security controls shared by every HTTP endpoint."""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, cast
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_CORRELATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")


class RequestBodyTooLarge(Exception):
    """Raised when a streamed request crosses the configured application limit."""


def _header(scope: Scope, name: bytes) -> str | None:
    headers = cast(list[tuple[bytes, bytes]], scope.get("headers", []))
    for key, value in headers:
        if key.lower() == name:
            return value.decode("latin-1")
    return None


def _error_body(code: str, message: str) -> bytes:
    return json.dumps(
        {"error": {"code": code, "message": message, "details": []}},
        separators=(",", ":"),
    ).encode("utf-8")


async def _send_json_error(
    send: Send,
    *,
    status_code: int,
    code: str,
    message: str,
    headers: list[tuple[bytes, bytes]] | None = None,
) -> None:
    body = _error_body(code, message)
    response_headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode("ascii")),
    ]
    response_headers.extend(headers or [])
    await send({"type": "http.response.start", "status": status_code, "headers": response_headers})
    await send({"type": "http.response.body", "body": body})


class CorrelationIdMiddleware:
    """Attach a safe request identifier to state and every HTTP response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        supplied = _header(scope, b"x-correlation-id")
        correlation_id = (
            supplied if supplied and _CORRELATION_ID_PATTERN.fullmatch(supplied) else uuid4().hex
        )
        scope.setdefault("state", {})["correlation_id"] = correlation_id

        async def send_with_correlation(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).append(
                    (b"x-correlation-id", correlation_id.encode("ascii"))
                )
            await send(message)

        await self.app(scope, receive, send_with_correlation)


class RequestSizeLimitMiddleware:
    """Reject declared and streamed bodies above one global upper bound."""

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        content_length = _header(scope, b"content-length")
        if content_length is not None:
            try:
                declared_size = int(content_length)
            except ValueError:
                await _send_json_error(
                    send,
                    status_code=400,
                    code="CONTENT_LENGTH_INVALID",
                    message="Content-Length header is invalid.",
                )
                return
            if declared_size < 0:
                await _send_json_error(
                    send,
                    status_code=400,
                    code="CONTENT_LENGTH_INVALID",
                    message="Content-Length header is invalid.",
                )
                return
            if declared_size > self.max_bytes:
                await _send_json_error(
                    send,
                    status_code=413,
                    code="REQUEST_TOO_LARGE",
                    message="Request body exceeds the configured size limit.",
                )
                return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise RequestBodyTooLarge
            return message

        await self.app(scope, limited_receive, send)


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after_seconds: int


class RateLimitBackend(Protocol):
    """Replaceable backend boundary for a future Redis/distributed limiter."""

    def check(self, key: str, *, now: float) -> RateLimitDecision: ...


class InMemoryFixedWindowRateLimiter:
    """Process-local MVP limiter; safe for concurrent threads in one API process."""

    def __init__(
        self,
        *,
        requests_per_window: int,
        window_seconds: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.requests_per_window = requests_per_window
        self.window_seconds = window_seconds
        self._clock = clock
        self._buckets: dict[str, tuple[float, int]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, *, now: float | None = None) -> RateLimitDecision:
        checked_at = self._clock() if now is None else now
        with self._lock:
            window_started, count = self._buckets.get(key, (checked_at, 0))
            elapsed = checked_at - window_started
            if elapsed >= self.window_seconds or elapsed < 0:
                window_started, count = checked_at, 0
            if count >= self.requests_per_window:
                retry_after = max(1, int(self.window_seconds - elapsed + 0.999))
                return RateLimitDecision(False, 0, retry_after)
            count += 1
            self._buckets[key] = (window_started, count)
            return RateLimitDecision(True, self.requests_per_window - count, 0)


class RateLimitMiddleware:
    """Apply a replaceable limiter to API traffic, excluding browser preflight."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        requests_per_window: int,
        window_seconds: int,
        backend: RateLimitBackend | None = None,
    ) -> None:
        self.app = app
        self.requests_per_window = requests_per_window
        self.backend = backend or InMemoryFixedWindowRateLimiter(
            requests_per_window=requests_per_window,
            window_seconds=window_seconds,
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        client_host = "unknown" if client is None else str(client[0])
        decision = self.backend.check(client_host, now=time.monotonic())
        headers = [
            (b"x-ratelimit-limit", str(self.requests_per_window).encode("ascii")),
            (b"x-ratelimit-remaining", str(decision.remaining).encode("ascii")),
        ]
        if not decision.allowed:
            headers.append((b"retry-after", str(decision.retry_after_seconds).encode("ascii")))
            await _send_json_error(
                send,
                status_code=429,
                code="RATE_LIMIT_EXCEEDED",
                message="Too many requests. Try again later.",
                headers=headers,
            )
            return

        async def send_with_rate_limit(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).extend(headers)
            await send(message)

        await self.app(scope, receive, send_with_rate_limit)
