from app.models import (
    GraphUpdateResult,
    IndexJobCreateResponse,
    IndexJobRequest,
    IndexJobStatus,
    IndexScope,
    IndexType,
    JobInputType,
    JobRequest,
    PageExtraction,
)
from app.repos.job_store import InMemoryJobStore
from app.services.crawl.canonicalizer import URLCanonicalizer
from app.services.crawl.pipeline import CrawlPipeline
from app.services.tools.base import BaseTool
from app.services.tools.executor import ToolExecutor
from app.services.tools.registry import ToolRegistry


class _FakeUrlHistory:
    async def has_seen(self, url: str) -> bool:
        return False


class _FetchUrlTool(BaseTool):
    name = "fetch_url"
    description = "fetch page"
    schema = {}

    async def execute(self, **kwargs):
        return {
            "url": kwargs["url"],
            "canonical_url": kwargs["url"],
            "title": "测试页面",
            "status_code": 200,
            "fetch_mode": "http",
            "html": "<html></html>",
            "text": "这是一段和主题无关的页面正文",
            "links": ["https://example.com/next"],
            "content_hash": "page-hash",
        }


class _UpsertKgEntityTool(BaseTool):
    name = "upsert_kg_entity"
    description = "upsert graph"
    schema = {}

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def execute(self, **kwargs):
        self.calls.append(kwargs)
        return GraphUpdateResult().model_dump()


class _FakeLlmOrchestrator:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def analyze_page(self, **kwargs):
        self.calls.append(kwargs)
        return PageExtraction(
            canonical_url=kwargs["canonical_url"],
            title=kwargs["title"],
            is_relevant=False,
            irrelevant_reason="页面主要内容和配置主题无关",
            summary="",
            extracted_entities=[],
            discovered_urls=[],
            content_hash=kwargs["content_hash"],
            raw_text_excerpt=kwargs["text"],
        )

    async def analyze_manual_seed(self, **kwargs):
        raise AssertionError("manual seed flow should not be used in this test")


class _RelevantLlmOrchestrator:
    async def analyze_page(self, **kwargs):
        return PageExtraction(
            canonical_url=kwargs["canonical_url"],
            title=kwargs["title"],
            is_relevant=True,
            summary="页面与主题相关",
            extracted_entities=[],
            discovered_urls=[],
            content_hash=kwargs["content_hash"],
            raw_text_excerpt=kwargs["text"],
        )

    async def analyze_manual_seed(self, **kwargs):
        raise AssertionError("manual seed flow should not be used in this test")


class _FakeIndexingService:
    def __init__(self) -> None:
        self.requests: list[IndexJobRequest] = []

    async def create_graph_update_backfill_jobs(self, scope=IndexScope.all):
        self.requests.extend(
            [
                IndexJobRequest(index_type=IndexType.fulltext, scope=scope),
                IndexJobRequest(index_type=IndexType.vector, scope=scope),
            ]
        )
        return [
            (
                IndexType.fulltext,
                IndexJobCreateResponse(job_id="fulltext-job", status=IndexJobStatus.queued),
            ),
            (
                IndexType.vector,
                IndexJobCreateResponse(job_id="vector-job", status=IndexJobStatus.queued),
            ),
        ], []


async def test_crawl_pipeline_skips_irrelevant_pages_before_graph_upsert():
    store = InMemoryJobStore()
    request = JobRequest(
        input_type=JobInputType.url,
        url="https://example.com/start",
        max_depth=1,
        max_pages=5,
    )
    job = await store.create_job(request, max_depth=1, max_pages=5)
    registry = ToolRegistry()
    upsert_tool = _UpsertKgEntityTool()
    registry.register(_FetchUrlTool())
    registry.register(upsert_tool)
    orchestrator = _FakeLlmOrchestrator()
    pipeline = CrawlPipeline(
        event_store=store,
        graph_repo=object(),
        url_history=_FakeUrlHistory(),
        canonicalizer=URLCanonicalizer(),
        tool_executor=ToolExecutor(registry),
        llm_orchestrator=orchestrator,
    )

    result = await pipeline.run_job(job.job_id, request)
    events = await store.get_events(job.job_id)
    final_job = await store.get_job(job.job_id)

    assert result == GraphUpdateResult()
    assert len(orchestrator.calls) == 1
    assert upsert_tool.calls == []
    assert final_job is not None
    assert final_job.graph_update == GraphUpdateResult()
    assert final_job.visited_count == 1
    assert final_job.queued_count == 0
    assert any(event.message == "页面与当前主题无关，跳过入库和后续扩展" for event in events)


async def test_crawl_pipeline_triggers_auto_index_backfill_after_graph_changes():
    store = InMemoryJobStore()
    request = JobRequest(
        input_type=JobInputType.url,
        url="https://example.com/start",
        max_depth=0,
        max_pages=1,
    )
    job = await store.create_job(request, max_depth=0, max_pages=1)
    registry = ToolRegistry()
    upsert_tool = _UpsertKgEntityTool()
    registry.register(_FetchUrlTool())
    registry.register(upsert_tool)
    indexing_service = _FakeIndexingService()
    pipeline = CrawlPipeline(
        event_store=store,
        graph_repo=object(),
        url_history=_FakeUrlHistory(),
        canonicalizer=URLCanonicalizer(),
        tool_executor=ToolExecutor(registry),
        llm_orchestrator=_RelevantLlmOrchestrator(),
        indexing_service=indexing_service,
        auto_backfill_indexes_after_crawl=True,
    )
    upsert_tool.calls.clear()

    async def _execute_with_changes(**kwargs):
        upsert_tool.calls.append(kwargs)
        return GraphUpdateResult(
            updated_entities=["角色甲"],
            created_relationships=1,
        ).model_dump()

    upsert_tool.execute = _execute_with_changes

    result = await pipeline.run_job(job.job_id, request)
    events = await store.get_events(job.job_id)

    assert result.updated_entities == ["角色甲"]
    assert result.created_relationships == 1
    assert [(payload.index_type, payload.scope) for payload in indexing_service.requests] == [
        (IndexType.fulltext, IndexScope.all),
        (IndexType.vector, IndexScope.all),
    ]
    assert any(event.message == "检测到图谱变更，开始自动触发索引补全任务" for event in events)
    assert any(event.message == "自动索引补全任务已处理" for event in events)
