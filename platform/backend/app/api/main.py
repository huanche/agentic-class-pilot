from fastapi import APIRouter

from app.api.routes import (
    agent_sessions,
    courses,
    enrollments,
    items,
    login,
    private,
    users,
    utils,
)
from app.core.config import settings
from app.api.routes import student_bridge, teacher_bridge

api_router = APIRouter()
api_router.include_router(teacher_bridge.router)
api_router.include_router(student_bridge.router)
api_router.include_router(login.router)
api_router.include_router(users.router)
api_router.include_router(utils.router)
api_router.include_router(items.router)
api_router.include_router(courses.router)
api_router.include_router(enrollments.router)
api_router.include_router(agent_sessions.router)


if settings.FASTAPI_ENV == "development":
    api_router.include_router(private.router)
