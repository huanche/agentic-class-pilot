"""Freeze platform's historical cross-service DDL; new migrations stay with owners."""
from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
VERSIONS = ROOT / "platform/backend/app/alembic/versions"
HISTORICAL = {
    "final02_teacher_schema.py",
    "final03_teacher_sessions.py",
    "final04_object_storage.py",
    "final05_student_schema.py",
    "final07_self_rating.py",
    "final08_report_versions.py",
    "final09_remove_self_rating.py",
    "pub10_published_lesson_knowledge.py",
    # These revisions reached main before student-owned migrations were
    # introduced. Preserve Alembic history; reject any subsequent platform DDL.
    "cmd11_reliable_student_commands.py",
    "rec12_student_learning_records.py",
}
PRIVATE_DDL = re.compile(r"\b(?:teacher|student)\s*\.|\bmentra_[a-z_]+\b|\b(?:teacher|student)\s+schema\b", re.I)


def main() -> int:
    actual = {p.name for p in VERSIONS.glob("*.py")}
    missing = HISTORICAL - actual
    violating = [p.name for p in VERSIONS.glob("*.py")
                 if p.name not in HISTORICAL and PRIVATE_DDL.search(p.read_text(encoding="utf-8"))]
    if missing or violating:
        print("Historical cross-service migrations missing:", sorted(missing))
        print("New platform migrations touching teacher/student data:", sorted(violating))
        return 1
    print("[OK] new platform migrations do not manage teacher/student-owned tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
