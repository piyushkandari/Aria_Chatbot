"""Pydantic request/response models for the Aria HTTP API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

MAX_MESSAGE_LENGTH = 500


class CreateSessionResponse(BaseModel):
    """Response body for POST /api/session."""

    session_id: str = Field(..., description="Opaque session identifier")


class ChatRequest(BaseModel):
    """Request body for POST /api/chat."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(..., min_length=1, max_length=64)
    message: str = Field(..., min_length=1, max_length=MAX_MESSAGE_LENGTH)


class ChatResponse(BaseModel):
    """Response body for POST /api/chat."""

    reply: str
    category: str
    intent: str
    timestamp: datetime


class MessageEntry(BaseModel):
    """One recorded message in a session transcript."""

    role: str
    text: str
    timestamp: datetime
    category: str | None = None
    intent: str | None = None


class HistoryResponse(BaseModel):
    """Response body for GET /api/history/{session_id}."""

    session_id: str
    messages: list[MessageEntry]
    facts: dict[str, str]


class HealthResponse(BaseModel):
    """Response body for GET /api/health."""

    status: str
    version: str
    active_sessions: int
