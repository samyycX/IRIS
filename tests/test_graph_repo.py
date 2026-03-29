from datetime import datetime, timezone

from app.models import (
    ExtractedEntity,
    GraphUpdateResult,
    JobInputType,
    JobStatus,
    JobSummary,
    PageExtraction,
)
from app.repos.graph_repo import (
    Neo4jGraphRepository,
    _build_related_url_lookup_terms,
    _build_job_change_log_text,
    _build_page_change_log,
    _build_page_modification_summary,
    _build_job_summary_text,
    _build_relation_target_summary,
    _build_entity_payload,
    _calculate_entity_completeness_score,
    _classify_entity_completeness,
    _build_search_terms,
    _entity_id,
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


class _FakeTx:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def run(self, query: str, **kwargs):
        self.calls.append((query, kwargs))


async def test_upsert_page_tx_writes_full_raw_text_excerpt_for_replacement():
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

    await Neo4jGraphRepository._upsert_page_tx(tx, "job-1", extraction)

    query, params = tx.calls[0]

    assert "page.raw_text_excerpt = $raw_text_excerpt" in query
    assert params["raw_text_excerpt"] == raw_text


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
    page_update = {
        "created_entities": ["角色甲"],
        "updated_entities": ["角色丙"],
        "created_pages": ["https://example.com/page"],
        "created_relationships": 2,
        "deleted_relationships": 1,
    }

    await Neo4jGraphRepository._update_visited_relation_tx(
        tx,
        job_id="job-1",
        extraction=extraction,
        page_created=True,
        page_update=page_update,
    )

    query, params = tx.calls[0]

    assert "visited.modification_summary = $modification_summary" in query
    assert "visited.change_log = $change_log" in query
    assert params["created_entities"] == ["角色甲"]
    assert params["updated_entities"] == ["角色丙"]
    assert params["created_relationships"] == 2
    assert params["deleted_relationships"] == 1
    assert "页面状态：新增页面" in params["modification_summary"]
    assert "新增实体（1）：角色甲" in params["change_log"]


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
            created_pages=["https://example.com/page-1"],
            created_relationships=4,
            deleted_relationships=1,
        ),
    )

    summary = _build_job_summary_text(job)

    assert "任务状态：completed" in summary
    assert "访问页面：5" in summary
    assert "图谱变更：新增页面 1 个，新增实体 2 个，更新实体 1 个，新增关系 4 条，删除关系 1 条" in summary
    assert "最近错误：timeout on a nested page" in summary
    assert completed_at.isoformat() in summary


def test_build_page_change_log_contains_specific_modification_content():
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
    page_update = {
        "created_entities": ["角色甲"],
        "updated_entities": ["地区乙"],
        "created_pages": ["https://example.com/page"],
        "created_relationships": 3,
        "deleted_relationships": 1,
    }

    summary = _build_page_modification_summary(
        extraction=extraction,
        page_created=False,
        page_update=page_update,
    )
    change_log = _build_page_change_log(
        extraction=extraction,
        page_created=False,
        page_update=page_update,
    )

    assert "页面状态：更新已有页面" in summary
    assert "新增关系：3 条" in summary
    assert "页面修改详情" in change_log
    assert "- 页面摘要：这是页面摘要" in change_log
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
            created_pages=["https://example.com/page-1"],
            created_relationships=4,
            deleted_relationships=1,
        ),
    )

    change_log = _build_job_change_log_text(job)

    assert "任务概览" in change_log
    assert "- 执行统计：访问页面 5，队列剩余 0，失败数 1" in change_log
    assert "修改记录" in change_log
    assert "- 新增页面（1）：https://example.com/page-1" in change_log
    assert "- 新增实体（2）：角色甲、角色丙" in change_log
    assert "- 更新实体（1）：地区乙" in change_log
    assert "- 新增关系：4" in change_log
    assert "- 删除关系：1" in change_log
