from __future__ import annotations

from time import monotonic
from typing import TYPE_CHECKING

from app.core.logging import get_logger
from app.models import PageExtraction
from app.services.llm.client import LLMClient

if TYPE_CHECKING:
    from app.services.tools.executor import ToolExecutor

logger = get_logger(__name__)


class LlmOrchestrator:
    def __init__(self, llm_client: LLMClient, tool_executor: ToolExecutor) -> None:
        self._llm_client = llm_client
        self._tool_executor = tool_executor

    async def analyze_page(
        self,
        *,
        canonical_url: str,
        title: str | None,
        text: str,
        content_hash: str,
        discovered_urls: list[str],
        filter_candidate_urls: bool = True,
    ) -> PageExtraction:
        logger.info(
            "llm_analyze_page_start",
            canonical_url=canonical_url,
            title=title,
            text_length=len(text),
            discovered_url_count=len(discovered_urls),
            filter_candidate_urls=filter_candidate_urls,
            content_hash=content_hash,
        )
        context_started_at = monotonic()
        logger.info(
            "llm_context_query_start",
            canonical_url=canonical_url,
            query=title or canonical_url,
            candidate_url_count=len(discovered_urls if filter_candidate_urls else []),
        )
        context = await self._tool_executor.execute(
            "query_neo4j_context",
            query=title or canonical_url,
            candidate_urls=discovered_urls if filter_candidate_urls else [],
        )
        context_matches = context.get("matches", [])
        candidate_url_entity_context = context.get("candidate_url_entity_context", [])
        logger.info(
            "llm_context_query_complete",
            canonical_url=canonical_url,
            elapsed_ms=_elapsed_ms(context_started_at),
            context_match_count=len(context_matches),
            candidate_url_entity_context_count=len(candidate_url_entity_context),
        )
        summary_started_at = monotonic()
        logger.info(
            "llm_extract_knowledge_start",
            canonical_url=canonical_url,
            context_match_count=len(context_matches),
            text_length=len(text),
        )
        summary, entities = await self._llm_client.extract_knowledge(
            url=canonical_url,
            title=title,
            text=text,
            context=context_matches,
        )
        logger.info(
            "llm_extract_knowledge_complete",
            canonical_url=canonical_url,
            elapsed_ms=_elapsed_ms(summary_started_at),
            summary_length=len(summary),
            entity_count=len(entities),
        )
        selected_urls = discovered_urls
        if filter_candidate_urls:
            filter_started_at = monotonic()
            logger.info(
                "llm_filter_related_urls_start",
                canonical_url=canonical_url,
                candidate_url_count=len(discovered_urls),
                candidate_url_entity_context_count=len(candidate_url_entity_context),
            )
            selected_urls = await self._llm_client.filter_related_urls(
                source_url=canonical_url,
                title=title,
                text=text,
                context=context_matches,
                candidate_urls=discovered_urls,
                candidate_url_entity_context=candidate_url_entity_context,
            )
            logger.info(
                "llm_filter_related_urls_complete",
                canonical_url=canonical_url,
                elapsed_ms=_elapsed_ms(filter_started_at),
                selected_url_count=len(selected_urls),
            )
        logger.info(
            "llm_analyze_page_complete",
            canonical_url=canonical_url,
            summary_length=len(summary),
            entity_count=len(entities),
            selected_url_count=len(selected_urls),
        )
        return PageExtraction(
            canonical_url=canonical_url,
            title=title,
            summary=summary,
            extracted_entities=entities,
            discovered_urls=selected_urls,
            content_hash=content_hash,
            raw_text_excerpt=text,
        )

    async def analyze_manual_seed(self, *, source_id: str, seed_text: str) -> PageExtraction:
        started_at = monotonic()
        logger.info(
            "llm_analyze_manual_seed_start",
            source_id=source_id,
            seed_text_length=len(seed_text),
        )
        summary, entities = await self._llm_client.extract_knowledge(
            url=source_id,
            title=None,
            text=seed_text,
            context=[],
        )
        logger.info(
            "llm_analyze_manual_seed_complete",
            source_id=source_id,
            elapsed_ms=_elapsed_ms(started_at),
            summary_length=len(summary),
            entity_count=len(entities),
        )
        return PageExtraction(
            canonical_url=source_id,
            summary=summary,
            extracted_entities=entities,
            discovered_urls=[],
            content_hash=source_id,
            raw_text_excerpt=seed_text,
        )


def _elapsed_ms(started_at: float) -> int:
    return int((monotonic() - started_at) * 1000)
