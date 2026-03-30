from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, Field

from app.repos.graph_repo import Neo4jGraphRepository
from app.services.graphrag.context_builder import build_context_documents
from app.services.graphrag.models import GraphRAGContext
from app.services.graphrag.retrievers import (
    EntityContextRetriever,
    RelationContextRetriever,
    SourceContextRetriever,
    context_to_documents,
)


class GraphRAGRetriever(BaseRetriever):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    graph_repo: Neo4jGraphRepository = Field(exclude=True)
    entity_retriever: EntityContextRetriever | None = Field(default=None, exclude=True)
    source_retriever: SourceContextRetriever | None = Field(default=None, exclude=True)
    relation_retriever: RelationContextRetriever | None = Field(default=None, exclude=True)
    entity_limit: int = 5
    source_limit: int = 5
    relation_limit: int = 5
    neighborhood_limit: int = 6
    neighborhood_hops: int = 2

    async def aget_graph_context(
        self,
        query: str,
        *,
        candidate_urls: list[str] | None = None,
    ) -> GraphRAGContext:
        entities, sources, relations, candidate_url_entity_context = await asyncio.gather(
            self._get_entity_retriever().aget_records(query),
            self._get_source_retriever().aget_records(query),
            self._get_relation_retriever().aget_records(query),
            self.graph_repo.query_related_url_entity_context(
                candidate_urls or [],
                limit_per_url=2,
            ),
        )

        seed_entity_ids = _collect_seed_entity_ids(entities, relations)[: self.entity_limit]
        neighborhoods = await self.graph_repo.query_entity_neighborhoods(
            seed_entity_ids,
            hops=self.neighborhood_hops,
            limit_per_entity=self.neighborhood_limit,
        )

        context = GraphRAGContext(
            query=query,
            entities=entities,
            sources=sources,
            relations=relations,
            neighborhoods=neighborhoods,
            candidate_url_entity_context=candidate_url_entity_context,
        )
        if not context.documents:
            context.documents = build_context_documents(context)
        return context

    async def _aget_relevant_documents(
        self,
        query: str,
        *,
        run_manager: Any = None,
    ) -> list[Document]:
        del run_manager
        context = await self.aget_graph_context(query)
        return context_to_documents(context)

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: Any = None,
    ) -> list[Document]:
        del run_manager
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._aget_relevant_documents(query))
        raise RuntimeError("Use the async retriever path inside an active event loop.")

    def _get_entity_retriever(self) -> EntityContextRetriever:
        return self.entity_retriever or EntityContextRetriever(
            graph_repo=self.graph_repo,
            limit=self.entity_limit,
        )

    def _get_source_retriever(self) -> SourceContextRetriever:
        return self.source_retriever or SourceContextRetriever(
            graph_repo=self.graph_repo,
            limit=self.source_limit,
        )

    def _get_relation_retriever(self) -> RelationContextRetriever:
        return self.relation_retriever or RelationContextRetriever(
            graph_repo=self.graph_repo,
            limit=self.relation_limit,
        )


def _collect_seed_entity_ids(
    entities: list[dict[str, Any]],
    relations: list[dict[str, Any]],
) -> list[str]:
    seed_entity_ids: list[str] = []
    for entity in entities:
        entity_id = str(entity.get("entity_id") or "").strip()
        if entity_id and entity_id not in seed_entity_ids:
            seed_entity_ids.append(entity_id)
    for relation in relations:
        for entity_id in (relation.get("left_entity_id"), relation.get("right_entity_id")):
            candidate_id = str(entity_id or "").strip()
            if candidate_id and candidate_id not in seed_entity_ids:
                seed_entity_ids.append(candidate_id)
    return seed_entity_ids
