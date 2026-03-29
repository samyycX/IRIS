import asyncio

from app.models import GraphUpdateResult
from app.services.crawl.pipeline import (
    _await_with_timeout,
    _should_bypass_history_seen_check,
    merge_graph_updates,
)


def test_merge_graph_updates_combines_lists_and_counts():
    left = GraphUpdateResult(
        created_entities=["角色甲"],
        updated_entities=["角色丁"],
        created_pages=["https://wiki.example.com/a"],
        created_relationships=2,
        deleted_relationships=1,
    )
    right = GraphUpdateResult(
        created_entities=["角色丁", "角色甲"],
        updated_entities=["角色戊"],
        created_pages=["https://wiki.example.com/b"],
        created_relationships=3,
        deleted_relationships=2,
    )

    merged = merge_graph_updates(left, right)

    assert set(merged.created_entities) == {"角色甲", "角色丁"}
    assert set(merged.updated_entities) == {"角色丁", "角色戊"}
    assert merged.created_pages == [
        "https://wiki.example.com/a",
        "https://wiki.example.com/b",
    ]
    assert merged.created_relationships == 5
    assert merged.deleted_relationships == 3


def test_seed_url_bypasses_history_seen_check():
    assert _should_bypass_history_seen_check(
        url="https://wiki.example.com/item/1415137052791296000",
        depth=0,
        seed_url="https://wiki.example.com/item/1415137052791296000",
    )


def test_non_seed_urls_still_use_history_seen_check():
    assert not _should_bypass_history_seen_check(
        url="https://wiki.example.com/item/1415137052791296001",
        depth=1,
        seed_url="https://wiki.example.com/item/1415137052791296000",
    )


async def test_await_with_timeout_returns_result_before_deadline():
    result = await _await_with_timeout(
        asyncio.sleep(0, result="ok"),
        timeout_seconds=1,
        timeout_message="不应该超时",
    )

    assert result == "ok"


async def test_await_with_timeout_raises_runtime_error_on_timeout():
    try:
        await _await_with_timeout(
            asyncio.sleep(0.05, result="late"),
            timeout_seconds=0.01,
            timeout_message="查询图谱上下文并调用 LLM 超时",
        )
    except RuntimeError as exc:
        assert str(exc) == "查询图谱上下文并调用 LLM 超时"
    else:
        raise AssertionError("expected timeout")
