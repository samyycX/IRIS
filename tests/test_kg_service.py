from app.models import ExtractedEntity, GraphUpdateResult, PageExtraction
from app.services.kg.service import KnowledgeGraphService


class _FakeGraphRepo:
    def __init__(self) -> None:
        self.received_extraction: PageExtraction | None = None
        self.merge_queries: list[tuple[str, list[str]]] = []

    async def query_entity_merge_candidates(self, name: str, aliases: list[str]):
        self.merge_queries.append((name, aliases))
        return []

    async def upsert_source_and_entities(self, job_id: str, extraction: PageExtraction) -> GraphUpdateResult:
        self.received_extraction = extraction
        return GraphUpdateResult(created_sources=[extraction.canonical_url])


class _FakeLLMClient:
    def __init__(self) -> None:
        self.merged_entities: list[ExtractedEntity] = []

    async def merge_entity(self, *, incoming_entity: ExtractedEntity, existing_entities: list[dict]):
        self.merged_entities.append(incoming_entity)
        return incoming_entity


async def test_upsert_extraction_filters_low_score_entities_without_defaulting_missing_scores():
    repo = _FakeGraphRepo()
    llm_client = _FakeLLMClient()
    service = KnowledgeGraphService(repo, llm_client)
    extraction = PageExtraction(
        canonical_url="https://example.com/page",
        title="示例页面",
        summary="页面摘要",
        extracted_entities=[
            ExtractedEntity(
                name="低分实体",
                category="character",
                summary="轻微提及",
                aliases=[],
                mentioned_in_score=0.01,
                relations=[],
            ),
            ExtractedEntity(
                name="缺省分数实体",
                category="character",
                summary="默认分数",
                aliases=[],
                relations=[],
            ),
            ExtractedEntity(
                name="高分实体",
                category="character",
                summary="重点实体",
                aliases=[],
                mentioned_in_score=0.9,
                relations=[],
            ),
        ],
        discovered_urls=[],
        content_hash="hash",
        raw_text_excerpt="正文",
    )

    result = await service.upsert_extraction("job-1", extraction)

    assert result.created_sources == ["https://example.com/page"]
    assert repo.received_extraction is not None
    assert [entity.name for entity in repo.received_extraction.extracted_entities] == [
        "缺省分数实体",
        "高分实体",
    ]
    assert [entity.mentioned_in_score for entity in repo.received_extraction.extracted_entities] == [None, 0.9]
    assert [entity.name for entity in llm_client.merged_entities] == ["缺省分数实体", "高分实体"]
