"""Request and response bodies for the retrieval endpoint."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.retrieval.types import RetrievalResult


class RetrievalRequest(BaseModel):
    """A hybrid-retrieval query with optional metadata filters."""

    query: str = Field(min_length=1, max_length=2000)
    document_id: uuid.UUID | None = None
    language: str | None = Field(default=None, max_length=35)
    top_k: int | None = Field(default=None, ge=1)


class RetrievedChunkResponse(BaseModel):
    """One fused, authorized evidence chunk with full provenance."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    content: str
    fused_score: float
    lexical_rank: int | None
    dense_rank: int | None
    page_number: int | None
    section: str | None
    char_start: int
    char_end: int
    language: str | None
    ocr_engine: str | None
    ocr_confidence: float | None


class RetrievalResponse(BaseModel):
    """Ordered evidence plus a non-sensitive retrieval trace."""

    results: list[RetrievedChunkResponse]
    trace: dict[str, object]

    @classmethod
    def from_result(cls, result: RetrievalResult) -> RetrievalResponse:
        return cls(
            results=[
                RetrievedChunkResponse(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    document_version_id=chunk.document_version_id,
                    content=chunk.content,
                    fused_score=chunk.fused_score,
                    lexical_rank=chunk.lexical_rank,
                    dense_rank=chunk.dense_rank,
                    page_number=chunk.page_number,
                    section=chunk.section,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                    language=chunk.language,
                    ocr_engine=chunk.ocr_engine,
                    ocr_confidence=chunk.ocr_confidence,
                )
                for chunk in result.chunks
            ],
            trace=result.trace.as_metadata(),
        )
