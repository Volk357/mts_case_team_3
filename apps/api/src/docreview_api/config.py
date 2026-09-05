"""Application configuration loaded from environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import Field, field_validator, model_validator
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
    api_prefix: Literal["/api"] = "/api"
    log_level: LogLevel = "INFO"
    database_url: str = "postgresql+psycopg://docreview@localhost/docreview"
    documents_dir: Path = REPOSITORY_DIRECTORY / "data" / "documents"
    runs_dir: Path = REPOSITORY_DIRECTORY / "data" / "runs"
    artifacts_dir: Path = REPOSITORY_DIRECTORY / "data" / "artifacts"
    review_packs_dir: Path = REPOSITORY_DIRECTORY / "review-packs"
    analysis_executable: str = Field(default="docreview", min_length=1, max_length=1000)
    analysis_model_config_path: Path | None = None
    process_stdout_limit_bytes: int = Field(default=5 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)
    process_stderr_limit_bytes: int = Field(default=256 * 1024, ge=1024, le=10 * 1024 * 1024)
    analysis_timeout_seconds: float = Field(default=300.0, gt=0, le=24 * 60 * 60)
    process_termination_grace_seconds: float = Field(default=5.0, ge=0, le=60)
    worker_poll_interval_seconds: float = Field(default=1.0, gt=0, le=60)
    review_poll_interval_seconds: int = Field(default=2, ge=1, le=30)
    worker_stale_after_seconds: float = Field(default=600.0, gt=0, le=48 * 60 * 60)
    # Отметка живости воркера. Живёт рядом с рабочими каталогами, а не в базе:
    # заводить миграцию ради одного поля дороже, чем файл.
    worker_heartbeat_path: Path = REPOSITORY_DIRECTORY / "data" / "worker-heartbeat"
    # Во сколько интервалов опроса укладывается живой воркер. Три — запас на
    # один пропущенный цикл и разброс планировщика.
    worker_heartbeat_tolerance: float = Field(default=3.0, ge=1.0, le=100.0)
    review_result_schema_path: Path = (
        REPOSITORY_DIRECTORY / "contracts" / "review-result.schema.json"
    )
    max_review_result_size_bytes: int = Field(
        default=10 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024
    )
    max_upload_size_bytes: int = Field(default=50 * 1024 * 1024, ge=1, le=1024 * 1024 * 1024)
    max_request_size_bytes: int = Field(default=55 * 1024 * 1024, ge=1024, le=1100 * 1024 * 1024)
    rate_limit_requests: int = Field(default=120, ge=1, le=100_000)
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    default_company_id: UUID = UUID("00000000-0000-0000-0000-000000000001")
    default_company_slug: str = Field(default="local-mvp", min_length=1, max_length=100)
    default_company_name: str = Field(default="Local MVP Company", min_length=1, max_length=255)
    orphan_upload_grace_period_hours: int = Field(default=24, ge=1, le=24 * 30)
    document_retention_days: int = Field(default=90, ge=1, le=3650)
    artifact_retention_days: int = Field(default=14, ge=1, le=365)
    automatic_retention_enabled: bool = False
    cors_origins: tuple[str, ...] = (
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    )

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        """Только PostgreSQL.

        SQLite сознательно не поддерживается: приложение рассчитано на
        параллельных писателей (API и воркер пишут одновременно), а у SQLite
        для этого нет ни блокировки строки, ни `SELECT ... FOR UPDATE` — их
        приходилось бы подменять сериализацией всех транзакций. Держать в
        продукте вторую СУБД с другой моделью параллелизма означало бы
        тестировать одно, а поставлять другое.
        """

        if value.startswith(("postgresql://", "postgresql+psycopg://")):
            return value
        raise ValueError("Database URL must use PostgreSQL")

    @field_validator(
        "documents_dir",
        "runs_dir",
        "artifacts_dir",
        "review_packs_dir",
        "review_result_schema_path",
        mode="before",
    )
    @classmethod
    def resolve_storage_path(cls, value: object) -> Path:
        """Resolve relative storage paths from the repository root, not process cwd."""

        path = Path(str(value)).expanduser()
        return path if path.is_absolute() else (REPOSITORY_DIRECTORY / path).resolve()

    @field_validator("analysis_model_config_path", mode="before")
    @classmethod
    def resolve_optional_model_config_path(cls, value: object) -> Path | None:
        """Resolve an explicitly configured model file without reading its secrets."""

        if value is None:
            return None
        path = Path(str(value)).expanduser()
        return path if path.is_absolute() else (REPOSITORY_DIRECTORY / path).resolve()

    @field_validator("automatic_retention_enabled")
    @classmethod
    def reject_automatic_retention(cls, value: bool) -> bool:
        """Keep all MVP deletion explicit even if an environment is misconfigured."""

        if value:
            raise ValueError("Automatic retention is not available in the MVP")
        return value

    @field_validator("analysis_executable")
    @classmethod
    def validate_analysis_executable(cls, value: str) -> str:
        """Reject empty/control-character executable configuration."""

        executable = value.strip()
        if not executable or any(ord(character) < 32 for character in executable):
            raise ValueError("Analysis executable must be a non-empty path or command")
        return executable

    @model_validator(mode="after")
    def validate_worker_stale_window(self) -> "Settings":
        minimum = self.analysis_timeout_seconds + self.process_termination_grace_seconds
        if self.worker_stale_after_seconds <= minimum:
            raise ValueError(
                "Worker stale window must exceed the analysis timeout and termination grace period"
            )
        return self

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
