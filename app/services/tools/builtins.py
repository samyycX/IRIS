from __future__ import annotations

from typing import Any

from app.core.i18n import render_text
from app.models import PageExtraction
from app.repos.graph_repo import Neo4jGraphRepository
from app.services.crawl.canonicalizer import URLCanonicalizer
from app.services.crawl.discovery import LinkDiscoveryService
from app.services.crawl.extractor import ContentExtractor
from app.services.crawl.fetcher import HttpFetcher
from app.services.graphrag.retrievers import EntityContextRetriever
from app.services.kg.service import KnowledgeGraphService
from app.services.tools.base import BaseTool


class FetchUrlTool(BaseTool):
    name = "fetch_url"
    schema = {
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "referer": {"type": "string"},
        },
        "required": ["url"],
    }

    def __init__(
        self,
        fetcher: HttpFetcher,
        extractor: ContentExtractor,
        discovery: LinkDiscoveryService,
        canonicalizer: URLCanonicalizer,
    ) -> None:
        self._fetcher = fetcher
        self._extractor = extractor
        self._discovery = discovery
        self._canonicalizer = canonicalizer

    @property
    def description(self) -> str:
        return render_text("tool.fetch_url.description")

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        url = kwargs["url"]
        referer = kwargs.get("referer")
        final_url, status_code, html, fetch_mode = await self._fetcher.fetch(url, referer=referer)
        canonical_url = self._canonicalizer.canonicalize(final_url)
        links = self._discovery.discover(html, canonical_url)
        page = self._extractor.extract(
            url=url,
            canonical_url=canonical_url,
            status_code=status_code,
            fetch_mode=fetch_mode,
            html=html,
            links=links,
        )
        return page.model_dump()


class ExtractMainContentTool(BaseTool):
    name = "extract_main_content"
    schema = {
        "type": "object",
        "properties": {
            "html": {"type": "string"},
            "url": {"type": "string"},
            "canonical_url": {"type": "string"},
            "status_code": {"type": "integer"},
            "fetch_mode": {"type": "string"},
            "links": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["html", "url", "canonical_url", "status_code"],
    }

    def __init__(self, extractor: ContentExtractor) -> None:
        self._extractor = extractor

    @property
    def description(self) -> str:
        return render_text("tool.extract_main_content.description")

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        page = self._extractor.extract(
            url=kwargs["url"],
            canonical_url=kwargs["canonical_url"],
            status_code=kwargs["status_code"],
            fetch_mode=kwargs.get("fetch_mode", "http"),
            html=kwargs["html"],
            links=kwargs.get("links", []),
        )
        return page.model_dump()


class DiscoverLinksTool(BaseTool):
    name = "discover_links"
    schema = {
        "type": "object",
        "properties": {
            "html": {"type": "string"},
            "base_url": {"type": "string"},
        },
        "required": ["html", "base_url"],
    }

    def __init__(self, discovery: LinkDiscoveryService) -> None:
        self._discovery = discovery

    @property
    def description(self) -> str:
        return render_text("tool.discover_links.description")

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        links = self._discovery.discover(kwargs["html"], kwargs["base_url"])
        return {"links": links}


class QueryNeo4jContextTool(BaseTool):
    name = "query_neo4j_context"
    schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 5},
            "candidate_urls": {"type": "array", "items": {"type": "string"}},
            "candidate_limit": {"type": "integer", "default": 2},
        },
        "required": ["query"],
    }

    def __init__(self, graph_repo: Neo4jGraphRepository) -> None:
        self._graph_repo = graph_repo

    @property
    def description(self) -> str:
        return render_text("tool.query_neo4j_context.description")

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        matches = await EntityContextRetriever(
            graph_repo=self._graph_repo,
            limit=kwargs.get("limit", 5),
        ).aget_records(kwargs["query"])
        candidate_url_entity_context = await self._graph_repo.query_related_url_entity_context(
            kwargs.get("candidate_urls", []),
            limit_per_url=kwargs.get("candidate_limit", 2),
        )
        return {
            "matches": matches,
            "candidate_url_entity_context": candidate_url_entity_context,
        }


class UpsertKgEntityTool(BaseTool):
    name = "upsert_kg_entity"
    schema = {
        "type": "object",
        "properties": {
            "job_id": {"type": "string"},
            "extraction": {"type": "object"},
        },
        "required": ["job_id", "extraction"],
    }

    def __init__(self, kg_service: KnowledgeGraphService) -> None:
        self._kg_service = kg_service

    @property
    def description(self) -> str:
        return render_text("tool.upsert_kg_entity.description")

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        extraction = PageExtraction.model_validate(kwargs["extraction"])
        result = await self._kg_service.upsert_extraction(kwargs["job_id"], extraction)
        return result.model_dump()
