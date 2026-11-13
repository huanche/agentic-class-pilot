"""Plain-text transcript formatting for the read-only dev console."""

import hashlib
import hmac
from datetime import datetime, timedelta, timezone


CHINA_TIME = timezone(timedelta(hours=8))


def student_code(secret: str, course_id: str, student_id: str) -> str:
    digest = hmac.new(secret.encode(), f"{course_id}:{student_id}".encode(), hashlib.sha256).hexdigest()
    return f"S{digest[:10].upper()}"


def display_time(value: str | None) -> tuple[str, str]:
    if not value:
        return "未知日期", "未知时间"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return "未知日期", "未知时间"
    if parsed.tzinfo is None:
        return parsed.strftime("%Y-%m-%d"), parsed.strftime("%H:%M")
    local = parsed.astimezone(CHINA_TIME)
    return local.strftime("%Y-%m-%d"), local.strftime("%H:%M")


def render_transcript(*, course: str, lesson: str, student: str,
                      started_at: str | None, messages: list[dict]) -> str:
    start_date, _ = display_time(started_at)
    lines = [f"课程：{course}", f"课时：{lesson}", f"学生：{student}", ""]
    previous_date = start_date
    for message in messages:
        date, clock = display_time(message.get("createdAt"))
        if date != previous_date:
            lines.extend([f"日期：{date}", ""])
            previous_date = date
        role = {"student": "学生", "assistant": "助教"}.get(message["role"], message["role"])
        content = str(message.get("content") or "").replace("\r\n", "\n").replace("\r", "\n")
        lines.append(f"[{clock}] {role}：{content}")
    return "\n".join(lines) + "\n"


def render_collection(sections: list[str], scope: str) -> str:
    heading = f"对话记录导出范围：{scope}\n会话数：{len(sections)}\n\n"
    return heading + ("\n" + "=" * 48 + "\n\n").join(sections)
