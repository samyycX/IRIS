from __future__ import annotations

from app.models import GraphUpdateResult, PageExtraction
from app.repos.graph_repo import Neo4jGraphRepository
from app.services.llm.client import LLMClient


class KnowledgeGraphService:
    def __init__(
        self,
        graph_repo: Neo4jGraphRepository,
        llm_client: LLMClient,
    ) -> None:
        self._graph_repo = graph_repo
        self._llm_client = llm_client

    async def upsert_extraction(self, job_id: str, extraction: PageExtraction) -> GraphUpdateResult:
        merged_entities = []
        for entity in extraction.extracted_entities:
            existing_entities = await self._graph_repo.query_entity_merge_candidates(
                entity.name,
                entity.aliases,
            )
            merged_entities.append(
                await self._llm_client.merge_entity(
                    incoming_entity=entity,
                    existing_entities=existing_entities,
                )
            )

        merged_extraction = extraction.model_copy(
            update={"extracted_entities": merged_entities},
        )
        return await self._graph_repo.upsert_page_and_entities(job_id, merged_extraction)
