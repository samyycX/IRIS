from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

from app.core.config import Settings
from app.core.logging import get_logger
from app.models import JobCreateResponse, JobEvent, JobRequest, JobStage, JobStatus
from app.repos.event_store import InMemoryEventStore
from app.repos.graph_repo import Neo4jGraphRepository
from app.services.crawl.pipeline import CrawlPipeline

logger = get_logger(__name__)


class JobService:
    def __init__(
        self,
        settings: Settings,
        event_store: InMemoryEventStore,
        graph_repo: Neo4jGraphRepository,
        pipeline: CrawlPipeline,
    ) -> None:
        self._settings = settings
        self._event_store = event_store
        self._graph_repo = graph_repo
        self._pipeline = pipeline
        self._local_tasks: dict[str, asyncio.Task] = {}

    async def create_job(self, request: JobRequest) -> JobCreateResponse:
        max_depth = (
            request.max_depth if request.max_depth is not None else self._settings.max_crawl_depth
        )
        max_pages = (
            request.max_pages if request.max_pages is not None else self._settings.max_pages_per_job
        )
        crawl_concurrency = (
            request.crawl_concurrency
            if request.crawl_concurrency is not None
            else self._settings.crawl_concurrency
        )
        job = await self._event_store.create_job(request, max_depth=max_depth, max_pages=max_pages)
        await self._graph_repo.sync_job(job, request=request)
        await self._event_store.append_event(
            JobEvent(
                job_id=job.job_id,
                stage=JobStage.queued,
                message="任务已创建，等待调度",
                data={
                    "input_type": request.input_type.value,
                    "seed": request.seed(),
                    "job_status": JobStatus.queued.value,
                    "visited_count": 0,
                    "queued_count": 0,
                    "failed_count": 0,
                    "max_depth": max_depth,
                    "max_pages": max_pages,
                    "crawl_concurrency": crawl_concurrency,
                },
            )
        )
        await self.enqueue_job(job.job_id)
        return JobCreateResponse(job_id=job.job_id, status=JobStatus.queued)

    async def enqueue_job(self, job_id: str) -> None:
        task = asyncio.create_task(self.run_job(job_id), name=f"job:{job_id}")
        self._local_tasks[job_id] = task
        task.add_done_callback(lambda _: self._local_tasks.pop(job_id, None))

    async def run_job(self, job_id: str) -> None:
        request = await self._event_store.get_request(job_id)
        if request is None:
            logger.warning("job_request_missing", job_id=job_id)
            return
        try:
            await self._pipeline.run_job(job_id, request)
        except Exception as exc:  # noqa: BLE001
            logger.exception("job_execution_failed", job_id=job_id, error=str(exc))
            failed_job = await self._event_store.finish_job(job_id, JobStatus.failed, last_error=str(exc))
            await self._event_store.append_event(
                JobEvent(
                    job_id=job_id,
                    stage=JobStage.failed,
                    message="任务执行失败",
                    data={
                        "error": str(exc),
                        "job_status": JobStatus.failed.value,
                        "last_error": str(exc),
                    },
                )
            )
            if failed_job is not None:
                await self._graph_repo.sync_job(failed_job, request=request)

    async def list_jobs(self):
        return await self._event_store.list_jobs()

    async def get_job(self, job_id: str):
        return await self._event_store.get_job(job_id)

    async def get_events(self, job_id: str) -> list[JobEvent]:
        return await self._event_store.get_events(job_id)

    async def stream_events(self, job_id: str) -> AsyncIterator[dict[str, str]]:
        sent = 0
        while True:
            events = await self._event_store.get_events(job_id)
            for event in events[sent:]:
                yield {"data": event.model_dump_json()}
            sent = len(events)

            job = await self._event_store.get_job(job_id)
            if job and job.status in {JobStatus.completed, JobStatus.failed, JobStatus.cancelled}:
                break
            await self._event_store.wait_for_event(job_id, sent)

    async def shutdown(self) -> None:
        for task in list(self._local_tasks.values()):
            task.cancel()
        for task in list(self._local_tasks.values()):
            with contextlib.suppress(asyncio.CancelledError):
                await task
