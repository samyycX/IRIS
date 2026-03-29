from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field

from app.models.jobs import utcnow


class EmbeddingSourceType(str, Enum):
    entity = "entity"
    page = "page"
    relation = "relation"


class VectorIndexScope(str, Enum):
    entity = "entity"
    page = "page"
    relation = "relation"
    all = "all"


class VectorIndexJobMode(str, Enum):
    backfill = "backfill"
    reindex = "reindex"


class VectorIndexJobStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class VectorIndexJobStage(str, Enum):
    queued = "queued"
    scanning = "scanning"
    embedding = "embedding"
    completed = "completed"
    failed = "failed"


class VectorIndexJobRequest(BaseModel):
    scope: VectorIndexScope = VectorIndexScope.all
    batch_size: int | None = Field(default=None, ge=1)


class VectorIndexJobEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    job_id: str
    stage: VectorIndexJobStage
    message: str
    created_at: datetime = Field(default_factory=utcnow)
    data: dict[str, object] = Field(default_factory=dict)


class VectorIndexJobSummary(BaseModel):
    job_id: str
    mode: VectorIndexJobMode
    scope: VectorIndexScope
    status: VectorIndexJobStatus
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = None
    batch_size: int
    scanned_count: int = 0
    synced_count: int = 0
    failed_count: int = 0
    pending_count: int = 0
    last_error: str | None = None


class VectorIndexJobCreateResponse(BaseModel):
    job_id: str
    status: VectorIndexJobStatus


class VectorIndexQueryPreviewRequest(BaseModel):
    query: str = Field(min_length=1)
    entity_limit: int = Field(default=5, ge=1, le=20)
    page_limit: int = Field(default=5, ge=1, le=20)
    relation_limit: int = Field(default=5, ge=1, le=20)


class EmbeddingCandidate(BaseModel):
    source_type: EmbeddingSourceType
    source_key: str
    embedding_key: str
    input_text: str
    target_hash: str


class EmbeddingQueryResult(BaseModel):
    source_type: EmbeddingSourceType
    source_key: str
    score: float
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
