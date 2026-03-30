from app.models import ExtractedEntity, PageExtraction
from app.services.llm.orchestrator import LlmOrchestrator


class _FakeGraphRAGWorkflow:
    def __init__(self) -> None:
        self.page_calls: list[dict] = []
        self.manual_calls: list[dict] = []

    async def analyze_page(self, **kwargs):
        self.page_calls.append(kwargs)
        return PageExtraction(
            canonical_url=kwargs["canonical_url"],
            title=kwargs["title"],
            summary="页面摘要",
            extracted_entities=[
                ExtractedEntity(
                    name="角色甲",
                    category="character",
                    summary="角色甲摘要",
                    aliases=["ROLE_ALPHA"],
                    mentioned_in_score=0.9,
                    relations=[],
                )
            ],
            discovered_urls=list(reversed(kwargs["discovered_urls"])),
            content_hash=kwargs["content_hash"],
            raw_text_excerpt=kwargs["text"],
        )

    async def analyze_manual_seed(self, **kwargs):
        self.manual_calls.append(kwargs)
        return PageExtraction(
            canonical_url=kwargs["source_id"],
            summary="手工输入摘要",
            extracted_entities=[],
            discovered_urls=[],
            content_hash=kwargs["source_id"],
            raw_text_excerpt=kwargs["seed_text"],
        )


async def test_analyze_page_preserves_full_raw_text():
    workflow = _FakeGraphRAGWorkflow()
    orchestrator = LlmOrchestrator(workflow)
    text = "正文" * 800

    extraction = await orchestrator.analyze_page(
        canonical_url="https://example.com/page",
        title="示例页面",
        text=text,
        content_hash="hash",
        discovered_urls=["https://example.com/related", "https://example.com/other"],
    )

    assert extraction.raw_text_excerpt == text
    assert extraction.extracted_entities[0].mentioned_in_score == 0.9
    assert extraction.discovered_urls == [
        "https://example.com/other",
        "https://example.com/related",
    ]
    assert workflow.page_calls == [
        {
            "canonical_url": "https://example.com/page",
            "title": "示例页面",
            "text": text,
            "content_hash": "hash",
            "discovered_urls": ["https://example.com/related", "https://example.com/other"],
            "filter_candidate_urls": True,
        }
    ]


async def test_analyze_page_can_skip_related_url_filtering():
    workflow = _FakeGraphRAGWorkflow()
    orchestrator = LlmOrchestrator(workflow)

    extraction = await orchestrator.analyze_page(
        canonical_url="https://example.com/page",
        title="示例页面",
        text="正文",
        content_hash="hash",
        discovered_urls=["https://example.com/related", "https://example.com/other"],
        filter_candidate_urls=False,
    )

    assert extraction.discovered_urls == [
        "https://example.com/other",
        "https://example.com/related",
    ]
    assert workflow.page_calls == [
        {
            "canonical_url": "https://example.com/page",
            "title": "示例页面",
            "text": "正文",
            "content_hash": "hash",
            "discovered_urls": ["https://example.com/related", "https://example.com/other"],
            "filter_candidate_urls": False,
        }
    ]


async def test_analyze_manual_seed_preserves_full_raw_text():
    workflow = _FakeGraphRAGWorkflow()
    orchestrator = LlmOrchestrator(workflow)
    seed_text = "手工输入" * 500

    extraction = await orchestrator.analyze_manual_seed(
        source_id="manual://seed",
        seed_text=seed_text,
    )

    assert extraction.raw_text_excerpt == seed_text
    assert workflow.manual_calls == [
        {
            "source_id": "manual://seed",
            "seed_text": seed_text,
        }
    ]
