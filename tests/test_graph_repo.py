from datetime import datetime, timezone

from app.core.config import Settings
from app.models import (
    ExtractedEntity,
    GraphUpdateResult,
    IndexScope,
    JobInputType,
    JobStatus,
    JobSummary,
    PageExtraction,
)
from app.repos.graph_repo import (
    Neo4jGraphRepository,
    _build_related_url_lookup_terms,
    _build_job_change_log_text,
    _build_source_change_log,
    _build_source_modification_summary,
    _build_job_summary_text,
    _build_relation_target_summary,
    _build_entity_payload,
    _calculate_entity_completeness_score,
    _classify_entity_completeness,
    _build_search_terms,
    _entity_id,
    _escape_fulltext_query,
    _relation_types_are_similar,
    _read_index_score,
    _select_canonical_match,
)


def test_entity_id_is_stable_across_category_changes():
    assert _entity_id("角色甲") == "角色甲"
    assert _entity_id("Role-Alpha / 角色甲") == "role_alpha_角色甲"


def test_select_canonical_match_prefers_known_entity_over_unknown_duplicate():
    matches = [
        {
            "entity_id": "unknown_角色甲",
            "name": "角色甲",
            "category": "unknown",
            "summary": "",
            "aliases": [],
        },
        {
            "entity_id": "character_角色甲",
            "name": "角色甲",
            "category": "character",
            "summary": "地区乙相关角色",
            "aliases": ["RoleAlpha"],
        },
    ]

    selected = _select_canonical_match(matches, preferred_entity_id="角色甲")

    assert selected is not None
    assert selected["entity_id"] == "character_角色甲"


def test_build_entity_payload_merges_aliases_and_promotes_richer_data():
    matches = [
        {
            "entity_id": "unknown_角色甲",
            "name": "角色甲",
            "category": "unknown",
            "summary": "",
            "aliases": ["RoleAlpha"],
        },
        {
            "entity_id": "character_角色甲",
            "name": "角色甲",
            "category": "character",
            "summary": "角色甲是地区乙的重要角色。",
            "aliases": ["地区乙负责人"],
        },
    ]
    entity = ExtractedEntity(
        name="角色甲",
        category="resonator",
        summary="角色甲是示例知识域中的重要角色。",
        aliases=["ROLE_ALPHA", "负责人"],
        relations=[],
    )

    payload = _build_entity_payload(matches, entity, canonical_entity_id="character_角色甲")

    assert payload["name"] == "角色甲"
    assert payload["normalized_name"] == "角色甲"
    assert payload["category"] == "resonator"
    assert payload["summary"] == "角色甲是示例知识域中的重要角色。"
    assert payload["aliases"] == ["RoleAlpha", "地区乙负责人", "负责人"]


def test_build_entity_payload_keeps_existing_summary_when_incoming_placeholder_is_empty():
    matches = [
        {
            "entity_id": "region_beta",
            "name": "地区乙",
            "category": "region",
            "summary": "地区乙是示例知识域中的重要地区，由负责人统辖。",
            "aliases": ["RegionBeta"],
        }
    ]
    placeholder = ExtractedEntity(
        name="地区乙",
        category="unknown",
        summary="",
        aliases=[],
        relations=[],
    )

    payload = _build_entity_payload(matches, placeholder, canonical_entity_id="region_beta")

    assert payload["name"] == "地区乙"
    assert payload["category"] == "region"
    assert payload["summary"] == "地区乙是示例知识域中的重要地区，由负责人统辖。"
    assert payload["aliases"] == ["RegionBeta"]


def test_build_relation_target_summary_prefers_evidence_and_has_non_empty_fallback():
    assert (
        _build_relation_target_summary(
            source_name="角色甲",
            relation_type="LEADS",
            evidence="角色甲是地区乙负责人。",
        )
        == "角色甲是地区乙负责人。"
    )
    assert _build_relation_target_summary(
        source_name="角色甲",
        relation_type="LEADS",
        evidence="  ",
    ) == "在关系 LEADS 中与 角色甲 有关联。"


def test_build_search_terms_covers_lookup_and_normalized_forms():
    terms = _build_search_terms("Role-Alpha / 角色甲", [" RoleAlpha "])

    assert "role-alpha / 角色甲" in terms
    assert "role_alpha_角色甲" in terms
    assert "rolealpha" in terms


