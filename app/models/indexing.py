from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field

from app.core.i18n import render_text
from app.models.jobs import utcnow


class EmbeddingSourceType(str, Enum):
    entity = "entity"
    source = "source"
    relation = "relation"


class IndexScope(str, Enum):
    entity = "entity"
    source = "source"
    relation = "relation"
    all = "all"


class IndexType(str, Enum):
    vector = "vector"
    fulltext = "fulltext"


class IndexJobMode(str, Enum):
    backfill = "backfill"
    reindex = "reindex"


class IndexJobStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class IndexJobStage(str, Enum):
    queued = "queued"
    scanning = "scanning"
    indexing = "indexing"
    completed = "completed"
    failed = "failed"


class IndexJobRequest(BaseModel):
    index_type: IndexType
    scope: IndexScope = IndexScope.all


class IndexPreparationRequest(BaseModel):
    index_type: IndexType
    mode: IndexJobMode
    scope: IndexScope = IndexScope.all
    sample_limit: int = Field(default=20, ge=0, le=100)


class IndexCandidateSample(BaseModel):
    source_type: EmbeddingSourceType
    source_key: str
    title: str | None = None
    name: str | None = None
    summary: str | None = None
    aggregated_text: str | None = None
    left_entity_name: str | None = None
    right_entity_name: str | None = None
    target_hash: str | None = None


class IndexPreparationResponse(BaseModel):
    index_type: IndexType
    mode: IndexJobMode
    scope: IndexScope
    total_count: int
    counts: dict[str, int] = Field(default_factory=dict)
    candidates: list[IndexCandidateSample] = Field(default_factory=list)


class IndexJobEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    job_id: str
    stage: IndexJobStage
    message: str = ""
    message_key: str | None = None
    message_params: dict[str, object] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
    data: dict[str, object] = Field(default_factory=dict)

    def localized(self, language: str | None = None) -> "IndexJobEvent":
        if not self.message_key:
            return self.model_copy(deep=True)
        return self.model_copy(
            update={
                "message": render_text(
                    self.message_key,
                    params=self.message_params,
                    language=language,
                    default=self.message or self.message_key,
                )
            }
        )


class IndexJobSummary(BaseModel):
    job_id: str
    index_type: IndexType
    mode: IndexJobMode
    scope: IndexScope
    status: IndexJobStatus
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = None
    batch_size: int
    scanned_count: int = 0
    synced_count: int = 0
    failed_count: int = 0
    pending_count: int = 0
    last_error: str | None = None


class IndexJobCreateResponse(BaseModel):
    job_id: str
    status: IndexJobStatus


class SearchPreviewRequest(BaseModel):
    query: str = Field(min_length=1)
    mode: str = Field(default="hybrid")
    entity_limit: int = Field(default=5, ge=1, le=20)
    source_limit: int = Field(default=5, ge=1, le=20)
    relation_limit: int = Field(default=5, ge=1, le=20)


class EmbeddingCandidate(BaseModel):
    source_type: EmbeddingSourceType
    source_key: str
    embedding_key: str
    input_text: str
    target_hash: str


class TextIndexCandidate(BaseModel):
    source_type: EmbeddingSourceType
    source_key: str
    title: str | None = None
    name: str | None = None
    summary: str | None = None
    aggregated_text: str | None = None
    left_entity_name: str | None = None
    right_entity_name: str | None = None
    document_text: str
    target_hash: str


class IndexQueryResult(BaseModel):
    source_type: EmbeddingSourceType
    source_key: str
    entity_id: str | None = None
    score: float = 0.0
    vector_score: float | None = None
    fulltext_score: float | None = None
    hybrid_score: float | None = None
    title: str | None = None
    name: str | None = None
    summary: str | None = None
    category: str | None = None
    aliases: list[str] = Field(default_factory=list)
    left_entity_id: str | None = None
    right_entity_id: str | None = None
    left_entity_name: str | None = None
    right_entity_name: str | None = None
    aggregated_text: str | None = None


class GraphRAGContextDocumentPayload(BaseModel):
    kind: str
    title: str
    content: str
    metadata: dict[str, object] = Field(default_factory=dict)


class SearchPreviewResponse(BaseModel):
    query: str
    entities: list[dict[str, object]] = Field(default_factory=list)
    sources: list[dict[str, object]] = Field(default_factory=list)
    relations: list[dict[str, object]] = Field(default_factory=list)
    neighborhoods: list[dict[str, object]] = Field(default_factory=list)
    documents: list[GraphRAGContextDocumentPayload] = Field(default_factory=list)


class IndexStatusEntry(BaseModel):
    index_type: IndexType
    scope: IndexScope
    name: str
    exists: bool
    state: str | None = None
    population_percent: float | None = None
    failure_message: str | None = None


class IndexStatusResponse(BaseModel):
    indexes: list[IndexStatusEntry] = Field(default_factory=list)

