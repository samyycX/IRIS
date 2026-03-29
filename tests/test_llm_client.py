import json

from app.core.config import Settings
from app.models import ExtractedEntity
from app.services.llm.client import LLMClient
from app.services.llm.prompts import GENERIC_PAGE_EXTRACTION_PROMPT, PAGE_EXTRACTION_PROMPT


def test_fallback_merge_entity_keeps_richer_existing_and_new_information():
    client = LLMClient(Settings())
    incoming = ExtractedEntity(
        name="角色甲",
        category="resonator",
        summary="角色甲是示例知识域中的关键角色，担任地区乙负责人。",
        aliases=["ROLE_ALPHA"],
        relations=[
            {
                "type": "MENTORS",
                "target": "角色丙",
                "evidence": "角色甲指导角色丙。",
            }
        ],
        deleted_relations=[
            {
                "type": "LEADS",
                "target": "地区乙",
                "reason": "页面明确说明角色甲已不再担任地区乙负责人。",
            }
        ],
    )
    existing_entities = [
        {
            "name": "角色甲",
            "category": "unknown",
            "summary": "角色甲与地区乙有关。",
            "aliases": ["地区乙负责人"],
            "outgoing_relations": [
                {
                    "type": "LEADS",
                    "target": "地区乙",
                    "evidence": "角色甲是地区乙负责人。",
                },
                {
                    "type": "LOCATED_IN",
                    "target": "地区乙",
                    "evidence": "角色甲常驻地区乙。",
                },
            ],
        }
    ]

    merged = client._fallback_merge_entity(
        incoming_entity=incoming,
        existing_entities=existing_entities,
    )

    assert merged.name == "角色甲"
    assert merged.category == "resonator"
    assert merged.summary == "角色甲是示例知识域中的关键角色，担任地区乙负责人。"
    assert merged.aliases == ["ROLE_ALPHA", "地区乙负责人"]
    assert merged.relations == [
        {
            "type": "MENTORS",
            "target": "角色丙",
            "evidence": "角色甲指导角色丙。",
        },
        {
            "type": "LOCATED_IN",
            "target": "地区乙",
            "evidence": "角色甲常驻地区乙。",
        },
    ]
    assert merged.deleted_relations == [
        {
            "type": "LEADS",
            "target": "地区乙",
            "reason": "页面明确说明角色甲已不再担任地区乙负责人。",
        }
    ]


def test_fallback_filter_related_urls_prefers_context_related_pages():
    client = LLMClient(Settings())

    selected = client._fallback_filter_related_urls(
        source_url="https://wiki.example.com/wiki/%E5%9C%B0%E5%8C%BA%E4%B9%99",
        title="地区乙",
        text="地区乙的负责人是角色甲，角色甲长期驻守地区乙。",
        context=[{"name": "角色甲", "aliases": ["ROLE_ALPHA"]}],
        candidate_urls=[
            "https://wiki.example.com/news/1.4-preview",
            "https://wiki.example.com/wiki/%E8%A7%92%E8%89%B2%E7%94%B2",
            "https://wiki.example.com/user/profile",
        ],
    )

    assert selected == [
        "https://wiki.example.com/wiki/%E8%A7%92%E8%89%B2%E7%94%B2",
        "https://wiki.example.com/news/1.4-preview",
    ]


def test_fallback_filter_related_urls_skips_complete_entity_detail_pages():
    client = LLMClient(Settings())

    selected = client._fallback_filter_related_urls(
        source_url="https://wiki.example.com/wiki/%E5%9C%B0%E5%8C%BA%E4%B9%99",
        title="地区乙",
        text="地区乙的负责人是角色甲，角色甲长期驻守地区乙。",
        context=[{"name": "角色甲", "aliases": ["ROLE_ALPHA"]}],
        candidate_urls=[
            "https://wiki.example.com/wiki/%E8%A7%92%E8%89%B2%E7%94%B2",
            "https://wiki.example.com/news/1.4-preview",
        ],
        candidate_url_entity_context=[
            {
                "url": "https://wiki.example.com/wiki/%E8%A7%92%E8%89%B2%E7%94%B2",
                "best_match": {
                    "name": "角色甲",
                    "category": "resonator",
                    "summary": "角色甲是地区乙负责人，也是示例知识域中的关键角色，拥有较完整的身份、阵营与关系描述。",
                    "aliases": ["ROLE_ALPHA", "地区乙负责人"],
                    "relation_count": 6,
                    "mentioned_in_count": 4,
                    "completeness_score": 8,
                    "completeness_level": "complete",
                },
            }
        ],
    )

    assert selected == ["https://wiki.example.com/news/1.4-preview"]


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


async def test_extract_knowledge_truncates_text_before_sending_to_llm():
    client = LLMClient(Settings(openai_api_key="test-key"))
    completions = _FakeCompletions(['{"summary":"ok","extracted_entities":[]}'])
    client._client = _FakeOpenAIClient(completions)

    text = "a" * 13000
    summary, entities = await client.extract_knowledge(
        url="https://example.com/page",
        title="标题",
        text=text,
        context=[],
    )

    payload = json.loads(completions.requests[0]["messages"][1]["content"])

    assert summary == "ok"
    assert entities == []
    assert len(payload["text"]) == 12000
    assert payload["text"] == text[:12000]


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


