from app.models import EmbeddingSourceType, IndexQueryResult
from app.repos.graph_repo import Neo4jGraphRepository
from app.services.graphrag import EntityContextRetriever, GraphRAGRetriever


class _FakeGraphRepo(Neo4jGraphRepository):
    def __init__(self) -> None:
        self.entity_calls: list[tuple[str, int]] = []
        self.source_calls: list[tuple[str, int]] = []
        self.relation_calls: list[tuple[str, int]] = []
        self.related_url_calls: list[tuple[list[str], int]] = []
        self.neighborhood_calls: list[tuple[list[str], int, int]] = []

    async def query_entity_context(self, query: str, limit: int = 5):
        self.entity_calls.append((query, limit))
        return [
            {
                "entity_id": "entity-1",
                "name": "角色甲",
                "category": "character",
                "summary": "角色甲是地区乙的重要角色。",
                "aliases": ["ROLE_ALPHA"],
                "relation_count": 3,
                "mentioned_in_count": 2,
                "completeness_level": "rich",
            }
        ]

    async def query_source_context(self, query: str, limit: int = 5):
        self.source_calls.append((query, limit))
        return [
            IndexQueryResult(
                source_type=EmbeddingSourceType.source,
                source_key="https://example.com/wiki/region-beta",
                score=0.91,
                title="地区乙词条",
                summary="地区乙相关来源摘要。",
            )
        ]

    async def query_relation_context(self, query: str, limit: int = 5):
        self.relation_calls.append((query, limit))
        return [
            IndexQueryResult(
                source_type=EmbeddingSourceType.relation,
                source_key="entity-1::entity-2",
                score=0.88,
                left_entity_id="entity-1",
                right_entity_id="entity-2",
                left_entity_name="角色甲",
                right_entity_name="地区乙",
                aggregated_text="角色甲负责地区乙。",
            )
        ]

    async def query_related_url_entity_context(self, candidate_urls: list[str], *, limit_per_url: int = 2):
        self.related_url_calls.append((candidate_urls, limit_per_url))
        if not candidate_urls:
            return []
        return [
            {
                "url": candidate_urls[0],
                "lookup_terms": ["角色甲"],
                "matches": [
                    {
                        "entity_id": "entity-1",
                        "name": "角色甲",
                        "summary": "角色甲的图谱记录较完整。",
                        "completeness_level": "complete",
                    }
                ],
                "best_match": {
                    "entity_id": "entity-1",
                    "name": "角色甲",
                    "summary": "角色甲的图谱记录较完整。",
                    "completeness_level": "complete",
                },
            }
        ]

    async def query_entity_neighborhoods(
        self,
        entity_ids: list[str],
        *,
        hops: int = 2,
        limit_per_entity: int = 6,
    ):
        self.neighborhood_calls.append((entity_ids, hops, limit_per_entity))
        return [
            {
                "seed_entity_id": "entity-1",
                "seed_name": "角色甲",
                "neighbors": [
                    {
                        "neighbor_entity_id": "entity-2",
                        "neighbor_name": "地区乙",
                        "relation_types": ["LEADS"],
                        "hop_count": 1,
                        "evidence": "角色甲负责地区乙。",
                    }
                ],
            }
        ]


async def test_entity_context_retriever_returns_langchain_documents():
    repo = _FakeGraphRepo()
    retriever = EntityContextRetriever(graph_repo=repo, limit=3)

    documents = await retriever.ainvoke("角色甲")

    assert repo.entity_calls == [("角色甲", 3)]
    assert len(documents) == 1
    assert documents[0].metadata["kind"] == "entity"
    assert documents[0].metadata["entity_id"] == "entity-1"
    assert "实体：角色甲" in documents[0].page_content


async def test_graphrag_retriever_composes_custom_query_retrievers():
    repo = _FakeGraphRepo()
    retriever = GraphRAGRetriever(
        graph_repo=repo,
        entity_limit=2,
        source_limit=1,
        relation_limit=1,
        neighborhood_limit=4,
        neighborhood_hops=2,
    )

    context = await retriever.aget_graph_context(
        "地区乙",
        candidate_urls=["https://example.com/wiki/character-alpha"],
    )

    assert repo.entity_calls == [("地区乙", 2)]
    assert repo.source_calls == [("地区乙", 1)]
    assert repo.relation_calls == [("地区乙", 1)]
    assert repo.related_url_calls == [(["https://example.com/wiki/character-alpha"], 2)]
    assert repo.neighborhood_calls == [(["entity-1", "entity-2"], 2, 4)]
    assert context.entities[0]["entity_id"] == "entity-1"
    assert context.sources[0]["source_key"] == "https://example.com/wiki/region-beta"
    assert context.relations[0]["right_entity_id"] == "entity-2"
    assert context.candidate_url_entity_context[0]["url"] == "https://example.com/wiki/character-alpha"
    assert {document.kind for document in context.documents} == {
        "entity",
        "source",
        "relation",
        "neighborhood",
    }
