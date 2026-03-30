import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import router
from app.core.config import Settings
from app.models import (
    EmbeddingCandidate,
    EmbeddingSourceType,
    IndexJobCreateResponse,
    IndexJobMode,
    IndexJobRequest,
    IndexJobStatus,
    IndexPreparationRequest,
    IndexQueryResult,
    IndexScope,
    IndexStatusEntry,
    IndexType,
    SearchPreviewRequest,
    TextIndexCandidate,
)
from app.repos.graph_repo import _merge_entity_context_matches, _merge_index_query_results
from app.repos.index_job_store import InMemoryIndexJobStore
from app.services.indexing import IndexingService
from app.services.llm.embedding_utils import (
    build_embedding_key,
    build_entity_embedding_text,
    build_relation_embedding_text,
    build_relation_pair_key,
    build_source_embedding_text,
)


class _FakeEmbeddingClient:
    def __init__(self) -> None:
        self.enabled = True
        self.batches: list[list[str]] = []

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.batches.append(list(texts))
        return [[float(index + 1), 0.5] for index, _ in enumerate(texts)]

    async def embed_text(self, text: str) -> list[float]:
        self.batches.append([text])
        return [1.0, 0.5]


class _FakeGraphRepo:
    def __init__(
        self,
        *,
        embedding_batches: list[list[EmbeddingCandidate]] | None = None,
        fulltext_batches: list[list[TextIndexCandidate]] | None = None,
    ) -> None:
        self._embedding_batches = embedding_batches or []
        self._fulltext_batches = fulltext_batches or []
        self.embedding_upserts: list[tuple[list[EmbeddingCandidate], list[list[float]]]] = []
        self.fulltext_upserts: list[list[TextIndexCandidate]] = []

    async def prepare_embedding_candidates(self, scope, *, reindex, sample_limit):
        del scope, reindex, sample_limit
        return {"entity": 0, "source": 1, "relation": 0}, []

    async def prepare_fulltext_candidates(self, scope, *, reindex, sample_limit):
        del scope, reindex, sample_limit
        return {"entity": 1, "source": 0, "relation": 0}, []

    async def list_embedding_candidates(self, scope, *, limit, reindex, exclude_source_keys):
        del scope, limit, reindex, exclude_source_keys
        if not self._embedding_batches:
            return []
        return self._embedding_batches.pop(0)

    async def list_fulltext_candidates(self, scope, *, limit, reindex, exclude_source_keys):
        del scope, limit, reindex, exclude_source_keys
        if not self._fulltext_batches:
            return []
        return self._fulltext_batches.pop(0)

    async def upsert_embeddings(self, records, embeddings):
        self.embedding_upserts.append((records, embeddings))

    async def upsert_fulltext_documents(self, records):
        self.fulltext_upserts.append(records)

    async def mark_embedding_failed(self, record, error):
        del record, error

    async def mark_fulltext_failed(self, record, error):
        del record, error

    async def get_index_statuses(self):
        return [
            IndexStatusEntry(
                index_type=IndexType.fulltext,
                scope=IndexScope.entity,
                name="entity_fulltext_index",
                exists=True,
                state="ONLINE",
            )
        ]

    async def ensure_fulltext_indexes(self):
        return await self.get_index_statuses()

    async def rebuild_fulltext_indexes(self, scope):
        del scope
        return await self.get_index_statuses()

    async def query_preview(self, query, *, mode, entity_limit, source_limit, relation_limit):
        del mode
        return {
            "query": query,
            "entities": [{"name": query, "fulltext_score": 1.0, "vector_score": 0.5, "hybrid_score": 1.5}],
            "sources": [{"source_key": "https://example.com", "fulltext_score": 0.9, "vector_score": 0.3, "hybrid_score": 1.2}],
            "relations": [{"source_key": "a::b", "fulltext_score": 0.8, "vector_score": 0.2, "hybrid_score": 1.0}],
            "neighborhoods": [{"seed_entity_id": "role-alpha", "neighbors": []}],
        }


