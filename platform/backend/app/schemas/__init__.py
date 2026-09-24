"""Pydantic request/response schemas and graph state for the chat pipeline.

Kept separate from ``app.models`` (SQLModel ORM tables): these shapes cross the
API / LLM boundaries, not the database.
"""
