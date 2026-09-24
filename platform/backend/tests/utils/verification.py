"""Helpers for email-verification-code tests."""

import hashlib
from datetime import UTC, datetime, timedelta

from sqlmodel import Session

from app.models import EmailVerification


def insert_verification_code(
    db: Session, email: str, code: str, *, expired: bool = False
) -> EmailVerification:
    record = EmailVerification(
        email=email.lower(),
        code_hash=hashlib.sha256(f"{email.lower()}:{code}".encode()).hexdigest(),
        expires_at=datetime.now(UTC) + timedelta(minutes=-1 if expired else 10),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record
