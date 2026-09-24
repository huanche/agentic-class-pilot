import warnings
from enum import StrEnum
from typing import Literal, Self

from pydantic import (
    EmailStr,
    HttpUrl,
    PostgresDsn,
    computed_field,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Use top level .env file (one level above ./backend/)
        env_file="../.env",
        env_ignore_empty=True,
        extra="ignore",
    )
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str
    # 60 minutes * 24 hours * 8 days = 8 days
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8
    FRONTEND_HOST: str = "http://localhost:5173"
    FASTAPI_ENV: Literal["development"] | None = None

    PROJECT_NAME: str
    EMBEDDED_AGENTS_ENABLED: bool = False
    TEACHER_SERVICE_KEY: str = ""
    TEACHER_URL: str = "http://127.0.0.1:3200"
    TEACHER_PUBLIC_URL: str = "http://localhost:3200"
    # Extra browser origins (teacher service dev ports, e.g. "http://localhost:3200")
    # accepted for non-GET teacher requests, in addition to FRONTEND_HOST.
    TEACHER_ALLOWED_ORIGINS: str = ""
    STUDENT_SERVICE_KEY: str = ""
    STUDENT_URL: str = "http://127.0.0.1:8000"
    STUDENT_PUBLIC_URL: str = "http://localhost:8000"
    # Launch-token lifetime for student workspace entry, in seconds.
    STUDENT_LAUNCH_TOKEN_TTL_SECONDS: int = 600
    PLATFORM_URL: str = "http://localhost:8080"
    SENTRY_DSN: HttpUrl | None = None
    DATABASE_URL: PostgresDsn

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _use_psycopg_driver(cls, value: str | PostgresDsn) -> str:
        database_url = str(value)
        for scheme in ("postgres://", "postgresql://"):
            if database_url.startswith(scheme):
                return database_url.replace(scheme, "postgresql+psycopg://", 1)
        return database_url

    SMTP_TLS: bool = True
    SMTP_SSL: bool = False
    SMTP_PORT: int = 587
    SMTP_HOST: str | None = None
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    EMAILS_FROM_EMAIL: EmailStr | None = None
    EMAILS_FROM_NAME: str | None = None

    @model_validator(mode="after")
    def _set_default_emails_from(self) -> Self:
        if not self.EMAILS_FROM_NAME:
            self.EMAILS_FROM_NAME = self.PROJECT_NAME
        return self

    EMAIL_RESET_TOKEN_EXPIRE_HOURS: int = 48

    @computed_field  # type: ignore[prop-decorator]
    @property
    def emails_enabled(self) -> bool:
        return bool(self.SMTP_HOST and self.EMAILS_FROM_EMAIL)

    EMAIL_TEST_USER: EmailStr = "test@example.com"
    FIRST_SUPERUSER: EmailStr
    FIRST_SUPERUSER_PASSWORD: str

    # LLM for in-LMS features (student Q&A), OpenAI-compatible API
    LLM_API_KEY: str | None = None
    LLM_BASE_URL: str = "https://api.deepseek.com/v1"
    LLM_MODEL: str = "deepseek-v4-flash"

    # Model factory knobs (app/services/llm/, ported from the vendor template).
    # Field names are what the vendored registry.py/service.py read at import
    # time, so they must exist before the factory is imported. MAX_LLM_CALL_
    # RETRIES in particular is baked into the tenacity decorator on import.
    ENVIRONMENT: Environment = Environment.DEVELOPMENT
    DEFAULT_LLM_MODEL: str = ""  # empty = follow LLM_MODEL
    MAX_TOKENS: int = 2000
    MAX_LLM_CALL_RETRIES: int = 3
    LLM_TOTAL_TIMEOUT: int = 60
    # Context-window budget (tokens) for trimming chat history in the
    # LangGraph pipeline (app/core/langgraph/utils.py). Distinct from
    # MAX_TOKENS above, which caps generation output.
    LLM_CONTEXT_TOKENS: int = 2000

    # LangGraph checkpoint persistence (app/core/langgraph/graph.py). The
    # three tables are created by ``checkpointer.setup()`` on first start —
    # no alembic migration. The checkpointer uses its own async psycopg pool
    # (separate from the sync SQLModel engine), sized by CHECKPOINT_POOL_SIZE.
    CHECKPOINT_TABLES: list[str] = [
        "checkpoint_blobs",
        "checkpoint_writes",
        "checkpoints",
    ]
    CHECKPOINT_POOL_SIZE: int = 20

    @model_validator(mode="after")
    def _default_llm_model(self) -> Self:
        if not self.DEFAULT_LLM_MODEL:
            self.DEFAULT_LLM_MODEL = self.LLM_MODEL
        return self

    def _check_default_secret(self, var_name: str, value: str | None) -> None:
        if value == "changethis":
            message = (
                f'The value of {var_name} is "changethis", '
                "for security, please change it, at least for deployments."
            )
            if self.FASTAPI_ENV == "development":
                warnings.warn(message, stacklevel=1)
            else:
                raise ValueError(message)

    @model_validator(mode="after")
    def _enforce_non_default_secrets(self) -> Self:
        self._check_default_secret("SECRET_KEY", self.SECRET_KEY)
        for host in self.DATABASE_URL.hosts():
            self._check_default_secret("DATABASE_URL password", host["password"])
        self._check_default_secret(
            "FIRST_SUPERUSER_PASSWORD", self.FIRST_SUPERUSER_PASSWORD
        )

        return self


settings = Settings()  # type: ignore
