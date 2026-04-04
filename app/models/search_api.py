from __future__ import annotations

from typing import Any
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.config import SearchPermissionSource, SearchPermissionSourceKind


class SearchMode(str, Enum):
    fulltext = "fulltext"
    vector = "vector"
    hybrid = "hybrid"


class SearchApiSettingsUpdateRequest(BaseModel):
    enabled: bool
    validation_enabled: bool


class SearchPermissionSourceCreateRequest(BaseModel):
    id: str | None = None
    kind: SearchPermissionSourceKind
    description: str = ""
    enabled: bool = True
    allow_builtin_embedding: bool = False
    ip_value: str | None = None

    @model_validator(mode="after")
    def _validate_create_payload(self) -> "SearchPermissionSourceCreateRequest":
        if self.kind == SearchPermissionSourceKind.ip and not self.ip_value:
            raise ValueError("ip_value is required for IP permission sources")
        return self


class SearchPermissionSourceUpdateRequest(BaseModel):
    description: str = ""
    enabled: bool = True
    allow_builtin_embedding: bool = False
    ip_value: str | None = None


class SearchPermissionSourceCreateResponse(BaseModel):
    permission_source: SearchPermissionSource
    generated_api_key: str | None = None


class SearchApiCapabilitiesResponse(BaseModel):
    enabled: bool
    validation_enabled: bool
    authenticated: bool
    matched_permission_source_id: str | None = None
    matched_permission_source_kind: SearchPermissionSourceKind | None = None
    allow_builtin_embedding: bool
    embedding_dimensions: int
    supported_modes: list[SearchMode] = Field(default_factory=list)
    query_vector_required_for_semantic_search: bool


class SearchEntityRelationRecord(BaseModel):
    relation_type: str
    entity_id: str | None = None
    name: str | None = None
    evidence: str | None = None


class SearchMentionedSourceRecord(BaseModel):
    id: str
    title: str | None = None
    summary: str | None = None
    relevance: float = 0.5


class SearchEntityRecord(BaseModel):
    entity_id: str
    name: str | None = None
    normalized_name: str | None = None
    category: str | None = None
    summary: str | None = None
    aliases: list[str] = Field(default_factory=list)
    mentioned_in_sources: list[SearchMentionedSourceRecord] = Field(default_factory=list)
    outgoing_relations: list[SearchEntityRelationRecord] = Field(default_factory=list)
    incoming_relations: list[SearchEntityRelationRecord] = Field(default_factory=list)


class SearchEntityQueryRequest(BaseModel):
    entity_id: str | None = None
    name: str | None = None
    alias: str | None = None
    limit: int = Field(default=10, ge=1, le=50)
    source_limit: int = Field(default=10, ge=0, le=50)
    relation_limit: int = Field(default=10, ge=0, le=50)

    @model_validator(mode="after")
    def _validate_query_payload(self) -> "SearchEntityQueryRequest":
        if not (self.entity_id or "").strip() and not (self.name or "").strip() and not (self.alias or "").strip():
            raise ValueError("At least one of 'entity_id', 'name', or 'alias' is required")
        return self


class SearchEntityQueryResponse(BaseModel):
    items: list[SearchEntityRecord] = Field(default_factory=list)


class SearchSourceEntityMention(BaseModel):
    entity_id: str
    name: str | None = None


class SearchSourceByKeyRequest(BaseModel):
    source_key: str = Field(min_length=1)


class SearchSourceRecord(BaseModel):
    source_key: str
    canonical_url: str
    title: str | None = None
    summary: str | None = None
    fetched_at: datetime | None = None
    content_hash: str | None = None
    mentioned_entities: list[SearchSourceEntityMention] = Field(default_factory=list)

    @field_validator("fetched_at", mode="before")
    @classmethod
    def _coerce_fetched_at(cls, value: Any) -> Any:
        if value is None or isinstance(value, datetime):
            return value
        if hasattr(value, "to_native"):
            native = value.to_native()
            if isinstance(native, datetime):
                return native
        return value


class SearchSourceDetailResponse(BaseModel):
    source: SearchSourceRecord


class SearchEntityHit(BaseModel):
    entity_id: str | None = None
    name: str | None = None
    category: str | None = None
    summary: str | None = None
    aliases: list[str] = Field(default_factory=list)
    fulltext_score: float | None = None
    vector_score: float | None = None
    hybrid_score: float | None = None


class SearchSourceHit(BaseModel):
    source_key: str
    title: str | None = None
    summary: str | None = None
    fulltext_score: float | None = None
    vector_score: float | None = None
    hybrid_score: float | None = None


class SearchRelationHit(BaseModel):
    source_key: str
    left_entity_id: str | None = None
    right_entity_id: str | None = None
    left_entity_name: str | None = None
    right_entity_name: str | None = None
    aggregated_text: str | None = None
    fulltext_score: float | None = None
    vector_score: float | None = None
    hybrid_score: float | None = None


class SearchQueryRequest(BaseModel):
    query_text: str | None = None
    query_vector: list[float] | None = None
    mode: SearchMode = SearchMode.hybrid
    entity_limit: int = Field(default=5, ge=1, le=20)
    source_limit: int = Field(default=5, ge=1, le=20)
    relation_limit: int = Field(default=5, ge=1, le=20)


class SearchQueryResponse(BaseModel):
    query_text: str | None = None
    mode: SearchMode
    query_vector_provided: bool
    capabilities: SearchApiCapabilitiesResponse
    entities: list[SearchEntityHit] = Field(default_factory=list)
    sources: list[SearchSourceHit] = Field(default_factory=list)
    relations: list[SearchRelationHit] = Field(default_factory=list)
    neighborhoods: list[dict[str, object]] = Field(default_factory=list)
