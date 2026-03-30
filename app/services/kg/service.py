from __future__ import annotations

from app.models import ExtractedEntity, GraphUpdateResult, PageExtraction
from app.repos.graph_repo import Neo4jGraphRepository
from app.services.llm.client import LLMClient
from app.services.llm.pinyin import expand_aliases_with_pinyin

MIN_MENTIONED_IN_SCORE = 0.05


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
            prepared_entity = _prepare_entity_for_source_linking(entity)
            if prepared_entity is None:
                continue
            existing_entities = await self._graph_repo.query_entity_merge_candidates(
                prepared_entity.name,
                prepared_entity.aliases,
            )
            merged_entity = await self._llm_client.merge_entity(
                incoming_entity=prepared_entity,
                existing_entities=existing_entities,
            )
            merged_entities.append(
                merged_entity.model_copy(update={"mentioned_in_score": prepared_entity.mentioned_in_score})
            )

        merged_extraction = extraction.model_copy(
            update={"extracted_entities": merged_entities},
        )
        return await self._graph_repo.upsert_source_and_entities(job_id, merged_extraction)


def _prepare_entity_for_source_linking(entity: ExtractedEntity) -> ExtractedEntity | None:
    score = _normalize_mentioned_in_score(entity.mentioned_in_score)
    if score is not None and score < MIN_MENTIONED_IN_SCORE:
        return None
    normalized_aliases = expand_aliases_with_pinyin([entity.name, *entity.aliases])
    aliases = [alias for alias in normalized_aliases if alias.casefold() != entity.name.casefold()]
    return entity.model_copy(
        update={
            "mentioned_in_score": score,
            "aliases": aliases,
        }
    )


def _normalize_mentioned_in_score(score: float | None) -> float | None:
    if score is None:
        return None
    return max(0.0, min(1.0, float(score)))
