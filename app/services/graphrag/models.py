from __future__ import annotations

from typing import Any, TypedDict

from pydantic import BaseModel, Field

from app.models import ExtractedEntity


class GraphRAGContextDocument(BaseModel):
    kind: str
    title: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphRAGContext(BaseModel):
    query: str
    entities: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    relations: list[dict[str, Any]] = Field(default_factory=list)
    neighborhoods: list[dict[str, Any]] = Field(default_factory=list)
    candidate_url_entity_context: list[dict[str, Any]] = Field(default_factory=list)
    documents: list[GraphRAGContextDocument] = Field(default_factory=list)


class GraphRAGExtractionPayload(BaseModel):
    is_relevant: bool = True
    irrelevant_reason: str | None = None
    summary: str
    extracted_entities: list[ExtractedEntity] = Field(default_factory=list)


class GraphRAGLinkSelectionPayload(BaseModel):
    selected_urls: list[str] = Field(default_factory=list)


class GraphRAGWorkflowState(TypedDict, total=False):
    canonical_url: str
    title: str | None
    knowledge_theme: str
    text: str
    content_hash: str
    discovered_urls: list[str]
    filter_candidate_urls: bool
    query: str
    context: GraphRAGContext
    extraction: GraphRAGExtractionPayload
    selected_urls: list[str]
