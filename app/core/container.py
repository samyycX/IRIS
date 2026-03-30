from __future__ import annotations

from app.core.config import BootstrapSettings, Settings
from app.repos import (
    InMemoryIndexJobStore,
    Neo4jGraphRepository,
    Neo4jJobStore,
    Neo4jMigrationManager,
    UrlHistoryRepository,
)
from app.services.crawl import (
    ContentExtractor,
    CrawlPipeline,
    HttpFetcher,
    LinkDiscoveryService,
    URLCanonicalizer,
)
from app.services.app_config import AppConfigService
from app.services.graphrag import GraphRAGRetriever, GraphRAGWorkflow
from app.services.jobs import JobService
from app.services.kg import KnowledgeGraphService
from app.services.local_data import LocalDataStore
from app.services.llm import EmbeddingClient, LLMClient
from app.services.llm.orchestrator import LlmOrchestrator
from app.services.indexing import IndexingService
from app.services.tools import (
    DiscoverLinksTool,
    ExtractMainContentTool,
    FetchUrlTool,
    ToolExecutor,
    ToolRegistry,
    UpsertKgEntityTool,
)


class ServiceContainer:
    def __init__(self, settings: BootstrapSettings) -> None:
        self.bootstrap_settings = settings
        self.settings: Settings | None = None
        self.local_data = LocalDataStore(settings.data_root)
        self.config_service = AppConfigService(settings, self.local_data)

        self.event_store: Neo4jJobStore | None = None
        self.embedding_client: EmbeddingClient | None = None
        self.graph_repo: Neo4jGraphRepository | None = None
        self.migrations: Neo4jMigrationManager | None = None
        self.index_job_store: InMemoryIndexJobStore | None = None
        self.canonicalizer: URLCanonicalizer | None = None
        self.fetcher: HttpFetcher | None = None
        self.extractor: ContentExtractor | None = None
        self.discovery: LinkDiscoveryService | None = None
        self.url_history: UrlHistoryRepository | None = None
        self.llm_client: LLMClient | None = None
        self.kg_service: KnowledgeGraphService | None = None
        self.graphrag_retriever: GraphRAGRetriever | None = None
        self.graphrag_workflow: GraphRAGWorkflow | None = None
        self.tool_registry: ToolRegistry | None = None
        self.tool_executor: ToolExecutor | None = None
        self.llm_orchestrator: LlmOrchestrator | None = None
        self.indexing: IndexingService | None = None
        self.pipeline: CrawlPipeline | None = None
        self.jobs: JobService | None = None

    async def initialize(self) -> None:
        await self.reload_runtime()

    async def close(self) -> None:
        await self._close_runtime_components()

    async def reload_runtime(self) -> None:
        await self._close_runtime_components()
        runtime_settings = self.config_service.get_runtime_settings()
        self._build_runtime_components(runtime_settings)
        self._register_tools()
        await self.graph_repo.ensure_constraints()
        await self.migrations.run_migrations()
        await self.jobs.mark_interrupted_jobs()
        await self.indexing.initialize()

    def _register_tools(self) -> None:
        self.tool_registry.register(FetchUrlTool(self.fetcher, self.extractor, self.discovery))
        self.tool_registry.register(ExtractMainContentTool(self.extractor))
        self.tool_registry.register(DiscoverLinksTool(self.discovery))
        self.tool_registry.register(UpsertKgEntityTool(self.kg_service))

    def _build_runtime_components(self, settings: Settings) -> None:
        self.settings = settings
        self.event_store = Neo4jJobStore(settings)
        self.embedding_client = EmbeddingClient(settings)
        self.graph_repo = Neo4jGraphRepository(settings, embedding_client=self.embedding_client)
        self.migrations = Neo4jMigrationManager(settings)
        self.index_job_store = InMemoryIndexJobStore()
        self.canonicalizer = URLCanonicalizer()
        self.fetcher = HttpFetcher(settings)
        self.extractor = ContentExtractor()
        self.discovery = LinkDiscoveryService(
            self.canonicalizer,
            set(settings.allowed_domains),
        )
        self.url_history = UrlHistoryRepository(
            self.graph_repo,
            ttl_days=settings.visited_url_ttl_days,
        )
        self.llm_client = LLMClient(settings)
        self.kg_service = KnowledgeGraphService(self.graph_repo, self.llm_client)
        self.graphrag_retriever = GraphRAGRetriever(graph_repo=self.graph_repo)
        self.graphrag_workflow = GraphRAGWorkflow(settings, self.graphrag_retriever)
        self.tool_registry = ToolRegistry()
        self.tool_executor = ToolExecutor(self.tool_registry)
        self.llm_orchestrator = LlmOrchestrator(self.graphrag_workflow)
        self.indexing = IndexingService(
            settings=settings,
            graph_repo=self.graph_repo,
            embedding_client=self.embedding_client,
            job_store=self.index_job_store,
        )
        self.pipeline = CrawlPipeline(
            event_store=self.event_store,
            graph_repo=self.graph_repo,
            url_history=self.url_history,
            canonicalizer=self.canonicalizer,
            tool_executor=self.tool_executor,
            llm_orchestrator=self.llm_orchestrator,
            indexing_service=self.indexing,
            crawl_concurrency=settings.crawl_concurrency,
            llm_timeout_seconds=settings.llm_timeout_seconds,
            skip_history_seen_urls=settings.skip_history_seen_urls,
            auto_backfill_indexes_after_crawl=settings.auto_backfill_indexes_after_crawl,
        )
        self.jobs = JobService(settings, self.event_store, self.pipeline)

    async def _close_runtime_components(self) -> None:
        if self.indexing is not None:
            await self.indexing.shutdown()
        if self.jobs is not None:
            await self.jobs.shutdown()
        if self.fetcher is not None:
            await self.fetcher.close()
        if self.migrations is not None:
            await self.migrations.close()
        if self.graph_repo is not None:
            await self.graph_repo.close()
        if self.event_store is not None:
            await self.event_store.close()
