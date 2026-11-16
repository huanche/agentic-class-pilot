"""The downloaded transcript preserves chronology and unmodified student text."""

from app.api.routes.dev_console_export import render_collection, render_transcript, student_code


def test_export_format_and_multiline_content() -> None:
    messages = [
        {"seq": 1, "role": "assistant", "content": "请解释数组下标……", "createdAt": "2026-11-13T02:00:00+00:00"},
        {"seq": 2, "role": "student", "content": "下标从 1 开始……\n这是第二行", "createdAt": "2026-11-13T02:01:00+00:00"},
    ]
    result = render_transcript(course="C语言程序设计", lesson="数组", student="S001",
                               started_at="2026-11-13T02:00:00+00:00", messages=messages)
    assert result.startswith("课程：C语言程序设计\n课时：数组\n学生：S001\n\n[10:00]")
    assert "[10:00] 助教：请解释数组下标……" in result
    assert "[10:01] 学生：下标从 1 开始……\n这是第二行" in result


def test_student_code_stable_and_course_scoped() -> None:
    first = student_code("test-secret", "course-1", "student-1")
    assert first == student_code("test-secret", "course-1", "student-1")
    assert first != student_code("test-secret", "course-2", "student-1")
    assert "student-1" not in first


def test_collection_keeps_sessions_separate() -> None:
    text = render_collection(["课程：C语言\n学生：S1\n", "课程：数学\n学生：S2\n"], "全部课程")
    assert text.startswith("对话记录导出范围：全部课程\n会话数：2\n")
    assert text.count("学生：") == 2
    assert "=" * 48 in text
