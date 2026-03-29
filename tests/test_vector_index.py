import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import router
from app.core.config import Settings
from app.models import (
    EmbeddingCandidate,
    EmbeddingSourceType,
    VectorIndexJobCreateResponse,
    VectorIndexJobMode,
    VectorIndexJobRequest,
    VectorIndexJobStatus,
    VectorIndexQueryPreviewRequest,
    VectorIndexScope,
)
from app.repos.graph_repo import _merge_entity_context_matches
from app.repos.vector_index_job_store import InMemoryVectorIndexJobStore
from app.services.llm.embedding_utils import (
    build_embedding_key,
    build_entity_embedding_text,
    build_page_embedding_text,
    build_relation_embedding_text,
    build_relation_pair_key,
)
from app.services.vector_index import VectorIndexService


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
    def __init__(self, candidates: list[list[EmbeddingCandidate]] | None = None) -> None:
        self._candidate_batches = candidates or []
        self.upsert_calls: list[tuple[list[EmbeddingCandidate], list[list[float]]]] = []
        self.failed_calls: list[tuple[str, str]] = []

    async def list_embedding_candidates(self, scope, *, limit, reindex, exclude_source_keys):
        if not self._candidate_batches:
            return []
        return self._candidate_batches.pop(0)

    async def upsert_embeddings(self, records, embeddings):
        self.upsert_calls.append((records, embeddings))

    async def mark_embedding_failed(self, record, error):
        self.failed_calls.append((record.source_key, error))

    async def query_preview(self, query, *, entity_limit, page_limit):
        return {
            "entities": [{"name": query, "limit": entity_limit}],
            "pages": [{"source_key": "https://example.com/page", "score": page_limit}],
            "relations": [{"source_key": "entity-a::entity-b", "score": 0.9}],
        }


async def _wait_until_completed(service: VectorIndexService, job_id: str) -> None:
    for _ in range(20):
        job = await service.get_job(job_id)
        if job and job.status in {VectorIndexJobStatus.completed, VectorIndexJobStatus.failed}:
            return
        await asyncio.sleep(0)
    raise AssertionError("vector index job did not finish in time")


def test_build_page_embedding_text_uses_summary_only():
    assert build_page_embedding_text("  页面摘要  ") == "页面摘要"


def test_build_entity_embedding_text_includes_relations_and_page_hints():
    text = build_entity_embedding_text(
        name="角色甲",
        category="character",
        summary="角色甲是地区乙的负责人。",
        aliases=["ROLE_ALPHA"],
        outgoing_relations=[{"type": "LEADS", "target": "地区乙", "evidence": "页面明确说明。"}],
        incoming_relations=[{"type": "MENTIONED_BY", "source": "角色丙", "evidence": ""}],
        mentioned_in_pages=["https://example.com/wiki/role-alpha"],
        text_max_chars=4000,
    )

    assert "名称：角色甲" in text
    assert "出边关系：指向地区乙（LEADS） 证据：页面明确说明。" in text
    assert "入边关系：来自角色丙（MENTIONED_BY）" in text
    assert "提及页面：https://example.com/wiki/role-alpha" in text


def test_build_embedding_key_uses_source_prefix():
    assert build_embedding_key(EmbeddingSourceType.entity, "role-alpha") == "entity:role-alpha"
    assert build_embedding_key(EmbeddingSourceType.page, "https://example.com") == (
        "page:https://example.com"
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
            },
            {
                "source_name": "地区乙",
                "target_name": "角色甲",
                "type": "TRUSTS",
                "evidence": "",
            },
        ],
        text_max_chars=4000,
    )

    assert "实体A：角色甲（entity-a）" in text
    assert "实体B：地区乙（entity-b）" in text
    assert "角色甲 -> 地区乙（LEADS） 证据：页面说明角色甲负责地区乙。" in text
    assert "地区乙 -> 角色甲（TRUSTS）" in text


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


