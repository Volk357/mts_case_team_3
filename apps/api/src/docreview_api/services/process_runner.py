"""Safe asynchronous process execution for the Analysis Core CLI."""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from docreview_api.services.run_workspace import RunWorkspace

READ_CHUNK_SIZE = 64 * 1024
ENVIRONMENT_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SECRET_KEY_PATTERN = re.compile(r"(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.IGNORECASE)
SAFE_PARENT_ENVIRONMENT_KEYS = (
    "COMSPEC",
    "LANG",
    "LC_ALL",
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "WINDIR",
)


class ProcessRunnerError(ValueError):
    """The requested process execution is unsafe or invalid."""


class AnalysisProcessTimeoutError(TimeoutError):
    """The child process did not exit within its overall execution timeout."""


@dataclass(frozen=True, slots=True)
class AnalysisProcessRequest:
    """Validated inputs needed to construct one `docreview analyze` command."""

    run_id: str
    document_path: Path
    review_pack_path: Path
    workspace: RunWorkspace
    model_config_path: Path | None = None
    include_rejected: bool = False


@dataclass(frozen=True, slots=True)
class CapturedProcessStream:
    """Bounded raw process output with an explicit truncation marker."""

    content: bytes
    truncated: bool

    def utf8(self) -> str:
        return self.content.decode("utf-8", errors="replace")


@dataclass(frozen=True, slots=True)
class ProcessExecutionResult:
    """Completed process metadata without command arguments or environment values."""

    pid: int
    started_at: datetime
    finished_at: datetime
    exit_code: int
    stdout: CapturedProcessStream
    stderr: CapturedProcessStream


class RunningAnalysisProcess:
    """A started child process whose streams are drained independently."""

    def __init__(
        self,
        process: asyncio.subprocess.Process,
        *,
        started_at: datetime,
        stdout_task: asyncio.Task[CapturedProcessStream],
        stderr_task: asyncio.Task[CapturedProcessStream],
        clock: Callable[[], datetime],
    ) -> None:
        self._process = process
        self._started_at = started_at
        self._stdout_task = stdout_task
        self._stderr_task = stderr_task
        self._clock = clock
        self._wait_lock = asyncio.Lock()
        self._result: ProcessExecutionResult | None = None

    @property
    def pid(self) -> int:
        return self._process.pid

    @property
    def started_at(self) -> datetime:
        return self._started_at

    @property
    def is_running(self) -> bool:
        return self._process.returncode is None

    async def wait(self, *, timeout_seconds: float | None = None) -> ProcessExecutionResult:
        """Wait for exit, optionally leaving the process alive when time expires."""

        if timeout_seconds is not None and timeout_seconds <= 0:
            raise ProcessRunnerError("process timeout must be positive")
        async with self._wait_lock:
            if self._result is not None:
                return self._result
            try:
                if timeout_seconds is None:
                    exit_code = await self._process.wait()
                else:
                    exit_code = await asyncio.wait_for(
                        asyncio.shield(self._process.wait()), timeout=timeout_seconds
                    )
            except TimeoutError as error:
                raise AnalysisProcessTimeoutError("Analysis Core process timed out") from error

            stdout, stderr = await asyncio.gather(self._stdout_task, self._stderr_task)
            finished_at = self._clock()
            _require_utc(finished_at, "finished_at")
            self._result = ProcessExecutionResult(
                pid=self.pid,
                started_at=self.started_at,
                finished_at=finished_at,
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
            )
            return self._result

    async def terminate(self, *, grace_period_seconds: float) -> ProcessExecutionResult:
        """Request termination, then force-kill a process that ignores the grace period."""

        if grace_period_seconds < 0:
            raise ProcessRunnerError("termination grace period must not be negative")
        if self.is_running:
            with suppress(ProcessLookupError):
                self._process.terminate()
            try:
                await asyncio.wait_for(
                    asyncio.shield(self._process.wait()), timeout=grace_period_seconds
                )
            except TimeoutError:
                with suppress(ProcessLookupError):
                    self._process.kill()
                await self._process.wait()
        return await self.wait()


class ProcessRunner:
    """Build and launch Analysis Core without a shell or inherited secrets."""

    def __init__(
        self,
        command: Sequence[str | Path],
        *,
        environment: Mapping[str, str] | None = None,
        stdout_limit_bytes: int = 5 * 1024 * 1024,
        stderr_limit_bytes: int = 256 * 1024,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not command or any(not str(part) or "\x00" in str(part) for part in command):
            raise ProcessRunnerError("process command must contain safe non-empty arguments")
        if stdout_limit_bytes < 1 or stderr_limit_bytes < 1:
            raise ProcessRunnerError("process output limits must be positive")
        self._command = tuple(str(part) for part in command)
        self._environment, self._secret_values = _build_environment(environment or {})
        self._stdout_limit_bytes = stdout_limit_bytes
        self._stderr_limit_bytes = stderr_limit_bytes
        self._clock = clock or _utc_now

    def build_arguments(self, request: AnalysisProcessRequest) -> tuple[str, ...]:
        """Return argv as distinct values; no quoting or shell interpolation is used."""

        if request.run_id != request.workspace.run_id:
            raise ProcessRunnerError("request run_id does not match its workspace")
        document_path = request.document_path.resolve()
        if not document_path.is_file() or not document_path.is_relative_to(
            request.workspace.input_dir
        ):
            raise ProcessRunnerError("document must be a file inside workspace/input")
        review_pack_path = request.review_pack_path.resolve()
        if not review_pack_path.exists():
            raise ProcessRunnerError("Review Pack path is unavailable")

        output_path = request.workspace.resolve("output/result.json")
        artifacts_path = request.workspace.resolve("artifacts")
        arguments = [
            *self._command,
            "analyze",
            "--file",
            str(document_path),
            "--pack",
            str(review_pack_path),
            "--run-id",
            request.run_id,
            "--output",
            str(output_path),
            "--artifacts-dir",
            str(artifacts_path),
        ]
        if request.model_config_path is not None:
            model_config_path = request.model_config_path.resolve()
            if not model_config_path.is_file():
                raise ProcessRunnerError("model configuration path is unavailable")
            arguments.extend(("--model-config", str(model_config_path)))
        if request.include_rejected:
            arguments.append("--include-rejected")
        return tuple(arguments)

    async def start(self, request: AnalysisProcessRequest) -> RunningAnalysisProcess:
        """Start a child and immediately begin draining stdout and stderr."""

        arguments = self.build_arguments(request)
        process = await asyncio.create_subprocess_exec(
            *arguments,
            cwd=request.workspace.root,
            env=self._environment,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        started_at = self._clock()
        try:
            _require_utc(started_at, "started_at")
        except BaseException:
            process.kill()
            await process.wait()
            raise
        if process.stdout is None or process.stderr is None:  # pragma: no cover - asyncio invariant
            process.kill()
            await process.wait()
            raise RuntimeError("process pipes were not created")
        stdout_task = asyncio.create_task(
            _read_limited(process.stdout, self._stdout_limit_bytes, self._secret_values)
        )
        stderr_task = asyncio.create_task(
            _read_limited(process.stderr, self._stderr_limit_bytes, self._secret_values)
        )
        return RunningAnalysisProcess(
            process,
            started_at=started_at,
            stdout_task=stdout_task,
            stderr_task=stderr_task,
            clock=self._clock,
        )


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _require_utc(value: datetime, field_name: str) -> None:
    if value.utcoffset() != timedelta(0):
        raise ProcessRunnerError(f"{field_name} must be a timezone-aware UTC datetime")


def _build_environment(explicit: Mapping[str, str]) -> tuple[dict[str, str], tuple[bytes, ...]]:
    environment = {
        key: value
        for key in SAFE_PARENT_ENVIRONMENT_KEYS
        if (value := os.environ.get(key)) is not None
    }
    secret_values: list[bytes] = []
    for key, value in explicit.items():
        if (
            not isinstance(key, str)
            or not isinstance(value, str)
            or ENVIRONMENT_KEY_PATTERN.fullmatch(key) is None
            or "\x00" in value
        ):
            raise ProcessRunnerError("process environment contains an invalid entry")
        environment[key] = value
        if value and SECRET_KEY_PATTERN.search(key):
            secret_values.append(value.encode("utf-8"))
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONUTF8"] = "1"
    return environment, tuple(sorted(set(secret_values), key=len, reverse=True))


async def _read_limited(
    stream: asyncio.StreamReader, limit: int, secret_values: tuple[bytes, ...]
) -> CapturedProcessStream:
    captured = bytearray()
    total_bytes = 0
    redaction_margin = max((len(secret) for secret in secret_values), default=0)
    capture_limit = limit + redaction_margin
    while chunk := await stream.read(READ_CHUNK_SIZE):
        total_bytes += len(chunk)
        remaining = capture_limit - len(captured)
        if remaining > 0:
            captured.extend(chunk[:remaining])
    content = bytes(captured)
    for secret in secret_values:
        content = content.replace(secret, b"[REDACTED]")
    return CapturedProcessStream(content=content[:limit], truncated=total_bytes > limit)
