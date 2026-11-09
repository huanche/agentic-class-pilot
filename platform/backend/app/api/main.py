from fastapi import APIRouter

from app.api.routes import (
    agent_sessions,
    courses,
    dev_console,
    enrollments,
    items,
    login,
    private,
    student_bridge,
    teacher_bridge,
    teacher_chat_records,
    user_model_config,
    users,
    utils,
)
from app.core.config import settings

api_router = APIRouter()
api_router.include_router(teacher_bridge.router)
api_router.include_router(student_bridge.router)
api_router.include_router(teacher_chat_records.router)
api_router.include_router(dev_console.router)
api_router.include_router(user_model_config.router)
api_router.include_router(login.router)
api_router.include_router(users.router)
api_router.include_router(utils.router)
api_router.include_router(items.router)
api_router.include_router(courses.router)
api_router.include_router(enrollments.router)
api_router.include_router(agent_sessions.router)


if settings.FASTAPI_ENV == "development":
    api_router.include_router(private.router)