async def test_vector_index_service_backfill_runs_to_completion():
    candidate = EmbeddingCandidate(
        source_type=EmbeddingSourceType.page,
        source_key="https://example.com/page",
        embedding_key="page:https://example.com/page",
        input_text="示例页面摘要",
        target_hash="hash-1",
    )
    graph_repo = _FakeGraphRepo(candidates=[[candidate], []])
    embedding_client = _FakeEmbeddingClient()
    store = InMemoryVectorIndexJobStore()
    service = VectorIndexService(
        Settings(OPENAI_EMBEDDING_API_KEY="key"),
        graph_repo,
        embedding_client,
        store,
    )

    created = await service.create_backfill_job(VectorIndexJobRequest(scope=VectorIndexScope.page))
    await _wait_until_completed(service, created.job_id)
    job = await service.get_job(created.job_id)
    events = await service.get_events(created.job_id)
    await service.shutdown()

    assert job is not None
    assert job.status == VectorIndexJobStatus.completed
    assert job.scanned_count == 1
    assert job.synced_count == 1
    assert graph_repo.upsert_calls
    assert events[-1].stage.value == "completed"


async def test_vector_index_service_can_process_relation_candidates():
    candidate = EmbeddingCandidate(
        source_type=EmbeddingSourceType.relation,
        source_key="entity-a::entity-b",
        embedding_key="relation:entity-a::entity-b",
        input_text="关系聚合文本",
        target_hash="relation-hash",
    )
    graph_repo = _FakeGraphRepo(candidates=[[candidate], []])
    embedding_client = _FakeEmbeddingClient()
    store = InMemoryVectorIndexJobStore()
    service = VectorIndexService(
        Settings(OPENAI_EMBEDDING_API_KEY="key"),
        graph_repo,
        embedding_client,
        store,
    )

    created = await service.create_backfill_job(
        VectorIndexJobRequest(scope=VectorIndexScope.relation)
    )
    await _wait_until_completed(service, created.job_id)
    job = await service.get_job(created.job_id)
    await service.shutdown()

    assert job is not None
    assert job.status == VectorIndexJobStatus.completed
    assert graph_repo.upsert_calls[0][0][0].source_type == EmbeddingSourceType.relation


async def test_vector_index_service_rejects_conflicting_active_job():
    graph_repo = _FakeGraphRepo(candidates=[[]])
    embedding_client = _FakeEmbeddingClient()
    store = InMemoryVectorIndexJobStore()
    service = VectorIndexService(
        Settings(OPENAI_EMBEDDING_API_KEY="key"),
        graph_repo,
        embedding_client,
        store,
    )
    active = await store.create_job(
        mode=VectorIndexJobMode.backfill,
        request=VectorIndexJobRequest(scope=VectorIndexScope.all),
        batch_size=16,
    )
    await store.update_job(active.job_id, status=VectorIndexJobStatus.running)
    try:
        await service.create_reindex_job(VectorIndexJobRequest(scope=VectorIndexScope.entity))
    except Exception as exc:  # noqa: BLE001
        assert "409" in str(getattr(exc, "status_code", "409")) or getattr(exc, "status_code", 409) == 409
    else:
        raise AssertionError("expected conflict error")
    finally:
        await service.shutdown()


class _FakeVectorIndexApi:
    async def create_backfill_job(self, payload):
        return VectorIndexJobCreateResponse(job_id="job-1", status=VectorIndexJobStatus.queued)

    async def create_reindex_job(self, payload):
        return VectorIndexJobCreateResponse(job_id="job-2", status=VectorIndexJobStatus.queued)

    async def get_job(self, job_id):
        if job_id != "job-1":
            return None
        return {
            "job_id": "job-1",
            "status": "completed",
        }

    async def get_events(self, job_id):
        return [{"job_id": job_id, "message": "done"}]

    async def query_preview(self, payload: VectorIndexQueryPreviewRequest):
        return {
            "entities": [{"name": payload.query}],
            "pages": [],
            "relations": [{"source_key": "entity-a::entity-b"}],
        }


class _FakeContainer:
    def __init__(self) -> None:
        self.jobs = None
        self.vector_index = _FakeVectorIndexApi()


def test_vector_index_api_routes():
    app = FastAPI()
    app.state.container = _FakeContainer()
    app.include_router(router)
    client = TestClient(app)

    backfill = client.post("/api/vector-index/backfill", json={"scope": "page"})
    preview = client.post("/api/vector-index/query-preview", json={"query": "角色甲"})
    events = client.get("/api/vector-index/jobs/job-1/events")

    assert backfill.status_code == 200
    assert backfill.json()["job_id"] == "job-1"
    assert preview.status_code == 200
    assert preview.json()["entities"][0]["name"] == "角色甲"
    assert preview.json()["relations"][0]["source_key"] == "entity-a::entity-b"
    assert events.status_code == 200
    assert events.json()[0]["message"] == "done"
