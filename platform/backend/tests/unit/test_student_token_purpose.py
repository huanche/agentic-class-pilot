"""Document the current launch/playback token purpose boundary."""

import uuid

import pytest
from fastapi import HTTPException

from app.api.routes.student_bridge import _issue_playback_grant, verify_launch_token
from app.core.config import settings


@pytest.mark.parametrize("refresh_session", [False, True])
def test_playback_token_cannot_be_used_as_launch_token(
    monkeypatch: pytest.MonkeyPatch, refresh_session: bool
) -> None:
    monkeypatch.setattr(settings, "STUDENT_TOKEN_SIGNING_KEY", "test-only-signing-key")
    token = _issue_playback_grant(uuid.uuid4(), uuid.uuid4(), "classroom-1")

    with pytest.raises(HTTPException) as error:
        verify_launch_token(token, refresh_session=refresh_session)

    assert error.value.status_code == 401
