from __future__ import annotations

from app.core.config import Settings
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
from app.services.graphrag import GraphRAGRetriever, GraphRAGWorkflow
from app.services.jobs import JobService
from app.services.kg import KnowledgeGraphService
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
    def __init__(self, settings: Settings) -> None:
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
            settings.allowed_domains,
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
        self.pipeline = CrawlPipeline(
            event_store=self.event_store,
            graph_repo=self.graph_repo,
            url_history=self.url_history,
            canonicalizer=self.canonicalizer,
            tool_executor=self.tool_executor,
            llm_orchestrator=self.llm_orchestrator,
            crawl_concurrency=settings.crawl_concurrency,
            llm_timeout_seconds=settings.llm_timeout_seconds,
            skip_history_seen_urls=settings.skip_history_seen_urls,
        )
        self.jobs = JobService(settings, self.event_store, self.pipeline)
        self.indexing = IndexingService(
            settings=settings,
            graph_repo=self.graph_repo,
            embedding_client=self.embedding_client,
            job_store=self.index_job_store,
        )

    async def initialize(self) -> None:
        self.url_history = UrlHistoryRepository(
            self.graph_repo,
            ttl_days=self.settings.visited_url_ttl_days,
        )
        self.kg_service = KnowledgeGraphService(self.graph_repo, self.llm_client)
        self.graphrag_retriever = GraphRAGRetriever(graph_repo=self.graph_repo)
        self.graphrag_workflow = GraphRAGWorkflow(self.settings, self.graphrag_retriever)
        self.tool_registry = ToolRegistry()
        self.tool_executor = ToolExecutor(self.tool_registry)
        self.llm_orchestrator = LlmOrchestrator(self.graphrag_workflow)
        self.pipeline = CrawlPipeline(
            event_store=self.event_store,
            graph_repo=self.graph_repo,
            url_history=self.url_history,
            canonicalizer=self.canonicalizer,
            tool_executor=self.tool_executor,
            llm_orchestrator=self.llm_orchestrator,
            crawl_concurrency=self.settings.crawl_concurrency,
            llm_timeout_seconds=self.settings.llm_timeout_seconds,
            skip_history_seen_urls=self.settings.skip_history_seen_urls,
        )
        self.jobs = JobService(self.settings, self.event_store, self.pipeline)
        self.indexing = IndexingService(
            settings=self.settings,
            graph_repo=self.graph_repo,
            embedding_client=self.embedding_client,
            job_store=self.index_job_store,
        )
        self._register_tools()
        await self.graph_repo.ensure_constraints()
        await self.migrations.run_migrations()
        await self.jobs.mark_interrupted_jobs()
        await self.indexing.initialize()

    async def close(self) -> None:
        await self.indexing.shutdown()
        await self.jobs.shutdown()
        await self.fetcher.close()
        await self.migrations.close()
        await self.graph_repo.close()

    def _register_tools(self) -> None:
        self.tool_registry.register(FetchUrlTool(self.fetcher, self.extractor, self.discovery))
        self.tool_registry.register(ExtractMainContentTool(self.extractor))
        self.tool_registry.register(DiscoverLinksTool(self.discovery))
        self.tool_registry.register(UpsertKgEntityTool(self.kg_service))
