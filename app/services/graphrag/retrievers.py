from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any, TypeVar

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, Field

from app.repos.graph_repo import Neo4jGraphRepository
from app.services.graphrag.context_builder import build_context_documents
from app.services.graphrag.models import GraphRAGContext

ContextRecordT = TypeVar("ContextRecordT")


def context_to_documents(context: GraphRAGContext) -> list[Document]:
    documents = context.documents or build_context_documents(context)
    return [
        Document(
            page_content=document.content,
            metadata={
                "kind": document.kind,
                "title": document.title,
                **document.metadata,
            },
        )
        for document in documents
    ]


class _BaseGraphContextRetriever(BaseRetriever, ABC):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    graph_repo: Neo4jGraphRepository = Field(exclude=True)

    async def aget_context(self, query: str) -> GraphRAGContext:
        context = self._build_context(query, await self.aget_records(query))
        if not context.documents:
            context.documents = build_context_documents(context)
        return context

    @abstractmethod
    async def aget_records(self, query: str) -> ContextRecordT:
        raise NotImplementedError

    @abstractmethod
    def _build_context(self, query: str, records: ContextRecordT) -> GraphRAGContext:
        raise NotImplementedError

    async def _aget_relevant_documents(
        self,
        query: str,
        *,
        run_manager: Any = None,
    ) -> list[Document]:
        del run_manager
        return context_to_documents(await self.aget_context(query))

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


class EntityContextRetriever(_BaseGraphContextRetriever):
    limit: int = 5

    async def aget_records(self, query: str) -> list[dict[str, Any]]:
        return await self.graph_repo.query_entity_context(query, limit=self.limit)

    def _build_context(self, query: str, records: list[dict[str, Any]]) -> GraphRAGContext:
        return GraphRAGContext(query=query, entities=records)


class SourceContextRetriever(_BaseGraphContextRetriever):
    limit: int = 5

    async def aget_records(self, query: str) -> list[dict[str, Any]]:
        results = await self.graph_repo.query_source_context(query, limit=self.limit)
        return [result.model_dump(mode="json") for result in results]

    def _build_context(self, query: str, records: list[dict[str, Any]]) -> GraphRAGContext:
        return GraphRAGContext(query=query, sources=records)


class RelationContextRetriever(_BaseGraphContextRetriever):
    limit: int = 5

    async def aget_records(self, query: str) -> list[dict[str, Any]]:
        results = await self.graph_repo.query_relation_context(query, limit=self.limit)
        return [result.model_dump(mode="json") for result in results]

    def _build_context(self, query: str, records: list[dict[str, Any]]) -> GraphRAGContext:
        return GraphRAGContext(query=query, relations=records)
