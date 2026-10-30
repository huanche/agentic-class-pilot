"""Document the current launch/playback token purpose boundary."""

import base64
import json
import time

import pytest
from fastapi import HTTPException

from app.api.routes.student_bridge import _launch_signature, verify_launch_token
from app.core.config import settings


@pytest.mark.parametrize("refresh_session", [False, True])
def test_other_purpose_token_cannot_be_used_as_launch_token(
    monkeypatch: pytest.MonkeyPatch, refresh_session: bool
) -> None:
    monkeypatch.setattr(settings, "STUDENT_TOKEN_SIGNING_KEY", "test-only-signing-key")
    payload_json = json.dumps({"kind": "other", "exp": int(time.time()) + 60},
                              separators=(",", ":"), sort_keys=True)
    encoded = base64.urlsafe_b64encode(payload_json.encode()).decode().rstrip("=")
    token = f"{encoded}.{_launch_signature(payload_json)}"

    with pytest.raises(HTTPException) as error:
        verify_launch_token(token, refresh_session=refresh_session)

    assert error.value.status_code == 401
