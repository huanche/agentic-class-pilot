"""Minimal structured-event logger for the ported LLM model factory.

The vendored factory code (``app/services/llm/``) logs structlog-style:
``logger.debug("event_name", key=value, ...)``. The standard library rejects
arbitrary keyword arguments, so this shim formats them into the message and
forwards to a stdlib logger. It exists so the factory source stays
byte-identical to the vendor template without pulling in structlog itself.
"""

import logging

_stdlib_logger = logging.getLogger("app.llm")


def _format(event: str, kwargs: dict[str, object]) -> tuple[str, bool]:
    exc_info = bool(kwargs.pop("exc_info", False))
    if not kwargs:
        return event, exc_info
    pairs = " ".join(f"{key}={value!r}" for key, value in kwargs.items())
    return f"{event} {pairs}", exc_info


class EventLogger:
    """Adapter covering the exact subset of structlog's API the factory uses."""

    def debug(self, event: str, **kwargs: object) -> None:
        message, exc_info = _format(event, kwargs)
        _stdlib_logger.debug(message, exc_info=exc_info)

    def info(self, event: str, **kwargs: object) -> None:
        message, exc_info = _format(event, kwargs)
        _stdlib_logger.info(message, exc_info=exc_info)

    def warning(self, event: str, **kwargs: object) -> None:
        message, exc_info = _format(event, kwargs)
        _stdlib_logger.warning(message, exc_info=exc_info)

    def error(self, event: str, **kwargs: object) -> None:
        message, exc_info = _format(event, kwargs)
        _stdlib_logger.error(message, exc_info=exc_info)

    def exception(self, event: str, **kwargs: object) -> None:
        message, _ = _format(event, kwargs)
        # stdlib .exception() always attaches the active traceback
        _stdlib_logger.exception(message)

    def log(self, level: int, message: object, *args: object, **kwargs: object) -> None:
        # tenacity 9's before_sleep_log() calls logger.log(level, msg,
        # exc_info=...) — accept and forward the stdlib-specific kwarg.
        exc_info = bool(kwargs.pop("exc_info", False))
        if kwargs:
            kwargs_str = " ".join(f"{k}={v!r}" for k, v in kwargs.items())
            message = f"{message} {kwargs_str}"
        _stdlib_logger.log(level, message, *args, exc_info=exc_info)


logger = EventLogger()
