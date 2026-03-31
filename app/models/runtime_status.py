from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class DependencyHealthState(str, Enum):
    healthy = "healthy"
    degraded = "degraded"
    unconfigured = "unconfigured"


class DependencyStatus(BaseModel):
    state: DependencyHealthState
    configured: bool
    available: bool
    last_checked_at: datetime | None = None
    last_error: str | None = None
    details: dict[str, str] = Field(default_factory=dict)


class GraphStatistics(BaseModel):
    entity_count: int = 0
    source_count: int = 0
    relation_count: int = 0
    stale: bool = False
    last_updated_at: datetime | None = None


class RuntimeStatusResponse(BaseModel):
    status: DependencyHealthState
    checked_at: datetime
    neo4j: DependencyStatus
    llm: DependencyStatus
    embedding: DependencyStatus
    graph: GraphStatistics = Field(default_factory=GraphStatistics)