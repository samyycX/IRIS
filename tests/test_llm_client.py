import json
import sys
import types

import pytest

from app.core.config import Settings
from app.models import ExtractedEntity
from app.services.llm import EmbeddingClient
from app.services.llm.client import LLMClient
from app.services.llm.prompts import GENERIC_PAGE_EXTRACTION_PROMPT, PAGE_EXTRACTION_PROMPT


async def test_llm_client_raises_at_call_time_without_openai_api_key():
    client = LLMClient(Settings())

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY is not configured"):
        await client.extract_knowledge(
            url="https://example.com/page",
            title="标题",
            text="正文",
            context=[],
        )


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, contents: list[str]) -> None:
        self._contents = contents
        self.requests: list[dict] = []

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        return _FakeResponse(self._contents.pop(0))


class _FakeChat:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.completions = completions


class _FakeOpenAIClient:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.chat = _FakeChat(completions)


class _FakeEmbeddings:
    def __init__(self, data: list[list[float]]) -> None:
        self._data = data
        self.requests: list[list[str]] = []

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        self.requests.append(list(texts))
        return self._data


class _TestEmbeddingClient(EmbeddingClient):
    def __init__(self, settings: Settings, embeddings: _FakeEmbeddings) -> None:
        self._fake_embeddings = embeddings
        super().__init__(settings)

    def _build_client(self):
        return self._fake_embeddings


class _FakeStructuredChain:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error
        self.requests: list[dict] = []

    async def ainvoke(self, payload: dict):
        self.requests.append(payload)
        if self._error is not None:
            raise self._error
        return self._result


class _TestLLMClient(LLMClient):
    def __init__(self, settings: Settings, merge_chain: _FakeStructuredChain) -> None:
        self._fake_merge_chain = merge_chain
        super().__init__(settings)

    def _build_merge_chain(self):
        return self._fake_merge_chain


async def test_extract_knowledge_truncates_text_before_sending_to_llm():
    client = LLMClient(Settings(openai_api_key="test-key"))
    completions = _FakeCompletions(['{"summary":"ok","extracted_entities":[]}'])
    client._client = _FakeOpenAIClient(completions)

    text = "a" * 60000
    summary, entities = await client.extract_knowledge(
        url="https://example.com/page",
        title="标题",
        text=text,
        context=[],
    )

    payload = json.loads(completions.requests[0]["messages"][1]["content"])

    assert summary == "ok"
    assert entities == []
    assert len(payload["text"]) == 50000
    assert payload["text"] == text[:50000]


async def test_extract_knowledge_raises_on_invalid_json_response():
    client = LLMClient(Settings(openai_api_key="test-key"))
    completions = _FakeCompletions(["not-json"])
    client._client = _FakeOpenAIClient(completions)

    with pytest.raises(ValueError, match="extract_knowledge"):
        await client.extract_knowledge(
            url="https://example.com/page",
            title="标题",
            text="正文",
            context=[],
        )


async def test_extract_knowledge_uses_wuwa_prompt_profile_by_default():
    client = LLMClient(Settings(openai_api_key="test-key"))
    completions = _FakeCompletions(['{"summary":"ok","extracted_entities":[]}'])
    client._client = _FakeOpenAIClient(completions)

    await client.extract_knowledge(
        url="https://example.com/page",
        title="标题",
        text="正文",
        context=[],
    )

    assert completions.requests[0]["messages"][0]["content"] == PAGE_EXTRACTION_PROMPT.strip()


async def test_extract_knowledge_can_switch_to_generic_prompt_profile():
    client = LLMClient(Settings(openai_api_key="test-key", prompt_profile="generic"))
    completions = _FakeCompletions(['{"summary":"ok","extracted_entities":[]}'])
    client._client = _FakeOpenAIClient(completions)

    await client.extract_knowledge(
        url="https://example.com/page",
        title="标题",
        text="正文",
        context=[],
    )

    assert completions.requests[0]["messages"][0]["content"] == GENERIC_PAGE_EXTRACTION_PROMPT.strip()


