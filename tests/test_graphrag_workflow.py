import pytest

from app.core.config import Settings
from app.services.graphrag.models import GraphRAGContext
from app.services.graphrag.workflow import GraphRAGWorkflow


class _FakeRetriever:
    async def aget_graph_context(self, query: str, candidate_urls: list[str] | None = None):
        return GraphRAGContext(query=query)


async def test_analyze_manual_seed_raises_at_call_time_without_openai_api_key():
    workflow = GraphRAGWorkflow(Settings(), _FakeRetriever())

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY is not configured"):
        await workflow.analyze_manual_seed(source_id="seed-1", seed_text="示例文本")


async def test_rank_candidate_urls_raises_without_openai_api_key_when_filtering():
    workflow = GraphRAGWorkflow(Settings(), _FakeRetriever())

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY is not configured"):
        await workflow._rank_candidate_urls_node(
            {
                "canonical_url": "https://example.com/source",
                "title": "标题",
                "text": "正文",
                "context": GraphRAGContext(query="标题"),
                "discovered_urls": ["https://example.com/a"],
                "filter_candidate_urls": True,
            }
        )
