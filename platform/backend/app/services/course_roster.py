"""平台保存教师确认的课程名单，账号关联不改变注册身份或选课记录。"""
import uuid

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlmodel import Session


class RosterEntry(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    studentNumber: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    major: str = Field(default="", max_length=255)
    grade: str = Field(default="", max_length=64)
    gender: str = Field(default="", max_length=32)
    studentId: uuid.UUID | None = None


def load_roster(session: Session, course_id: uuid.UUID) -> list[dict]:
    rows = session.execute(text('''
        SELECT student_number, name, major, grade, gender, user_id
        FROM course_student_profile WHERE course_id=:course ORDER BY student_number
    '''), {"course": course_id}).all()
    return [{"studentNumber": r[0], "name": r[1], "major": r[2], "grade": r[3],
             "gender": r[4], "studentId": str(r[5]) if r[5] else None} for r in rows]


def save_roster(session: Session, course_id: uuid.UUID, entries: list[RosterEntry],
                previous: list[RosterEntry]) -> list[dict]:
    # 同一课程的导入串行提交；预览后若他人修改名单，要求重新核对，避免覆盖。
    session.execute(text("SELECT id FROM course WHERE id=:course FOR UPDATE"), {"course": course_id})
    current = load_roster(session, course_id)
    expected = sorted([entry.model_dump(mode="json") for entry in previous], key=lambda e: e["studentNumber"])
    if current != expected:
        raise HTTPException(409, "名单已被其他操作更新，请重新打开并核对后保存")
    numbers = [entry.studentNumber for entry in entries]
    linked = [entry.studentId for entry in entries if entry.studentId]
    if len(numbers) != len(set(numbers)):
        raise HTTPException(422, "学号重复，请核对名单")
    if len(linked) != len(set(linked)):
        raise HTTPException(422, "同一注册账号不能关联多个学生")
    enrolled = set(session.execute(text('''SELECT student_id FROM enrollment
        WHERE course_id=:course'''), {"course": course_id}).scalars())
    if set(linked) - enrolled:
        raise HTTPException(422, "只能关联已加入本课程的学生账号")
    # 上传只新增或更新指定学号。未出现在本次 PDF 的历史行仍保留。
    unchanged = {row["studentId"] for row in current if row["studentNumber"] not in numbers and row["studentId"]}
    if {str(value) for value in linked} & unchanged:
        raise HTTPException(422, "账号已关联其他学号，请先在名单管理中解除原关联")
    if numbers:
        session.execute(text('''UPDATE course_student_profile SET user_id=NULL
            WHERE course_id=:course AND student_number=ANY(:numbers)'''), {"course": course_id, "numbers": numbers})
    for entry in entries:
        session.execute(text('''INSERT INTO course_student_profile
            (course_id, student_number, name, major, grade, gender, user_id)
            VALUES (:course, :number, :name, :major, :grade, :gender, :user)
            ON CONFLICT (course_id, student_number) DO UPDATE SET
            name=EXCLUDED.name, major=EXCLUDED.major, grade=EXCLUDED.grade,
            gender=EXCLUDED.gender, user_id=EXCLUDED.user_id, updated_at=now()
        '''), {"course": course_id, "number": entry.studentNumber, "name": entry.name,
               "major": entry.major, "grade": entry.grade, "gender": entry.gender, "user": entry.studentId})
    session.commit()
    return load_roster(session, course_id)