async def test_filter_related_urls_uses_context_and_preserves_llm_priority_order():
    client = LLMClient(Settings(openai_api_key="test-key"))
    completions = _FakeCompletions(
        ['{"selected_urls":["https://example.com/b","https://example.com/a","https://example.com/missing"]}']
    )
    client._client = _FakeOpenAIClient(completions)

    text = "b" * 5000
    selected = await client.filter_related_urls(
        source_url="https://example.com/source",
        title="标题",
        text=text,
        context=[{"name": "角色甲", "aliases": ["ROLE_ALPHA"]}],
        candidate_urls=["https://example.com/a", "https://example.com/b"],
        candidate_url_entity_context=[
            {
                "url": "https://example.com/a",
                "lookup_terms": ["角色甲"],
                "best_match": {
                    "name": "角色甲",
                    "category": "resonator",
                    "summary": "角色甲的图谱记录已经很完整。",
                    "aliases": ["ROLE_ALPHA"],
                    "relation_count": 5,
                    "mentioned_in_count": 3,
                    "completeness_score": 7,
                    "completeness_level": "complete",
                },
            }
        ],
    )

    payload = json.loads(completions.requests[0]["messages"][1]["content"])

    assert selected == ["https://example.com/b", "https://example.com/a"]
    assert payload["context"] == [{"name": "角色甲", "aliases": ["ROLE_ALPHA"]}]
    assert payload["candidate_url_entity_context"] == [
        {
            "url": "https://example.com/a",
            "lookup_terms": ["角色甲"],
            "best_match": {
                "name": "角色甲",
                "category": "resonator",
                "summary": "角色甲的图谱记录已经很完整。",
                "aliases": ["ROLE_ALPHA"],
                "relation_count": 5,
                "mentioned_in_count": 3,
                "completeness_score": 7,
                "completeness_level": "complete",
            },
        }
    ]
    assert len(payload["text_excerpt"]) == 4000
    assert payload["text_excerpt"] == text[:4000]


async def test_merge_entity_raises_on_invalid_json_response():
    client = _TestLLMClient(
        Settings(openai_api_key="test-key"),
        _FakeStructuredChain(error=ValueError("invalid payload")),
    )

    with pytest.raises(ValueError, match="merge_entity"):
        await client.merge_entity(
            incoming_entity=ExtractedEntity(
                name="角色甲",
                category="resonator",
                summary="角色甲",
                aliases=[],
                mentioned_in_score=1.0,
                relations=[],
            ),
            existing_entities=[
                {
                    "name": "角色甲",
                    "category": "resonator",
                    "summary": "已有记录",
                    "aliases": [],
                    "outgoing_relations": [],
                }
            ],
        )


async def test_merge_entity_uses_structured_output_chain():
    result = ExtractedEntity(
        name="角色甲",
        category="resonator",
        summary="合并后的实体摘要",
        aliases=["ROLE_ALPHA"],
        mentioned_in_score=1.0,
        relations=[{"type": "LEADS", "target": "地区乙", "evidence": "页面明确说明。"}],
    )
    chain = _FakeStructuredChain(result=result)
    client = _TestLLMClient(Settings(openai_api_key="test-key"), chain)
    incoming = ExtractedEntity(
        name="角色甲",
        category="resonator",
        summary="新摘要",
        aliases=[],
        mentioned_in_score=1.0,
        relations=[],
    )

    merged = await client.merge_entity(
        incoming_entity=incoming,
        existing_entities=[{"name": "角色甲", "summary": "已有摘要"}],
    )

    assert merged == result
    assert json.loads(chain.requests[0]["payload"]) == {
        "incoming_entity": incoming.model_dump(),
        "existing_entities": [{"name": "角色甲", "summary": "已有摘要"}],
    }


async def test_embedding_client_uses_dedicated_embedding_configuration():
    embeddings = _FakeEmbeddings([[0.1, 0.2, 0.3]])
    client = _TestEmbeddingClient(
        Settings(
            openai_embedding_api_key="embedding-key",
            openai_embedding_base_url="https://emb.example.com/v1",
            openai_embedding_model="mebedding-large",
            embedding_dimensions=1024,
        ),
        embeddings,
    )

    vector = await client.embed_text("示例摘要")

    assert vector == [0.1, 0.2, 0.3]
    assert embeddings.requests[0] == ["示例摘要"]


def test_embedding_client_builds_langchain_embeddings_with_dedicated_configuration(monkeypatch):
    captured_kwargs = {}

    class _FakeLangChainEmbeddings:
        def __init__(self, **kwargs) -> None:
            captured_kwargs.update(kwargs)

        async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
            return [[0.1] for _ in texts]

    monkeypatch.setitem(
        sys.modules,
        "langchain_openai",
        types.SimpleNamespace(OpenAIEmbeddings=_FakeLangChainEmbeddings),
    )

    client = EmbeddingClient(
        Settings(
            openai_embedding_api_key="embedding-key",
            openai_embedding_base_url="https://emb.example.com/v1",
            openai_embedding_model="mebedding-large",
            embedding_dimensions=1024,
        )
    )

    assert client.enabled is True
    assert captured_kwargs == {
        "model": "mebedding-large",
        "api_key": "embedding-key",
        "base_url": "https://emb.example.com/v1",
        "dimensions": 1024,
    }


