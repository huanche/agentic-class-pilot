"""Centralized environment configuration for the student agent platform layer.

Fail-closed: in production mode a missing required variable raises immediately;
the agent must never silently fall back to demo data.
"""
import os


class IntegrationConfigError(RuntimeError):
    """Raised when required platform configuration is missing or invalid."""


def _clean(name: str) -> str:
    value = os.environ.get(name, "").strip()
    return value


def demo_mode() -> bool:
    return _clean("STUDENT_DEMO_MODE").lower() == "true"


def platform_auth_url() -> str:
    """Base URL of the platform internal API (…/api/v1)."""
    return _clean("PLATFORM_AUTH_URL")


def student_service_key() -> str:
    return _clean("STUDENT_SERVICE_KEY")


def student_database_url() -> str:
    return _clean("STUDENT_DATABASE_URL")


def student_database_schema() -> str:
    return _clean("STUDENT_DATABASE_SCHEMA") or "student"


def require_platform_config() -> None:
    """Production entry points call this; missing config fails closed."""
    if demo_mode():
        return
    missing = [name for name, value in (
        ("PLATFORM_AUTH_URL", platform_auth_url()),
        ("STUDENT_SERVICE_KEY", student_service_key()),
    ) if not value]
    if missing:
        raise IntegrationConfigError(
            f"学生 Agent 平台配置缺失: {', '.join(missing)}（正式模式禁止回退 demo 数据）")


def require_database_config() -> None:
    """Learning-data persistence requires the shared database."""
    if demo_mode():
        return
    if not student_database_url():
        raise IntegrationConfigError(
            "STUDENT_DATABASE_URL 未配置：正式模式学习数据必须写入 student schema")
