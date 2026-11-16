# ruff: noqa: T201 — printing the result is this script's job
"""Grant (or revoke) the internal read-only ``observer`` role.

The observer role is for team members who need the dev console
(``/dev-console`` API + ``/console`` page): read-only access to user,
course, and chat-record data. It is never selectable at registration and
is only granted here or directly by a superuser.

Usage (from ``backend/``)::

    uv run python scripts/create_observer.py someone@example.com          # grant
    uv run python scripts/create_observer.py someone@example.com --revoke  # revoke

Requires DATABASE_URL to point at the real database.
"""

import argparse
import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlmodel import Session, select

from app.core.db import engine
from app.models import User


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email", help="email of an existing user")
    parser.add_argument("--revoke", action="store_true", help="revert to student role")
    args = parser.parse_args()

    with Session(engine) as session:
        user = session.exec(
            select(User).where(User.email == args.email)
        ).first()
        if not user:
            print(f"未找到用户:{args.email}")
            return 1
        user.role = "student" if args.revoke else "observer"
        session.add(user)
        session.commit()
        action = "已撤销" if args.revoke else "已授予"
        print(f"{action} observer 角色:{user.email}(role={user.role})")
        return 0


if __name__ == "__main__":
    sys.exit(main())
