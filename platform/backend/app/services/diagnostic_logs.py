"""Read a bounded window of service logs for the internal console."""

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

SERVICES = ("platform", "student", "teacher")
TAIL_BYTES = 256 * 1024
FILES_PER_STREAM = 4
TEACHER_LINE = re.compile(r"^\[([^\]]+)\] \[(DEBUG|INFO|WARN|ERROR)\] \[([\w.-]{1,80})\]")
IDENTIFIER = re.compile(r"[A-Za-z0-9_.-]{1,80}")
REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{8,64}")
ROUTE = re.compile(r"/[A-Za-z0-9_./{}:-]{0,240}")


def parse_event(line: str, service: str) -> tuple[datetime, dict] | None:
    if len(line) > 16_384:
        return None
    try:
        raw = json.loads(line)
    except (ValueError, RecursionError):
        match = TEACHER_LINE.match(line) if service == "teacher" else None
        if not match:
            return None
        timestamp, level, tag = match.groups()
        raw = {"timestamp": timestamp, "level": level, "tag": tag}
    if not isinstance(raw, dict):
        return None

    timestamp = raw.get("ts") or raw.get("timestamp")
    level = str(raw.get("level", "")).lower()
    if not isinstance(timestamp, str) or level not in {
        "debug", "info", "warn", "warning", "error",
    }:
        return None
    if timestamp.endswith("Z"):
        timestamp = timestamp[:-1] + "+00:00"
    try:
        when = datetime.fromisoformat(timestamp)
    except ValueError:
        return None
    if when.tzinfo is None:
        return None

    # Expose a fixed set of metadata. Messages, raw paths, and exception
    # payloads may contain request bodies or credentials.
    event = {
        "timestamp": when.isoformat(),
        "service": service,
        "level": "warning" if level == "warn" else level,
    }
    for key, value, pattern in (
        ("event", raw.get("event") or raw.get("tag"), IDENTIFIER),
        ("request_id", raw.get("request_id"), REQUEST_ID),
        ("method", raw.get("method"), IDENTIFIER),
        ("route", raw.get("route"), ROUTE),
        ("error_type", raw.get("error_type"), IDENTIFIER),
        ("error_code", raw.get("error_code"), IDENTIFIER),
    ):
        if isinstance(value, str) and pattern.fullmatch(value):
            event[key] = value
    for key in ("status_code", "duration_ms"):
        value = raw.get(key)
        if type(value) is int and 0 <= value <= 2**31 - 1:
            event[key] = value
    return when, event


def _read_tail(path: Path) -> tuple[list[str], bool]:
    with path.open("rb") as stream:
        start = max(0, stream.seek(0, os.SEEK_END) - TAIL_BYTES)
        stream.seek(start)
        data = stream.read(TAIL_BYTES)
    if start:
        data = data.partition(b"\n")[2]
    # The producer may still be writing the final line.
    return data.rpartition(b"\n")[0].decode("utf-8", errors="replace").splitlines(), bool(start)


def read_recent_logs(
    *, local: bool, service: str | None, hours: int, request_id: str | None,
    problems_only: bool, limit: int,
) -> dict:
    configured_dir = os.environ.get("DEV_CONSOLE_LOG_DIR")
    directory = Path(configured_dir) if configured_dir else None
    if directory is None and local:
        directory = Path(__file__).resolve().parents[4] / ".runtime" / "local-dev"

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    services = (service,) if service else SERVICES
    events = []
    unavailable = []
    truncated = False
    for name in services:
        readable = False
        for stream in ("stdout", "stderr"):
            paths = sorted(
                directory.glob(f"{name}-*.{stream}.log"), reverse=True,
            ) if directory else []
            truncated |= len(paths) > FILES_PER_STREAM
            for path in paths[:FILES_PER_STREAM]:
                try:
                    if path.is_symlink() or not path.is_file():
                        continue
                    lines, tail_truncated = _read_tail(path)
                except OSError:
                    continue
                readable = True
                truncated |= tail_truncated
                for line in lines:
                    parsed = parse_event(line, name)
                    if parsed is None:
                        continue
                    when, event = parsed
                    if when < cutoff or (request_id and event.get("request_id") != request_id):
                        continue
                    if (
                        problems_only and not request_id
                        and event["level"] not in ("warning", "error")
                        and event.get("status_code", 0) < 400
                    ):
                        continue
                    events.append((when, event))
        if not readable:
            unavailable.append(name)
    events.sort(key=lambda item: item[0], reverse=True)
    return {
        "events": [event for _, event in events[:limit]],
        "unavailable": unavailable,
        "truncated": truncated or len(events) > limit,
    }
