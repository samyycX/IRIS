from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langchain_openai import ChatOpenAI

from app.core.config import Settings
from app.core.logging import get_logger
from app.models import PageExtraction
from app.services.graphrag.context_builder import build_prompt_context
from app.services.graphrag.models import (
    GraphRAGContext,
    GraphRAGExtractionPayload,
    GraphRAGLinkSelectionPayload,
    GraphRAGWorkflowState,
)
from app.services.graphrag.retriever import GraphRAGRetriever
from app.services.llm.prompts import (
    build_page_extraction_prompt,
    build_related_url_filter_prompt,
    get_prompt_bundle,
)

logger = get_logger(__name__)

PAGE_TEXT_LIMIT = 12000
RELATED_URL_TEXT_LIMIT = 4000


class GraphRAGWorkflow:
    def __init__(self, settings: Settings, retriever: GraphRAGRetriever) -> None:
        self._settings = settings
        self._retriever = retriever
        self._prompts = get_prompt_bundle(settings.prompt_profile)
        self.enabled = bool(settings.openai_api_key)
        self._llm = (
            ChatOpenAI(
                model=settings.openai_model,
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                temperature=0,
            )
            if self.enabled
            else None
        )

        self._graph = self._build_graph()

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
        state = await self._graph.ainvoke(
            {
                "canonical_url": canonical_url,
                "title": title,
                "text": text,
                "content_hash": content_hash,
                "discovered_urls": discovered_urls,
                "filter_candidate_urls": filter_candidate_urls,
                "query": title or canonical_url,
            }
        )
        extraction = state["extraction"]
        selected_urls = state.get("selected_urls", discovered_urls)
        return PageExtraction(
            canonical_url=canonical_url,
            title=title,
            summary=extraction.summary,
            extracted_entities=extraction.extracted_entities,
            discovered_urls=selected_urls,
            content_hash=content_hash,
            raw_text_excerpt=text,
        )

    async def analyze_manual_seed(self, *, source_id: str, seed_text: str) -> PageExtraction:
        extraction = await self._run_extraction_chain(
            url=source_id,
            title=None,
            text=seed_text,
            context=GraphRAGContext(query=source_id),
        )
        return PageExtraction(
            canonical_url=source_id,
            summary=extraction.summary,
            extracted_entities=extraction.extracted_entities,
            discovered_urls=[],
            content_hash=source_id,
            raw_text_excerpt=seed_text,
        )

    def _build_graph(self):
        graph = StateGraph(GraphRAGWorkflowState)
        graph.add_node("retrieve_context", self._retrieve_context_node)
        graph.add_node("extract_knowledge", self._extract_knowledge_node)
        graph.add_node("rank_candidate_urls", self._rank_candidate_urls_node)
        graph.add_edge(START, "retrieve_context")
        graph.add_edge("retrieve_context", "extract_knowledge")
        graph.add_edge("extract_knowledge", "rank_candidate_urls")
        graph.add_edge("rank_candidate_urls", END)
        return graph.compile()

    async def _retrieve_context_node(
        self,
        state: GraphRAGWorkflowState,
    ) -> dict[str, Any]:
        query = state["query"]
        candidate_urls = state["discovered_urls"] if state.get("filter_candidate_urls", True) else []
        context = await self._retriever.aget_graph_context(query, candidate_urls=candidate_urls)
        return {"context": context}

    async def _extract_knowledge_node(
        self,
        state: GraphRAGWorkflowState,
    ) -> dict[str, Any]:
        extraction = await self._run_extraction_chain(
            url=state["canonical_url"],
            title=state.get("title"),
            text=state["text"],
            context=state["context"],
        )
        return {"extraction": extraction}

    async def _rank_candidate_urls_node(
        self,
        state: GraphRAGWorkflowState,
    ) -> dict[str, Any]:
        discovered_urls = state["discovered_urls"]
        if not state.get("filter_candidate_urls", True):
            return {"selected_urls": discovered_urls}
        if not discovered_urls:
            return {"selected_urls": []}

        payload = {
            "source_url": state["canonical_url"],
            "title": state.get("title"),
            "text_excerpt": _truncate_text(state["text"], RELATED_URL_TEXT_LIMIT),
            "graph_context": build_prompt_context(state["context"]),
            "candidate_urls": discovered_urls,
            "candidate_url_entity_context": state["context"].candidate_url_entity_context,
        }
        chain = self._build_related_url_chain()
        result = await chain.ainvoke(payload)
        allowed = {url.casefold(): url for url in discovered_urls}
        normalized = []
        seen = set()
        for url in result.selected_urls:
            key = url.strip().casefold()
            if key in allowed and key not in seen:
                normalized.append(allowed[key])
                seen.add(key)
        return {"selected_urls": normalized}

    async def _run_extraction_chain(
        self,
        *,
        url: str,
        title: str | None,
        text: str,
        context: GraphRAGContext,
    ) -> GraphRAGExtractionPayload:
        chain = self._build_extraction_chain()
        payload = {
            "url": url,
            "title": title,
            "text": _truncate_text(text, PAGE_TEXT_LIMIT),
            "graph_context": build_prompt_context(context),
        }
        result = await chain.ainvoke(payload)
        return GraphRAGExtractionPayload(
            summary=result.summary or (title or text[:200]),
            extracted_entities=result.extracted_entities,
        )

    def _build_extraction_chain(self):
        llm = self._require_llm()
        prompt = build_page_extraction_prompt(self._prompts)
        return prompt | llm.with_structured_output(GraphRAGExtractionPayload)

    def _build_related_url_chain(self):
        llm = self._require_llm()
        prompt = build_related_url_filter_prompt(self._prompts)
        return prompt | llm.with_structured_output(GraphRAGLinkSelectionPayload)

    def _require_llm(self) -> ChatOpenAI:
        if self._llm is None:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        return self._llm


def _truncate_text(text: str, limit: int) -> str:
    stripped = text.strip()
    return stripped[:limit] if len(stripped) > limit else stripped
