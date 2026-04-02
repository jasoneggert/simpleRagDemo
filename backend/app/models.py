from typing import Literal

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(min_length=3, description="User question about the docs.")
    top_k: int | None = Field(default=None, ge=1, le=10)


class SourceChunk(BaseModel):
    chunk_id: str
    document_id: str
    source_path: str
    title: str
    heading: str | None = None
    content: str
    score: float | None = None


class Citation(BaseModel):
    chunk_id: str
    source_path: str
    title: str
    quote: str = Field(description="Short excerpt supporting the answer.")


class AnswerPayload(BaseModel):
    answer: str = Field(
        min_length=12,
        description="Customer-facing answer to the billing question. Must be non-empty and specific.",
    )
    rationale: str = Field(
        min_length=12,
        description="Short internal explanation grounded in cited policy. Must be non-empty.",
    )
    recommended_action: str = Field(
        min_length=8,
        description="Single next step for the support agent. Must be non-empty and operational.",
    )
    escalation_required: bool = Field(description="Whether the case should be escalated.")
    citations: list[Citation]
    confidence: Literal["low", "medium", "high"]


class RetrievalDebug(BaseModel):
    query: str
    top_k: int
    system_prompt: str
    user_prompt: str
    retrieved_chunks: list[SourceChunk]


class AskResponse(BaseModel):
    answer: AnswerPayload
    debug: RetrievalDebug
