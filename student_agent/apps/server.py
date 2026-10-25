"""Load deployment configuration and expose the new FastAPI application.

Existing systemd units may still import ``apps.server:app``. This file keeps
that entry point while all classroom behavior lives in ``backend.main``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_environment(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip().strip('"'))


_load_environment(ROOT / ".env.local")
_load_environment(ROOT.parent / "platform" / ".env")
if not os.environ.get("PLATFORM_AUTH_URL") and os.environ.get("PLATFORM_URL"):
    os.environ["PLATFORM_AUTH_URL"] = os.environ["PLATFORM_URL"].rstrip("/") + "/api/v1"
for new_name, old_name in (
    ("STUDENT_AGENT_API_KEY", "AGENT_LLM_API_KEY"),
    ("STUDENT_AGENT_BASE_URL", "AGENT_LLM_BASE_URL"),
    ("STUDENT_AGENT_MODEL", "AGENT_LLM_MODEL"),
):
    if not os.environ.get(new_name) and os.environ.get(old_name):
        os.environ[new_name] = os.environ[old_name]

from backend.main import app  # noqa: E402


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("AGENT_PORT", "8000")))