def test_escape_fulltext_query_escapes_lucene_special_characters():
    escaped = _escape_fulltext_query(' 鸣潮/典故: "设定" && || ')

    assert escaped == '鸣潮\\/典故\\: \\"设定\\" \\&\\& \\|\\|'


def test_relation_types_are_similar_for_long_near_duplicate_labels():
    assert _relation_types_are_similar("地区乙组织核心成员", "地区乙组织的核心成员")
    assert not _relation_types_are_similar("朋友", "女朋友")


def test_related_url_lookup_terms_extracts_entity_slug_from_url():
    terms = _build_related_url_lookup_terms("https://wiki.example.com/character/%E8%A7%92%E8%89%B2%E7%94%B2")

    assert terms == ["角色甲"]


def test_entity_completeness_score_marks_rich_entities_as_complete():
    score = _calculate_entity_completeness_score(
        summary="角色甲是地区乙负责人，也是示例知识域中的重要角色，拥有较完整的身份、势力、经历、能力与人物关系描述。" * 3,
        alias_count=3,
        relation_count=6,
        mentioned_in_count=4,
    )

    assert score >= 7
    assert _classify_entity_completeness(score) == "complete"


def test_read_index_score_accepts_fulltext_alias_or_score():
    assert _read_index_score({"fulltext_score": 1.25}, "fulltext_score") == 1.25
    assert _read_index_score({"score": 0.75}, "fulltext_score") == 0.75


class _FakeTx:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def run(self, query: str, **kwargs):
        self.calls.append((query, kwargs))


class _FakeSingleResult:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    async def single(self):
        return self._payload


class _FakeTxWithSingleResult(_FakeTx):
    def __init__(self, payload: dict) -> None:
        super().__init__()
        self._payload = payload

    async def run(self, query: str, **kwargs):
        self.calls.append((query, kwargs))
        return _FakeSingleResult(self._payload)


class _FakeTxWithSequentialSingleResults(_FakeTx):
    def __init__(self, payloads: list[dict]) -> None:
        super().__init__()
        self._payloads = list(payloads)

    async def run(self, query: str, **kwargs):
        self.calls.append((query, kwargs))
        payload = self._payloads.pop(0) if self._payloads else {}
        return _FakeSingleResult(payload)


class _FakeRecord:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def data(self) -> dict:
        return self._payload


class _FakeResultStream:
    def __init__(self, payloads: list[dict]) -> None:
        self._payloads = payloads
        self._index = 0

    def __aiter__(self):
        self._index = 0
        return self

    async def __anext__(self):
        if self._index >= len(self._payloads):
            raise StopAsyncIteration
        payload = self._payloads[self._index]
        self._index += 1
        return _FakeRecord(payload)


