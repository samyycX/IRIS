from app.services.llm.orchestrator import LlmOrchestrator


class _FakeLLMClient:
    def __init__(self) -> None:
        self.last_filter_kwargs = None

    async def extract_knowledge(self, **kwargs):
        return "页面摘要", []

    async def filter_related_urls(self, **kwargs):
        self.last_filter_kwargs = kwargs
        return list(reversed(kwargs["candidate_urls"]))


class _FakeToolExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, name: str, **kwargs):
        self.calls.append((name, kwargs))
        return {"matches": [{"name": "角色甲", "aliases": ["ROLE_ALPHA"]}]}


async def test_analyze_page_preserves_full_raw_text():
    llm_client = _FakeLLMClient()
    tool_executor = _FakeToolExecutor()
    orchestrator = LlmOrchestrator(
        llm_client=llm_client,
        tool_executor=tool_executor,
    )
    text = "正文" * 800

    extraction = await orchestrator.analyze_page(
        canonical_url="https://example.com/page",
        title="示例页面",
        text=text,
        content_hash="hash",
        discovered_urls=["https://example.com/related", "https://example.com/other"],
    )

    assert extraction.raw_text_excerpt == text
    assert extraction.discovered_urls == [
        "https://example.com/other",
        "https://example.com/related",
    ]
    assert llm_client.last_filter_kwargs == {
        "source_url": "https://example.com/page",
        "title": "示例页面",
        "text": text,
        "context": [{"name": "角色甲", "aliases": ["ROLE_ALPHA"]}],
        "candidate_urls": ["https://example.com/related", "https://example.com/other"],
        "candidate_url_entity_context": [],
    }
    assert tool_executor.calls == [
        (
            "query_neo4j_context",
            {
                "query": "示例页面",
                "candidate_urls": ["https://example.com/related", "https://example.com/other"],
            },
        )
    ]


async def test_analyze_page_can_skip_related_url_filtering():
    llm_client = _FakeLLMClient()
    tool_executor = _FakeToolExecutor()
    orchestrator = LlmOrchestrator(
        llm_client=llm_client,
        tool_executor=tool_executor,
    )

    extraction = await orchestrator.analyze_page(
        canonical_url="https://example.com/page",
        title="示例页面",
        text="正文",
        content_hash="hash",
        discovered_urls=["https://example.com/related", "https://example.com/other"],
        filter_candidate_urls=False,
    )

    assert extraction.discovered_urls == [
        "https://example.com/related",
        "https://example.com/other",
    ]
    assert llm_client.last_filter_kwargs is None
    assert tool_executor.calls == [
        (
            "query_neo4j_context",
            {
                "query": "示例页面",
                "candidate_urls": [],
            },
        )
    ]


async def test_analyze_manual_seed_preserves_full_raw_text():
    orchestrator = LlmOrchestrator(
        llm_client=_FakeLLMClient(),
        tool_executor=_FakeToolExecutor(),
    )
    seed_text = "手工输入" * 500

    extraction = await orchestrator.analyze_manual_seed(
        source_id="manual://seed",
        seed_text=seed_text,
    )

    assert extraction.raw_text_excerpt == seed_text
