"""LLM package: registry of available models and the service that calls them."""

from app.services.llm.registry import LLMRegistry
from app.services.llm.service import LLMService, llm_service

__all__ = ["LLMRegistry", "LLMService", "llm_service"]
