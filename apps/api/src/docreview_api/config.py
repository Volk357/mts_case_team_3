"""Application configuration loaded from environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "demo", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

API_DIRECTORY = Path(__file__).resolve().parents[2]
REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[4]
PROFILE_DIRECTORY = API_DIRECTORY / "config"
LOCAL_ENV_FILE = API_DIRECTORY / ".env"


class EnvironmentSelector(BaseSettings):
    """Read only the environment name before loading its checked-in profile."""

    model_config = SettingsConfigDict(
        env_prefix="DOCREVIEW_",
        extra="ignore",
    )

    environment: Environment = "development"


class Settings(BaseSettings):
    """Runtime settings for the Product Application API."""

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        env_prefix="DOCREVIEW_",
        extra="ignore",
    )

    app_name: str = "DocReview API"
    environment: Environment = "development"
    api_prefix: str = Field(default="/api", pattern=r"^/[A-Za-z0-9/_-]*$")
    log_level: LogLevel = "INFO"
    documents_dir: Path = REPOSITORY_DIRECTORY / "data" / "documents"
    runs_dir: Path = REPOSITORY_DIRECTORY / "data" / "runs"
    artifacts_dir: Path = REPOSITORY_DIRECTORY / "data" / "artifacts"
    cors_origins: tuple[str, ...] = (
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    )

    @field_validator("documents_dir", "runs_dir", "artifacts_dir", mode="before")
    @classmethod
    def resolve_storage_path(cls, value: object) -> Path:
        """Resolve relative storage paths from the repository root, not process cwd."""

        path = Path(str(value)).expanduser()
        return path if path.is_absolute() else (REPOSITORY_DIRECTORY / path).resolve()

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, origins: tuple[str, ...]) -> tuple[str, ...]:
        """Accept explicit HTTP(S) origins without paths or wildcard credentials."""

        normalized: list[str] = []
        for origin in origins:
            candidate = origin.rstrip("/")
            parsed = urlparse(candidate)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.path
                or parsed.params
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(f"Invalid CORS origin: {origin}")
            normalized.append(candidate)
        return tuple(dict.fromkeys(normalized))


def load_settings(
    environment: Environment | None = None,
    *,
    local_env_file: Path = LOCAL_ENV_FILE,
    profile_directory: Path = PROFILE_DIRECTORY,
) -> Settings:
    """Load a checked-in profile and then optional local overrides."""

    selected_environment = environment
    if selected_environment is None:
        selector_file = local_env_file if local_env_file.is_file() else None
        selected_environment = EnvironmentSelector(_env_file=selector_file).environment

    profile_file = profile_directory / f"{selected_environment}.env"
    env_files = tuple(path for path in (profile_file, local_env_file) if path.is_file())
    return Settings(
        environment=selected_environment,
        _env_file=env_files or None,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return one immutable-by-convention settings instance per process."""

    return load_settings()
