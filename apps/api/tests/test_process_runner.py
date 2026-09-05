import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from docreview_api.services import (
    AnalysisProcessRequest,
    AnalysisProcessTimeoutError,
    ProcessRunner,
    ProcessRunnerError,
    RunWorkspaceManager,
)

STARTED_AT = datetime(2026, 9, 3, 16, 0, tzinfo=UTC)


def mock_executable() -> Path:
    executable_name = "docreview-mock.exe" if sys.platform == "win32" else "docreview-mock"
    return Path(sys.executable).parent / executable_name


def prepare_request(tmp_path: Path, *, run_id: str = "review-process") -> AnalysisProcessRequest:
    workspace = RunWorkspaceManager(tmp_path / "runs").prepare(run_id)
    document = workspace.resolve("input/requirements;literal.pdf")
    document.write_bytes(b"%PDF-1.7\nprocess runner test")
    review_pack = tmp_path / "review-packs" / "requirements"
    review_pack.mkdir(parents=True)
    return AnalysisProcessRequest(
        run_id=run_id,
        document_path=document,
        review_pack_path=review_pack,
        workspace=workspace,
    )


@pytest.mark.anyio
async def test_runner_executes_mock_without_shell_and_keeps_streams_separate(
    tmp_path: Path,
) -> None:
    request = prepare_request(tmp_path)
    runner = ProcessRunner((mock_executable(),))

    arguments = runner.build_arguments(request)
    assert arguments[0] == str(mock_executable())
    assert arguments[arguments.index("--file") + 1] == str(request.document_path.resolve())
    assert ";literal.pdf" in arguments[arguments.index("--file") + 1]

    running = await runner.start(request)
    result = await running.wait()

    assert result.pid == running.pid > 0
    assert result.started_at.tzinfo is UTC
    assert result.exit_code == 0
    payload = json.loads(result.stdout.utf8())
    assert payload["run_id"] == request.run_id
    assert "mock analysis completed" in result.stderr.utf8()
    assert "mock analysis completed" not in result.stdout.utf8()
    assert request.workspace.resolve("output/result.json").is_file()


@pytest.mark.anyio
async def test_runner_uses_allowlisted_environment_redacts_secrets_and_limits_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = prepare_request(tmp_path, run_id="review-bounded")
    script = tmp_path / "fake_core.py"
    script.write_text(
        "import os, sys\n"
        "visible = os.getenv('VISIBLE_SETTING', 'missing')\n"
        "secret = os.getenv('MODEL_API_KEY', 'missing')\n"
        "inherited = os.getenv('UNRELATED_SECRET', 'missing')\n"
        "sys.stdout.write(f'{visible}|{secret}|{inherited}|' + 'o' * 200)\n"
        "sys.stderr.write(f'{secret}|' + 'e' * 200)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("UNRELATED_SECRET", "must-not-be-inherited")
    runner = ProcessRunner(
        (sys.executable, script),
        environment={"VISIBLE_SETTING": "visible", "MODEL_API_KEY": "top-secret-value"},
        stdout_limit_bytes=64,
        stderr_limit_bytes=32,
    )

    result = await (await runner.start(request)).wait()

    assert result.exit_code == 0
    assert len(result.stdout.content) == 64
    assert len(result.stderr.content) == 32
    assert result.stdout.truncated
    assert result.stderr.truncated
    assert b"top-secret-value" not in result.stdout.content + result.stderr.content
    assert b"[REDACTED]" in result.stdout.content + result.stderr.content
    assert b"visible" in result.stdout.content
    assert b"must-not-be-inherited" not in result.stdout.content
    assert b"missing" in result.stdout.content


@pytest.mark.anyio
async def test_runner_records_stable_start_and_finish_times(tmp_path: Path) -> None:
    request = prepare_request(tmp_path, run_id="review-clock")
    times = iter((STARTED_AT, STARTED_AT + timedelta(seconds=2)))
    runner = ProcessRunner((mock_executable(),), clock=lambda: next(times))

    result = await (await runner.start(request)).wait()

    assert result.started_at == STARTED_AT
    assert result.finished_at == STARTED_AT + timedelta(seconds=2)


def test_runner_rejects_invalid_inputs_before_start(tmp_path: Path) -> None:
    request = prepare_request(tmp_path)

    with pytest.raises(ProcessRunnerError, match="command"):
        ProcessRunner(())
    with pytest.raises(ProcessRunnerError, match="limits"):
        ProcessRunner((mock_executable(),), stdout_limit_bytes=0)
    with pytest.raises(ProcessRunnerError, match="environment"):
        ProcessRunner((mock_executable(),), environment={"BAD-NAME": "value"})

    mismatched = AnalysisProcessRequest(
        run_id="other-run",
        document_path=request.document_path,
        review_pack_path=request.review_pack_path,
        workspace=request.workspace,
    )
    with pytest.raises(ProcessRunnerError, match="run_id"):
        ProcessRunner((mock_executable(),)).build_arguments(mismatched)


def test_runner_requires_document_inside_workspace_and_existing_pack(tmp_path: Path) -> None:
    request = prepare_request(tmp_path)
    outside_document = tmp_path / "outside.pdf"
    outside_document.write_bytes(b"%PDF-1.7")
    runner = ProcessRunner((mock_executable(),))

    with pytest.raises(ProcessRunnerError, match="workspace/input"):
        runner.build_arguments(
            AnalysisProcessRequest(
                run_id=request.run_id,
                document_path=outside_document,
                review_pack_path=request.review_pack_path,
                workspace=request.workspace,
            )
        )
    with pytest.raises(ProcessRunnerError, match="Review Pack"):
        runner.build_arguments(
            AnalysisProcessRequest(
                run_id=request.run_id,
                document_path=request.document_path,
                review_pack_path=tmp_path / "missing-pack",
                workspace=request.workspace,
            )
        )


@pytest.mark.anyio
async def test_wait_timeout_leaves_process_for_explicit_controlled_termination(
    tmp_path: Path,
) -> None:
    request = prepare_request(tmp_path, run_id="review-explicit-timeout")
    script = tmp_path / "slow.py"
    script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    process = await ProcessRunner((sys.executable, script)).start(request)

    with pytest.raises(AnalysisProcessTimeoutError):
        await process.wait(timeout_seconds=0.02)
    assert process.is_running

    result = await process.terminate(grace_period_seconds=0.1)
    assert not process.is_running
    assert result.pid == process.pid