async def _wait_until_completed(service: IndexingService, job_id: str) -> None:
    for _ in range(20):
        job = await service.get_job(job_id)
        if job and job.status in {IndexJobStatus.completed, IndexJobStatus.failed}:
            return
        await asyncio.sleep(0)
    raise AssertionError("indexing job did not finish in time")


def test_build_source_embedding_text_uses_summary_only():
    assert build_source_embedding_text("  页面摘要  ") == "页面摘要"


def test_build_entity_embedding_text_includes_relations_and_page_hints():
    text = build_entity_embedding_text(
        name="角色甲",
        category="character",
        summary="角色甲是地区乙的负责人。",
        aliases=["ROLE_ALPHA"],
        outgoing_relations=[{"type": "LEADS", "target": "地区乙", "evidence": "页面明确说明。"}],
        incoming_relations=[{"type": "MENTIONED_BY", "source": "角色丙", "evidence": ""}],
        mentioned_in_sources=["https://example.com/wiki/role-alpha"],
        text_max_chars=4000,
    )

    assert "名称：角色甲" in text
    assert "出边关系：指向地区乙（LEADS） 证据：页面明确说明。" in text
    assert "入边关系：来自角色丙（MENTIONED_BY）" in text
    assert "提及来源：https://example.com/wiki/role-alpha" in text


def test_build_embedding_key_uses_source_prefix():
    assert build_embedding_key(EmbeddingSourceType.entity, "role-alpha") == "entity:role-alpha"
    assert build_embedding_key(EmbeddingSourceType.source, "https://example.com") == (
        "source:https://example.com"
    )
    assert build_embedding_key(EmbeddingSourceType.relation, "a::b") == "relation:a::b"


def test_build_relation_pair_key_sorts_entity_ids():
    assert build_relation_pair_key("z-entity", "a-entity") == "a-entity::z-entity"


def test_build_relation_embedding_text_includes_both_nodes_and_bundle():
    text = build_relation_embedding_text(
        left_entity_id="entity-a",
        left_entity_name="角色甲",
        right_entity_id="entity-b",
        right_entity_name="地区乙",
        relations=[
            {
                "source_name": "角色甲",
                "target_name": "地区乙",
                "type": "LEADS",
                "evidence": "页面说明角色甲负责地区乙。",
            }
        ],
        text_max_chars=4000,
    )

    assert "实体A：角色甲（entity-a）" in text
    assert "实体B：地区乙（entity-b）" in text


def test_merge_entity_context_matches_prefers_hybrid_overlap():
    merged = _merge_entity_context_matches(
        keyword_matches=[
            {
                "entity_id": "role-alpha",
                "name": "角色甲",
                "summary": "关键词命中的角色甲。",
                "aliases": [],
                "relation_count": 1,
                "completeness_score": 2,
            }
        ],
        fulltext_matches=[],
        vector_matches=[
            {
                "entity_id": "role-alpha",
                "name": "角色甲",
                "summary": "语义相近的角色甲。",
                "aliases": [],
                "relation_count": 3,
                "completeness_score": 4,
                "vector_score": 0.95,
            },
            {
                "entity_id": "region-beta",
                "name": "地区乙",
                "summary": "只有向量召回的地区乙。",
                "aliases": [],
                "relation_count": 1,
                "completeness_score": 1,
                "vector_score": 0.7,
            },
        ],
        limit=5,
    )

    assert merged[0]["entity_id"] == "role-alpha"
    assert merged[1]["entity_id"] == "region-beta"
    assert round(merged[0]["hybrid_score"], 6) == round((1 / 61) + (1 / 61), 6)
    assert round(merged[1]["hybrid_score"], 6) == round(1 / 62, 6)


