from __future__ import annotations

from time import monotonic

from app.core.logging import get_logger
from app.models import PageExtraction
from app.services.graphrag.workflow import GraphRAGWorkflow

logger = get_logger(__name__)


class LlmOrchestrator:
    def __init__(self, workflow: GraphRAGWorkflow) -> None:
        self._workflow = workflow

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
        started_at = monotonic()
        logger.info(
            "llm_analyze_page_start",
            canonical_url=canonical_url,
            title=title,
            text_length=len(text),
            discovered_url_count=len(discovered_urls),
            filter_candidate_urls=filter_candidate_urls,
            content_hash=content_hash,
        )
        extraction = await self._workflow.analyze_page(
            canonical_url=canonical_url,
            title=title,
            text=text,
            content_hash=content_hash,
            discovered_urls=discovered_urls,
            filter_candidate_urls=filter_candidate_urls,
        )
        logger.info(
            "llm_analyze_page_complete",
            canonical_url=canonical_url,
            elapsed_ms=_elapsed_ms(started_at),
            is_relevant=extraction.is_relevant,
            irrelevant_reason=extraction.irrelevant_reason,
            summary_length=len(extraction.summary),
            entity_count=len(extraction.extracted_entities),
            selected_url_count=len(extraction.discovered_urls),
        )
        return extraction

    async def analyze_manual_seed(self, *, source_id: str, seed_text: str) -> PageExtraction:
        started_at = monotonic()
        logger.info(
            "llm_analyze_manual_seed_start",
            source_id=source_id,
            seed_text_length=len(seed_text),
        )
        extraction = await self._workflow.analyze_manual_seed(source_id=source_id, seed_text=seed_text)
        logger.info(
            "llm_analyze_manual_seed_complete",
            source_id=source_id,
            elapsed_ms=_elapsed_ms(started_at),
            summary_length=len(extraction.summary),
            entity_count=len(extraction.extracted_entities),
        )
        return extraction


def _elapsed_ms(started_at: float) -> int:
    return int((monotonic() - started_at) * 1000)