class _FakeSession:
    def __init__(self, payloads: list[dict]) -> None:
        self._payloads = payloads
        self.run_calls: list[tuple[str, dict | None, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def run(self, query: str, parameters: dict | None = None, **kwargs):
        self.run_calls.append((query, parameters, kwargs))
        return _FakeResultStream(self._payloads)


class _FakeDriver:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def session(self):
        return self._session


async def test_upsert_source_tx_writes_full_raw_text_excerpt_for_replacement():
    tx = _FakeTx()
    raw_text = "完整正文" * 600
    extraction = PageExtraction(
        canonical_url="https://example.com/page",
        title="示例页面",
        summary="摘要",
        extracted_entities=[],
        discovered_urls=[],
        content_hash="hash",
        raw_text_excerpt=raw_text,
    )

    await Neo4jGraphRepository._upsert_source_tx(tx, "job-1", extraction, "hash")

    query, params = tx.calls[0]

    assert "source.raw_text_excerpt = $raw_text_excerpt" in query
    assert params["raw_text_excerpt"] == raw_text


async def test_query_read_records_passes_query_param_via_parameters_dict():
    session = _FakeSession([{"value": "角色甲"}])
    repo = Neo4jGraphRepository(Settings(NEO4J_PASSWORD="pw"))
    repo._driver = _FakeDriver(session)

    rows = await repo._query_read_records("test_query", "RETURN $query AS value", query="角色甲")

    assert rows == [{"value": "角色甲"}]
    assert session.run_calls == [("RETURN $query AS value", {"query": "角色甲"}, {})]


async def test_query_fulltext_sources_escapes_query_before_running_cypher():
    session = _FakeSession([])
    repo = Neo4jGraphRepository(
        Settings(
            NEO4J_URI="neo4j://127.0.0.1:7687",
            NEO4J_USERNAME="neo4j",
            NEO4J_PASSWORD="pw",
        )
    )
    repo._driver = _FakeDriver(session)

    rows = await repo.query_fulltext_sources("鸣潮/典故", limit=3)

    assert rows == []
    assert len(session.run_calls) == 1
    query, parameters, kwargs = session.run_calls[0]
    assert "db.index.fulltext.queryNodes" in query
    assert parameters == {
        "index_name": "source_fulltext_index",
        "query": r"鸣潮\/典故",
        "limit": 3,
    }
    assert kwargs == {}


async def test_prepare_embedding_candidates_returns_empty_when_neo4j_is_degraded():
    repo = Neo4jGraphRepository(
        Settings(
            NEO4J_URI="neo4j://127.0.0.1:7687",
            NEO4J_USERNAME="neo4j",
            NEO4J_PASSWORD="pw",
        )
    )
    await repo.mark_neo4j_unavailable("startup failed")

    counts, samples = await repo.prepare_embedding_candidates(
        IndexScope.all,
        reindex=False,
        sample_limit=10,
    )

    assert counts == {"entity": 0, "source": 0, "relation": 0}
    assert samples == []


async def test_get_graph_counts_returns_zero_when_neo4j_is_degraded():
    repo = Neo4jGraphRepository(
        Settings(
            NEO4J_URI="neo4j://127.0.0.1:7687",
            NEO4J_USERNAME="neo4j",
            NEO4J_PASSWORD="pw",
        )
    )
    await repo.mark_neo4j_unavailable("startup failed")

    counts = await repo.get_graph_counts()

    assert counts == {
        "entity_count": 0,
        "source_count": 0,
        "relation_count": 0,
    }


async def test_update_visited_relation_tx_stores_page_modification_details():
    tx = _FakeTx()
    extraction = PageExtraction(
        canonical_url="https://example.com/page",
        title="示例页面",
        summary="这是页面摘要",
        extracted_entities=[
            ExtractedEntity(name="角色甲", category="character", summary="角色", aliases=[], relations=[]),
            ExtractedEntity(name="角色丙", category="character", summary="角色", aliases=[], relations=[]),
        ],
        discovered_urls=["https://example.com/next"],
        content_hash="hash",
        raw_text_excerpt="正文",
    )
    source_update = {
        "created_entities": ["角色甲"],
        "updated_entities": ["角色丙"],
        "created_sources": ["https://example.com/page"],
        "created_relationships": 2,
        "deleted_relationships": 1,
    }

    await Neo4jGraphRepository._update_visited_relation_tx(
        tx,
        job_id="job-1",
        extraction=extraction,
        source_created=True,
        source_update=source_update,
    )

    query, params = tx.calls[0]

    assert "visited.modification_summary = $modification_summary" in query
    assert "visited.change_log = $change_log" in query
    assert params["created_entities"] == ["角色甲"]
    assert params["updated_entities"] == ["角色丙"]
    assert params["created_relationships"] == 2
    assert params["deleted_relationships"] == 1
    assert "来源状态：新增来源" in params["modification_summary"]
    assert "新增实体（1）：角色甲" in params["change_log"]


async def test_upsert_entity_node_tx_sets_mentioned_in_relevance():
    tx = _FakeTx()

    await Neo4jGraphRepository._upsert_entity_node_tx(
        tx,
        canonical_url="https://example.com/page",
        entity_id="entity-1",
        name="角色甲",
        normalized_name="角色甲",
        category="character",
        summary="角色甲摘要",
        aliases=["ROLE_ALPHA"],
        mentioned_in_score=0.9,
    )

    query, params = tx.calls[0]

    assert "CASE WHEN $mentioned_in_score IS NULL THEN [] ELSE [1] END" in query
    assert "MERGE (entity)-[rel:MENTIONED_IN]->(source)" in query
    assert "SET rel.relevance = $mentioned_in_score" in query
    assert params["mentioned_in_score"] == 0.9


async def test_upsert_entity_node_tx_skips_mentioned_in_when_score_missing():
    tx = _FakeTx()

    await Neo4jGraphRepository._upsert_entity_node_tx(
        tx,
        canonical_url="https://example.com/page",
        entity_id="entity-1",
        name="角色甲",
        normalized_name="角色甲",
        category="character",
        summary="角色甲摘要",
        aliases=["ROLE_ALPHA"],
        mentioned_in_score=None,
    )

    _, params = tx.calls[0]

    assert params["mentioned_in_score"] is None


async def test_delete_stale_mentioned_in_tx_returns_removed_entities_and_count():
    tx = _FakeTxWithSingleResult(
        {
            "entity_ids": ["entity-1", "entity-2"],
            "deleted_relationships": 2,
        }
    )

    result = await Neo4jGraphRepository._delete_stale_mentioned_in_tx(
        tx,
        canonical_url="https://example.com/page",
        retained_entity_ids=["entity-3"],
    )

    query, params = tx.calls[0]

    assert "WHERE NOT entity.entity_id IN $retained_entity_ids" in query
    assert params["retained_entity_ids"] == ["entity-3"]
    assert result == {
        "entity_ids": ["entity-1", "entity-2"],
        "deleted_relationships": 2,
    }


async def test_merge_entity_into_canonical_tx_keeps_higher_mentioned_in_relevance():
    tx = _FakeTx()

    await Neo4jGraphRepository._merge_entity_into_canonical_tx(
        tx,
        canonical_entity_id="entity-1",
        duplicate_entity_id="entity-2",
    )

    query, params = tx.calls[0]

    assert "MERGE (canonical)-[merged:MENTIONED_IN]->(source)" in query
    assert "WHEN merged.relevance >= coalesce(rel.relevance, $default_relevance)" in query
    assert params["default_relevance"] == 0.5


async def test_upsert_relation_tx_reuses_similar_existing_relation_instead_of_creating_new():
    tx = _FakeTxWithSequentialSingleResults(
        [
            {"relation_types": ["地区乙组织的核心成员"]},
            {"existed": True},
        ]
    )

    created = await Neo4jGraphRepository._upsert_relation_tx(
        tx,
        source_entity_id="entity-1",
        target_entity_id="entity-2",
        relation_type="地区乙组织核心成员",
        evidence="角色甲是地区乙组织核心成员。",
    )

    assert created is False
    first_query, first_params = tx.calls[0]
    second_query, second_params = tx.calls[1]
    assert "collect(DISTINCT coalesce(rel.relation_type, \"RELATED_TO\")) AS relation_types" in first_query
    assert first_params["source_entity_id"] == "entity-1"
    assert first_params["target_entity_id"] == "entity-2"
    assert "SET rel.evidence = CASE" in second_query
    assert second_params["matched_relation_type"] == "地区乙组织的核心成员"


async def test_mark_embedding_failed_tx_inserts_with_before_second_match():
    tx = _FakeTx()

    await Neo4jGraphRepository._mark_embedding_failed_tx(
        tx,
        source_type="relation",
        source_key="entity-a::entity-b",
        error="boom",
    )

    query, params = tx.calls[0]

    assert "WITH $source_type AS source_type, $error AS error, $embedding_key AS embedding_key" in query
    assert "OPTIONAL MATCH (embedding:Embedding {embedding_key: embedding_key})" in query
    assert params["embedding_key"] == "relation:entity-a::entity-b"


async def test_mark_fulltext_failed_tx_inserts_with_before_second_match():
    tx = _FakeTx()

    await Neo4jGraphRepository._mark_fulltext_failed_tx(
        tx,
        source_type="relation",
        source_key="entity-a::entity-b",
        error="boom",
    )

    query, _ = tx.calls[0]

    assert "WITH $source_type AS source_type, $source_key AS source_key, $error AS error" in query
    assert "OPTIONAL MATCH (embedding:RelationEmbedding {embedding_key: 'relation:' + source_key})" in query


async def test_upsert_fulltext_documents_tx_avoids_subquery_importing_with():
    tx = _FakeTx()

    await Neo4jGraphRepository._upsert_fulltext_documents_tx(
        tx,
        records=[
            {
                "source_type": "entity",
                "source_key": "entity-a",
                "document_text": "doc",
                "target_hash": "hash",
                "updated_at": "2026-03-30T12:00:00+00:00",
                "aggregated_text": "agg",
                "left_entity_name": None,
                "right_entity_name": None,
            }
        ],
        version="v1",
    )

    query, params = tx.calls[0]

    assert "CALL {" not in query
    assert "FOREACH (_ IN CASE WHEN record.source_type = 'entity' AND entity IS NOT NULL THEN [1] ELSE [] END |" in query
    assert "WITH record\n            OPTIONAL MATCH (source:Source {canonical_url: record.source_key})" in query
    assert "FOREACH (_ IN CASE WHEN record.source_type = 'relation' THEN [1] ELSE [] END |" in query
    assert params["version"] == "v1"


def test_build_job_summary_text_includes_graph_update_and_error_details():
    completed_at = datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc)
    job = JobSummary(
        job_id="job-1",
        input_type=JobInputType.url,
        seed="https://example.com",
        status=JobStatus.completed,
        max_depth=2,
        max_pages=20,
        visited_count=5,
        queued_count=0,
        failed_count=1,
        completed_at=completed_at,
        last_error="timeout on a nested page",
        graph_update=GraphUpdateResult(
            created_entities=["角色甲", "角色丙"],
            updated_entities=["地区乙"],
            created_sources=["https://example.com/page-1"],
            created_relationships=4,
            deleted_relationships=1,
        ),
    )

    summary = _build_job_summary_text(job)

    assert "任务状态：completed" in summary
    assert "访问页面：5" in summary
    assert "图谱变更：新增来源 1 个，新增实体 2 个，更新实体 1 个，新增关系 4 条，删除关系 1 条" in summary
    assert "最近错误：timeout on a nested page" in summary
    assert completed_at.isoformat() in summary


def test_build_source_change_log_contains_specific_modification_content():
    extraction = PageExtraction(
        canonical_url="https://example.com/page",
        title="示例页面",
        summary="这是页面摘要",
        extracted_entities=[
            ExtractedEntity(name="角色甲", category="character", summary="角色", aliases=[], relations=[])
        ],
        discovered_urls=["https://example.com/next"],
        content_hash="hash",
        raw_text_excerpt="正文",
    )
    source_update = {
        "created_entities": ["角色甲"],
        "updated_entities": ["地区乙"],
        "created_sources": ["https://example.com/page"],
        "created_relationships": 3,
        "deleted_relationships": 1,
    }

    summary = _build_source_modification_summary(
        extraction=extraction,
        source_created=False,
        source_update=source_update,
    )
    change_log = _build_source_change_log(
        extraction=extraction,
        source_created=False,
        source_update=source_update,
    )

    assert "来源状态：更新已有来源" in summary
    assert "新增关系：3 条" in summary
    assert "来源修改详情" in change_log
    assert "- 来源摘要：这是页面摘要" in change_log
    assert "- 新增实体（1）：角色甲" in change_log
    assert "- 更新实体（1）：地区乙" in change_log


def test_build_job_change_log_text_contains_detailed_modification_records():
    completed_at = datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc)
    job = JobSummary(
        job_id="job-1",
        input_type=JobInputType.url,
        seed="https://example.com",
        status=JobStatus.completed,
        max_depth=2,
        max_pages=20,
        visited_count=5,
        queued_count=0,
        failed_count=1,
        completed_at=completed_at,
        graph_update=GraphUpdateResult(
            created_entities=["角色甲", "角色丙"],
            updated_entities=["地区乙"],
            created_sources=["https://example.com/page-1"],
            created_relationships=4,
            deleted_relationships=1,
        ),
    )

    change_log = _build_job_change_log_text(job)

    assert "任务概览" in change_log
    assert "- 执行统计：访问页面 5，队列剩余 0，失败数 1" in change_log
    assert "修改记录" in change_log
    assert "- 新增来源（1）：https://example.com/page-1" in change_log
    assert "- 新增实体（2）：角色甲、角色丙" in change_log
    assert "- 更新实体（1）：地区乙" in change_log
    assert "- 新增关系：4" in change_log
    assert "- 删除关系：1" in change_log
