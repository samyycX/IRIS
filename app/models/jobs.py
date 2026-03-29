from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, HttpUrl


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobInputType(str, Enum):
    url = "url"
    instruction = "instruction"
    entity = "entity"


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    paused = "paused"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    interrupted = "interrupted"


class JobStage(str, Enum):
    queued = "queued"
    fetching = "fetching"
    extracting = "extracting"
    discovering = "discovering"
    summarizing = "summarizing"
    updating_graph = "updating_graph"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class ExtractedEntity(BaseModel):
    name: str
    category: str = "unknown"
    summary: str
    aliases: list[str] = Field(default_factory=list)
    relations: list[dict[str, Any]] = Field(default_factory=list)
    deleted_relations: list[dict[str, Any]] = Field(default_factory=list)


class PageExtraction(BaseModel):
    canonical_url: str
    title: str | None = None
    summary: str
    extracted_entities: list[ExtractedEntity] = Field(default_factory=list)
    discovered_urls: list[str] = Field(default_factory=list)
    content_hash: str
    raw_text_excerpt: str


class GraphUpdateResult(BaseModel):
    created_entities: list[str] = Field(default_factory=list)
    updated_entities: list[str] = Field(default_factory=list)
    created_pages: list[str] = Field(default_factory=list)
    created_relationships: int = 0
    deleted_relationships: int = 0


class JobRequest(BaseModel):
    input_type: JobInputType
    url: HttpUrl | None = None
    instruction: str | None = None
    entity_name: str | None = None
    max_depth: int | None = None
    max_pages: int | None = None
    crawl_concurrency: int | None = Field(default=None, ge=1)
    filter_candidate_urls: bool = True

    def seed(self) -> str:
        if self.url is not None:
            return str(self.url)
        if self.instruction:
            return self.instruction
        if self.entity_name:
            return self.entity_name
        raise ValueError("Job request does not contain any usable seed input.")


class JobCreateResponse(BaseModel):
    job_id: str
    status: JobStatus


class JobEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    job_id: str
    stage: JobStage
    message: str
    created_at: datetime = Field(default_factory=utcnow)
    url: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class JobQueueItem(BaseModel):
    url: str
    depth: int
    referer: str | None = None


class JobCheckpoint(BaseModel):
    pending_queue: list[JobQueueItem] = Field(default_factory=list)
    in_progress: list[JobQueueItem] = Field(default_factory=list)
    visited_urls: list[str] = Field(default_factory=list)
    completion_reason: str | None = None
    last_event_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utcnow)


class JobSummary(BaseModel):
    job_id: str
    input_type: JobInputType
    seed: str
    status: JobStatus
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = None
    max_depth: int
    max_pages: int
    visited_count: int = 0
    queued_count: int = 0
    failed_count: int = 0
    last_error: str | None = None
    graph_update: GraphUpdateResult | None = None
    resume_available: bool = False
    checkpoint_updated_at: datetime | None = None
    completion_reason: str | None = None


class CrawlContext(BaseModel):
    job_id: str
    current_depth: int
    seed_url: str
    max_depth: int
    max_pages: int


class CrawlPageResult(BaseModel):
    url: str
    canonical_url: str
    title: str | None = None
    status_code: int
    fetch_mode: str = "http"
    html: str
    text: str
    links: list[str] = Field(default_factory=list)
    content_hash: str
