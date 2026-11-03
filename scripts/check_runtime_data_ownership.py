"""Reject new SQL string literals that bypass teacher/student data ownership."""

from __future__ import annotations

import ast
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PLATFORM = ROOT / "platform/backend/app"
STUDENT = ROOT / "student_agent"
PRIVATE_SQL = re.compile(r"\b(?:teacher|student)\.[a-z_][a-z_0-9]*", re.I)
TEACHER_SQL = re.compile(r"\bteacher\.[a-z_][a-z_0-9]*", re.I)


def source_files():
    for folder in (PLATFORM / "api", PLATFORM / "services"):
        yield from folder.rglob("*.py")
    for folder in (STUDENT / "agent", STUDENT / "backend"):
        yield from (p for p in folder.rglob("*.py") if "tests" not in p.parts)


def main() -> int:
    violations = []
    for path in source_files():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        pattern = PRIVATE_SQL if path.is_relative_to(PLATFORM) else TEACHER_SQL
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            for match in pattern.finditer(node.value):
                # Restrict to known table access, not prose such as "student.id".
                if match.group().lower().split(".", 1)[1] in {
                    "id", "role", "name", "email", "is_active", "full_name",
                }:
                    continue
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}: {match.group()}")
    if violations:
        print("Cross-owner SQL references in runtime source:")
        print("\n".join(violations))
        return 1
    print("[OK] platform and student runtime do not reference another service's private tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
