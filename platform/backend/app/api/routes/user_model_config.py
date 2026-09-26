"""User model-config endpoints: BYOK configuration for teachers and students."""
import hmac
import uuid

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.services import user_model_config as store

router = APIRouter(tags=["user-model-config"])


def _check_service_key(value: str | None, expected: str) -> None:
    if not expected or not hmac.compare_digest(value or "", expected):
        raise HTTPException(403, "Invalid service credentials")


class ModelConfigIn(BaseModel):
    llm: dict = Field(default_factory=dict)
    tts: dict = Field(default_factory=dict)
    asr: dict = Field(default_factory=dict)
    image: dict = Field(default_factory=dict)


def _validate(config: dict) -> None:
    llm = config.get("llm") or {}
    if llm.get("apiKey") or llm.get("baseUrl"):
        for field in ("baseUrl", "apiKey", "model"):
            if not str(llm.get(field) or "").strip():
                raise HTTPException(422, f"LLM 配置缺少 {field}")
    tts = config.get("tts") or {}
    if tts.get("apiKey") or tts.get("provider"):
        for field in ("provider", "apiKey"):
            if not str(tts.get(field) or "").strip():
                raise HTTPException(422, f"语音配置缺少 {field}")


@router.get("/users/me/model-config")
def read_model_config(session: SessionDep, user: CurrentUser):
    """Masked read: shows whether a key is set, never the key itself."""
    return store.get_masked(session, user.id)


@router.put("/users/me/model-config")
def save_model_config(payload: ModelConfigIn, session: SessionDep, user: CurrentUser):
    incoming = payload.model_dump()
    # 合并语义：空 section（未填）原样保留已存配置；apiKey 留空 = 沿用已保存的 Key
    existing = store.get_decrypted(session, user.id)
    for section, value in incoming.items():
        old_section = existing.get(section) or {}
        if not value:
            incoming[section] = old_section
            continue
        if not str(value.get("apiKey") or "").strip():
            value["apiKey"] = old_section.get("apiKey", "")
    _validate(incoming)
    return store.save(session, user.id, incoming)


@router.delete("/users/me/model-config")
def clear_model_config(session: SessionDep, user: CurrentUser):
    session.execute(
        text("DELETE FROM public.user_model_config WHERE user_id = :u"),
        {"u": str(user.id)})
    session.commit()
    return {"cleared": True}


@router.get("/internal/user/{user_id}/model-config")
def internal_model_config(user_id: uuid.UUID, session: SessionDep,
                          x_teacher_service_key: str | None = Header(default=None),
                          x_student_service_key: str | None = Header(default=None)):
    """Service-facing decrypted config for the student/teacher agents."""
    provided = x_teacher_service_key or x_student_service_key
    # 教师/学生 service key 是两把不同的钥匙，任一匹配即可
    expected_keys = [k for k in (settings.TEACHER_SERVICE_KEY, settings.STUDENT_SERVICE_KEY) if k]
    if not provided or not any(
        hmac.compare_digest(provided, k) for k in expected_keys
    ):
        raise HTTPException(403, "Invalid service credentials")
    return store.get_decrypted_by_user(session, user_id)