def test_merge_entity_context_matches_fulltext_mode_keeps_accumulated_score():
    merged = _merge_entity_context_matches(
        keyword_matches=[],
        fulltext_matches=[
            {
                "entity_id": "siglia",
                "name": "西格莉卡",
                "fulltext_score": 1.2,
                "hybrid_score": 1.2,
            }
        ],
        vector_matches=[],
        limit=5,
        mode="fulltext",
    )

    assert len(merged) == 1
    assert merged[0]["entity_id"] == "siglia"
    assert merged[0]["fulltext_score"] == 1.2
    assert round(merged[0]["hybrid_score"], 6) == round(1 / 61, 6)


def test_merge_entity_context_matches_keeps_keyword_only_results_as_hybrid_signal():
    merged = _merge_entity_context_matches(
        keyword_matches=[
            {
                "entity_id": "principal",
                "name": "校长",
                "summary": "只有关键词命中，没有全文或向量分数。",
            }
        ],
        fulltext_matches=[],
        vector_matches=[],
        limit=5,
        mode="hybrid",
    )

    assert len(merged) == 1
    assert merged[0]["entity_id"] == "principal"
    assert merged[0].get("fulltext_score") is None
    assert merged[0].get("vector_score") is None
    assert round(merged[0]["hybrid_score"], 6) == round(1 / 61, 6)


def test_merge_index_query_results_combines_fulltext_and_vector_scores():
    merged = _merge_index_query_results(
        [IndexQueryResult(source_type=EmbeddingSourceType.source, source_key="a", fulltext_score=0.8, hybrid_score=0.8)],
        [IndexQueryResult(source_type=EmbeddingSourceType.source, source_key="a", vector_score=0.5, hybrid_score=0.5)],
        limit=5,
    )

    assert len(merged) == 1
    assert merged[0].fulltext_score == 0.8
    assert merged[0].vector_score == 0.5
    assert round(merged[0].hybrid_score or 0.0, 6) == round((1 / 61) + (1 / 61), 6)


def test_merge_index_query_results_does_not_double_count_single_fulltext_score():
    merged = _merge_index_query_results(
        [
            IndexQueryResult(
                source_type=EmbeddingSourceType.source,
                source_key="source-1",
                fulltext_score=4.7108,
                hybrid_score=4.7108,
            )
        ],
        [],
        limit=5,
        mode="hybrid",
    )

    assert len(merged) == 1
    assert round(merged[0].hybrid_score or 0.0, 6) == round(1 / 61, 6)


def test_merge_index_query_results_preserves_hybrid_score_after_vector_merge():
    merged = _merge_index_query_results(
        [
            IndexQueryResult(
                source_type=EmbeddingSourceType.relation,
                source_key="entity-a::entity-b",
                fulltext_score=1.6845,
                hybrid_score=1.6845,
            )
        ],
        [
            IndexQueryResult(
                source_type=EmbeddingSourceType.relation,
                source_key="entity-a::entity-b",
                vector_score=0.7221,
                hybrid_score=0.7221,
            )
        ],
        limit=5,
        mode="hybrid",
    )

    assert len(merged) == 1
    assert round(merged[0].hybrid_score or 0.0, 6) == round((1 / 61) + (1 / 61), 6)


async def test_indexing_service_vector_backfill_runs_to_completion():
    candidate = EmbeddingCandidate(
        source_type=EmbeddingSourceType.source,
        source_key="https://example.com/page",
        embedding_key="source:https://example.com/page",
        input_text="示例页面摘要",
        target_hash="hash-1",
    )
    graph_repo = _FakeGraphRepo(embedding_batches=[[candidate], []])
    embedding_client = _FakeEmbeddingClient()
    store = InMemoryIndexJobStore()
    service = IndexingService(Settings(OPENAI_EMBEDDING_API_KEY="key"), graph_repo, embedding_client, store)

    created = await service.create_backfill_job(
        IndexJobRequest(index_type=IndexType.vector, scope=IndexScope.source)
    )
    await _wait_until_completed(service, created.job_id)
    job = await service.get_job(created.job_id)
    await service.shutdown()

    assert job is not None
    assert job.status == IndexJobStatus.completed
    assert graph_repo.embedding_upserts


