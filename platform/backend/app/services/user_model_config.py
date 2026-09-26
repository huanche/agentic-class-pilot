"""Per-user BYOK model configuration store.

Users persist provider credentials once; every subsequent platform action
(generation, guidance) uses their stored config. Keys are encrypted at rest
via app.core.credential_crypto and never returned to the browser — reads are
masked. Storage lives in public.user_model_config (migration final06); the
platform owns the schema and is the single writer.
"""
import json
import uuid
from typing import Any

from sqlalchemy import text

from app.core.credential_crypto import decrypt, encrypt

_SECRET_FIELDS = ("apiKey", "ttsApiKey", "asrApiKey")


def _mask(config: dict) -> dict:
    masked = json.loads(json.dumps(config, ensure_ascii=False))
    for section in masked.values():
        if isinstance(section, dict) and section.get("apiKey"):
            key = str(section["apiKey"])
            section["apiKey"] = (key[:4] + "…" + key[-4:]) if len(key) > 8 else "已设置"
            section["apiKeySet"] = True
    return masked


def _encrypt_credentials(config: dict) -> dict:
    import copy
    stored = copy.deepcopy(config)
    for section in stored.values():
        if isinstance(section, dict) and section.get("apiKey"):
            section["apiKey"] = encrypt(str(section["apiKey"]))
    return stored


def _decrypt_credentials(stored: dict) -> dict:
    config = json.loads(json.dumps(stored, ensure_ascii=False))
    for section in config.values():
        if isinstance(section, dict) and section.get("apiKey"):
            try:
                section["apiKey"] = decrypt(section["apiKey"])
            except ValueError:
                section["apiKey"] = ""
    return config


def get_masked(session, user_id: uuid.UUID) -> dict:
    row = session.execute(
        text("SELECT config FROM public.user_model_config WHERE user_id = :u"),
        {"u": str(user_id)}).first()
    return _mask(row[0]) if row else {}


def get_decrypted(session, user_id: uuid.UUID) -> dict:
    row = session.execute(
        text("SELECT config FROM public.user_model_config WHERE user_id = :u"),
        {"u": str(user_id)}).first()
    return _decrypt_credentials(row[0]) if row else {}


def save(session, user_id: uuid.UUID, config: dict) -> dict:
    session.execute(
        text("INSERT INTO public.user_model_config (user_id, config, updated_at) "
             "VALUES (:u, CAST(:config AS jsonb), now()) "
             "ON CONFLICT (user_id) DO UPDATE SET config = EXCLUDED.config, updated_at = now()"),
        {"u": str(user_id), "config": json.dumps(_encrypt_credentials(config), ensure_ascii=False)})
    session.commit()
    return get_masked(session, user_id)


def get_decrypted_by_user(session, user_id: uuid.UUID) -> dict:
    """Service-facing accessor: decrypted config for one user."""
    row = session.execute(
        text("SELECT config FROM public.user_model_config WHERE user_id = :u"),
        {"u": str(user_id)}).first()
    return _decrypt_credentials(row[0]) if row else {}
