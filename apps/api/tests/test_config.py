from pathlib import Path

from pydantic import ValidationError

from docreview_api.config import REPOSITORY_DIRECTORY, Settings, load_settings


def test_settings_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_name == "DocReview API"
    assert settings.environment == "development"
    assert settings.api_prefix == "/api"
    assert settings.log_level == "INFO"
    assert settings.documents_dir == REPOSITORY_DIRECTORY / "data" / "documents"
    assert settings.runs_dir == REPOSITORY_DIRECTORY / "data" / "runs"


def test_invalid_api_prefix_is_rejected() -> None:
    try:
        Settings(api_prefix="api", _env_file=None)
    except ValidationError:
        return
    raise AssertionError("Settings must reject an API prefix without a leading slash")


def test_demo_profile_is_loaded() -> None:
    settings = load_settings("demo")

    assert settings.environment == "demo"
    assert settings.app_name == "DocReview API (demo)"
    assert settings.runs_dir == REPOSITORY_DIRECTORY / "data" / "demo" / "runs"
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