async def test_indexing_service_fulltext_backfill_runs_to_completion():
    candidate = TextIndexCandidate(
        source_type=EmbeddingSourceType.entity,
        source_key="role-alpha",
        name="角色甲",
        document_text="角色甲 全文文档",
        target_hash="fulltext-hash",
    )
    graph_repo = _FakeGraphRepo(fulltext_batches=[[candidate], []])
    embedding_client = _FakeEmbeddingClient()
    store = InMemoryIndexJobStore()
    service = IndexingService(Settings(OPENAI_EMBEDDING_API_KEY="key"), graph_repo, embedding_client, store)

    created = await service.create_backfill_job(
        IndexJobRequest(index_type=IndexType.fulltext, scope=IndexScope.entity)
    )
    await _wait_until_completed(service, created.job_id)
    job = await service.get_job(created.job_id)
    await service.shutdown()

    assert job is not None
    assert job.status == IndexJobStatus.completed
    assert graph_repo.fulltext_upserts


async def test_indexing_service_prepare_returns_counts():
    graph_repo = _FakeGraphRepo()
    embedding_client = _FakeEmbeddingClient()
    store = InMemoryIndexJobStore()
    service = IndexingService(Settings(OPENAI_EMBEDDING_API_KEY="key"), graph_repo, embedding_client, store)

    prepared = await service.prepare(
        IndexPreparationRequest(index_type=IndexType.fulltext, mode=IndexJobMode.backfill)
    )
    await service.shutdown()

    assert prepared.total_count == 1
    assert prepared.counts["entity"] == 1


class _FakeIndexingApi:
    async def create_backfill_job(self, payload):
        return IndexJobCreateResponse(job_id="job-1", status=IndexJobStatus.queued)

    async def create_reindex_job(self, payload):
        return IndexJobCreateResponse(job_id="job-2", status=IndexJobStatus.queued)

    async def prepare(self, payload: IndexPreparationRequest):
        return {
            "index_type": payload.index_type,
            "mode": payload.mode,
            "scope": payload.scope,
            "total_count": 1,
            "counts": {"entity": 1, "source": 0, "relation": 0},
            "candidates": [],
        }

    async def list_jobs(self):
        return [{"job_id": "job-1", "status": "completed"}]

    async def get_job(self, job_id):
        if job_id != "job-1":
            return None
        return {"job_id": "job-1", "status": "completed"}

    async def get_events(self, job_id):
        return [{"job_id": job_id, "message": "done"}]

    async def get_statuses(self):
        return {"indexes": []}

    async def ensure_fulltext_indexes(self):
        return {"indexes": []}

    async def rebuild_fulltext_indexes(self, scope):
        del scope
        return {"indexes": []}

    async def query_preview(self, payload: SearchPreviewRequest):
        return {
            "query": payload.query,
            "entities": [{"name": payload.query}],
            "sources": [],
            "relations": [{"source_key": "entity-a::entity-b"}],
            "neighborhoods": [],
        }


class _FakeContainer:
    def __init__(self) -> None:
        self.jobs = None
        self.indexing = _FakeIndexingApi()


def test_indexing_api_routes():
    app = FastAPI()
    app.state.container = _FakeContainer()
    app.include_router(router)
    client = TestClient(app)

    backfill = client.post("/api/indexing/backfill", json={"index_type": "vector", "scope": "source"})
    prepare = client.post("/api/indexing/prepare", json={"index_type": "fulltext", "mode": "backfill", "scope": "entity"})
    preview = client.post("/api/indexing/query-preview", json={"query": "角色甲"})
    events = client.get("/api/indexing/jobs/job-1/events")

    assert backfill.status_code == 200
    assert backfill.json()["job_id"] == "job-1"
    assert prepare.status_code == 200
    assert prepare.json()["total_count"] == 1
    assert preview.status_code == 200
    assert preview.json()["entities"][0]["name"] == "角色甲"
    assert events.status_code == 200
    assert events.json()[0]["message"] == "done"
