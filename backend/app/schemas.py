from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody


class DocumentCreateResponse(BaseModel):
    id: UUID
    title: str
    status: str
    job_id: UUID
    stage: str


class DocumentOut(BaseModel):
    id: UUID
    title: str
    manufacturer: str
    machine_model: str
    equipment_type: str
    plant: str
    document_revision: str
    effective_date: date | None
    filename: str
    mime_type: str
    size_bytes: int
    status: str
    is_demo: bool
    chunk_count: int = 0
    job: dict[str, Any] | None = None
    created_at: datetime


class DocumentList(BaseModel):
    documents: list[DocumentOut]
    stats: dict[str, Any]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_token: str | None = None
    manufacturer: str | None = None
    machine_model: str | None = None


class FeedbackRequest(BaseModel):
    message_id: UUID
    rating: str = Field(pattern="^(up|down)$")
    comment: str | None = Field(default=None, max_length=2000)


class EvaluationRequest(BaseModel):
    case_ids: list[str] | None = None
