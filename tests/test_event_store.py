import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.models import JobEvent, JobInputType, JobRequest, JobStage, JobStatus
from app.repos.job_store import InMemoryJobStore


@pytest.mark.asyncio
async def test_wait_for_event_returns_after_new_event_is_appended():
    store = InMemoryJobStore()
    job = await store.create_job(
        JobRequest(input_type=JobInputType.entity, entity_name="角色甲"),
        max_depth=1,
        max_pages=1,
    )
    await store.append_event(
        JobEvent(job_id=job.job_id, stage=JobStage.queued, message="任务已创建")
    )

    waiter = asyncio.create_task(store.wait_for_event(job.job_id, after_count=1))
    await asyncio.sleep(0)
    await store.append_event(
        JobEvent(job_id=job.job_id, stage=JobStage.fetching, message="开始抓取页面")
    )

    await asyncio.wait_for(waiter, timeout=0.2)


@pytest.mark.asyncio
async def test_wait_for_event_returns_when_job_becomes_terminal():
    store = InMemoryJobStore()
    job = await store.create_job(
        JobRequest(input_type=JobInputType.entity, entity_name="角色丁"),
        max_depth=1,
        max_pages=1,
    )

    waiter = asyncio.create_task(store.wait_for_event(job.job_id, after_count=0))
    await asyncio.sleep(0)
    await store.finish_job(job.job_id, JobStatus.completed)

    await asyncio.wait_for(waiter, timeout=0.2)


@pytest.mark.asyncio
async def test_global_seen_urls_expire_after_ttl():
    current = datetime(2026, 3, 29, tzinfo=timezone.utc)
    store = InMemoryJobStore(
        global_seen_ttl_days=10,
        now_provider=lambda: current,
    )
    job = await store.create_job(
        JobRequest(input_type=JobInputType.url, url="https://wiki.example.com/character/role-alpha"),
        max_depth=1,
        max_pages=1,
    )

    await store.remember_visited_url(job.job_id, "https://wiki.example.com/character/role-alpha")
    assert await store.has_seen_url_globally("https://wiki.example.com/character/role-alpha") is True

    current = current + timedelta(days=11)
    assert await store.has_seen_url_globally("https://wiki.example.com/character/role-alpha") is False
