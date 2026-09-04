from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from docreview_api.config import REPOSITORY_DIRECTORY, Settings, load_settings


def test_settings_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_name == "DocReview API"
    assert settings.environment == "development"
    assert settings.api_prefix == "/api"
    assert settings.log_level == "INFO"
    assert settings.database_url.endswith("/data/docreview.db")
    assert settings.documents_dir == REPOSITORY_DIRECTORY / "data" / "documents"
    assert settings.runs_dir == REPOSITORY_DIRECTORY / "data" / "runs"
    assert settings.review_packs_dir == REPOSITORY_DIRECTORY / "review-packs"
    assert settings.analysis_executable == "docreview"
    assert settings.process_stdout_limit_bytes == 5 * 1024 * 1024
    assert settings.process_stderr_limit_bytes == 256 * 1024
    assert settings.analysis_timeout_seconds == 300.0
    assert settings.process_termination_grace_seconds == 5.0
    assert settings.worker_poll_interval_seconds == 1.0
    assert settings.worker_stale_after_seconds == 600.0
    assert settings.review_result_schema_path == (
        REPOSITORY_DIRECTORY / "contracts" / "review-result.schema.json"
    )
    assert settings.max_review_result_size_bytes == 10 * 1024 * 1024
    assert settings.max_upload_size_bytes == 50 * 1024 * 1024
    assert settings.max_request_size_bytes == 55 * 1024 * 1024
    assert settings.rate_limit_requests == 120
    assert settings.rate_limit_window_seconds == 60
    assert settings.default_company_id == UUID("00000000-0000-0000-0000-000000000001")
    assert settings.default_company_slug == "local-mvp"
    assert settings.orphan_upload_grace_period_hours == 24
    assert settings.document_retention_days == 90
    assert settings.artifact_retention_days == 14
    assert settings.automatic_retention_enabled is False


@pytest.mark.parametrize("prefix", ["api", "/v1"])
def test_invalid_api_prefix_is_rejected(prefix: str) -> None:
    try:
        Settings(api_prefix=prefix, _env_file=None)  # type: ignore[arg-type]
    except ValidationError:
        return
    raise AssertionError("Settings must reject an API prefix without a leading slash")


def test_demo_profile_is_loaded() -> None:
    settings = load_settings("demo")

    assert settings.environment == "demo"
    assert settings.app_name == "DocReview API (demo)"
    assert settings.runs_dir == REPOSITORY_DIRECTORY / "data" / "demo" / "runs"
    assert settings.database_url.endswith("/data/demo/docreview.db")
    assert settings.cors_origins == (
        "http://127.0.0.1:4173",
        "http://localhost:4173",
    )


def test_local_env_selects_profile_and_overrides_it(tmp_path: Path) -> None:
    local_env = tmp_path / ".env"
    local_env.write_text(
        "DOCREVIEW_ENVIRONMENT=demo\nDOCREVIEW_LOG_LEVEL=ERROR\n",
        encoding="utf-8",
    )

    settings = load_settings(local_env_file=local_env)

    assert settings.environment == "demo"
    assert settings.app_name == "DocReview API (demo)"
    assert settings.log_level == "ERROR"


def test_invalid_cors_origin_is_rejected() -> None:
    try:
        Settings(cors_origins=("*",), _env_file=None)
    except ValidationError:
        return
    raise AssertionError("Settings must reject wildcard and malformed CORS origins")


def test_postgresql_database_url_is_supported() -> None:
    url = "postgresql+psycopg://docreview:secret@database/docreview"

    assert Settings(database_url=url, _env_file=None).database_url == url


def test_unsupported_database_driver_is_rejected() -> None:
    try:
        Settings(database_url="mysql://database/docreview", _env_file=None)
    except ValidationError:
        return
    raise AssertionError("Settings must reject unsupported database drivers")


def test_automatic_retention_cannot_be_enabled_in_mvp() -> None:
    try:
        Settings(automatic_retention_enabled=True, _env_file=None)
    except ValidationError:
        return
    raise AssertionError("MVP settings must reject automatic retention")


def test_upload_size_limit_must_be_positive() -> None:
    try:
        Settings(max_upload_size_bytes=0, _env_file=None)
    except ValidationError:
        return
    raise AssertionError("Upload size limit must be positive")


def test_worker_stale_window_must_exceed_process_timeout() -> None:
    try:
        Settings(
            analysis_timeout_seconds=300,
            process_termination_grace_seconds=5,
            worker_stale_after_seconds=305,
            _env_file=None,
        )
    except ValidationError:
        return
    raise AssertionError("Worker stale window must exceed the complete process timeout")
