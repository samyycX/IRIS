from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

from app.core.config import Settings
from app.core.logging import get_logger
from app.models import JobCreateResponse, JobEvent, JobRequest, JobStage, JobStatus, JobSummary
from app.repos.job_store import JobStore
from app.services.crawl.pipeline import CrawlPipeline

logger = get_logger(__name__)


class JobService:
    def __init__(
        self,
        settings: Settings,
        job_store: JobStore,
        pipeline: CrawlPipeline,
    ) -> None:
        self._settings = settings
        self._job_store = job_store
        self._pipeline = pipeline
        self._local_tasks: dict[str, asyncio.Task] = {}
        self._pause_requests: set[str] = set()
        self._cancel_requests: set[str] = set()
        self._shutdown_requested = False

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
        job = await self._job_store.create_job(request, max_depth=max_depth, max_pages=max_pages)
        await self._job_store.append_event(
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
        await self.enqueue_job(job.job_id, is_resume=False)
        return JobCreateResponse(job_id=job.job_id, status=JobStatus.queued)

    async def enqueue_job(self, job_id: str, *, is_resume: bool) -> None:
        existing = self._local_tasks.get(job_id)
        if existing is not None and not existing.done():
            return
        task = asyncio.create_task(self.run_job(job_id, is_resume=is_resume), name=f"job:{job_id}")
        self._local_tasks[job_id] = task
        task.add_done_callback(lambda _: self._local_tasks.pop(job_id, None))

    async def run_job(self, job_id: str, *, is_resume: bool) -> None:
        request = await self._job_store.get_request(job_id)
        if request is None:
            logger.warning("job_request_missing", job_id=job_id)
            return
        try:
            checkpoint = await self._job_store.get_checkpoint(job_id) if is_resume else None
            await self._pipeline.run_job(job_id, request, checkpoint=checkpoint)
        except asyncio.CancelledError:
            pause_requested = job_id in self._pause_requests
            cancel_requested = job_id in self._cancel_requests
            self._pause_requests.discard(job_id)
            self._cancel_requests.discard(job_id)
            if cancel_requested:
                current = await self._job_store.get_job(job_id)
                await self._job_store.save_checkpoint(job_id, None)
                cancelled_job = await self._job_store.finish_job(
                    job_id,
                    JobStatus.cancelled,
                    graph_update=current.graph_update if current else None,
                )
                await self._job_store.update_job(
                    job_id,
                    resume_available=False,
                    checkpoint_updated_at=None,
                    completion_reason="cancelled",
                )
                await self._job_store.append_event(
                    JobEvent(
                        job_id=job_id,
                        stage=JobStage.cancelled,
                        message="任务已取消",
                        data={
                            "job_status": JobStatus.cancelled.value,
                            "cancelled": True,
                        },
                    )
                )
                return
            if pause_requested:
                await self._job_store.set_status(job_id, JobStatus.paused)
                checkpoint = await self._job_store.get_checkpoint(job_id)
                await self._job_store.update_job(
                    job_id,
                    resume_available=bool(checkpoint and (checkpoint.pending_queue or checkpoint.in_progress)),
                    checkpoint_updated_at=checkpoint.updated_at if checkpoint else None,
                    completion_reason="paused",
                )
                await self._job_store.append_event(
                    JobEvent(
                        job_id=job_id,
                        stage=JobStage.queued,
                        message="任务已暂停",
                        data={
                            "job_status": JobStatus.paused.value,
                            "paused": True,
                        },
                    )
                )
                return
            if self._shutdown_requested:
                raise
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("job_execution_failed", job_id=job_id, error=str(exc))
            failed_job = await self._job_store.finish_job(job_id, JobStatus.failed, last_error=str(exc))
            await self._job_store.append_event(
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
                await self._mark_job_resumable(job_id, failed_job)

    async def list_jobs(self):
        return await self._job_store.list_jobs()

    async def get_job(self, job_id: str):
        return await self._job_store.get_job(job_id)

    async def get_events(self, job_id: str) -> list[JobEvent]:
        return await self._job_store.get_events(job_id)

    async def resume_job(self, job_id: str) -> JobSummary | None:
        job = await self._job_store.get_job(job_id)
        if job is None:
            return None
        if job.status not in {JobStatus.failed, JobStatus.interrupted, JobStatus.paused}:
            return job
        local_task = self._local_tasks.get(job_id)
        if local_task is not None and not local_task.done():
            return job
        request = await self._job_store.get_request(job_id)
        if request is None:
            return job
        updated = await self._job_store.update_job(
            job_id,
            status=JobStatus.queued,
            last_error=None,
            completed_at=None,
        )
        await self._job_store.append_event(
            JobEvent(
                job_id=job_id,
                stage=JobStage.queued,
                message="任务已恢复，等待调度",
                data={
                    "job_status": JobStatus.queued.value,
                    "resume": True,
                    "visited_count": updated.visited_count if updated else job.visited_count,
                    "queued_count": updated.queued_count if updated else job.queued_count,
                    "failed_count": updated.failed_count if updated else job.failed_count,
                },
            )
        )
        await self.enqueue_job(job_id, is_resume=True)
        return await self._job_store.get_job(job_id)

    async def pause_job(self, job_id: str) -> JobSummary | None:
        job = await self._job_store.get_job(job_id)
        if job is None:
            return None
        if job.status not in {JobStatus.queued, JobStatus.running}:
            return job
        task = self._local_tasks.get(job_id)
        self._pause_requests.add(job_id)
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        current = await self._job_store.get_job(job_id)
        if current is None:
            return None
        if current.status != JobStatus.paused:
            checkpoint = await self._job_store.get_checkpoint(job_id)
            await self._job_store.update_job(
                job_id,
                status=JobStatus.paused,
                resume_available=bool(checkpoint and (checkpoint.pending_queue or checkpoint.in_progress)),
                checkpoint_updated_at=checkpoint.updated_at if checkpoint else None,
                completion_reason="paused",
            )
            await self._job_store.append_event(
                JobEvent(
                    job_id=job_id,
                    stage=JobStage.queued,
                    message="任务已暂停",
                    data={
                        "job_status": JobStatus.paused.value,
                        "paused": True,
                    },
                )
            )
        self._pause_requests.discard(job_id)
        return await self._job_store.get_job(job_id)

    async def cancel_job(self, job_id: str) -> JobSummary | None:
        job = await self._job_store.get_job(job_id)
        if job is None:
            return None
        if job.status in {JobStatus.completed, JobStatus.cancelled}:
            return job
        task = self._local_tasks.get(job_id)
        self._cancel_requests.add(job_id)
        self._pause_requests.discard(job_id)
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        current = await self._job_store.get_job(job_id)
        if current is None:
            return None
        if current.status != JobStatus.cancelled:
            await self._job_store.save_checkpoint(job_id, None)
            await self._job_store.finish_job(
                job_id,
                JobStatus.cancelled,
                graph_update=current.graph_update,
            )
            await self._job_store.update_job(
                job_id,
                resume_available=False,
                checkpoint_updated_at=None,
                completion_reason="cancelled",
            )
            await self._job_store.append_event(
                JobEvent(
                    job_id=job_id,
                    stage=JobStage.cancelled,
                    message="任务已取消",
                    data={
                        "job_status": JobStatus.cancelled.value,
                        "cancelled": True,
                    },
                )
            )
        self._cancel_requests.discard(job_id)
        return await self._job_store.get_job(job_id)

    async def stream_events(self, job_id: str) -> AsyncIterator[dict[str, str]]:
        sent = len(await self._job_store.get_events(job_id))
        while True:
            events = await self._job_store.get_events(job_id)
            for event in events[sent:]:
                yield {"data": event.model_dump_json()}
            sent = len(events)

            job = await self._job_store.get_job(job_id)
            if job and job.status in {
                JobStatus.completed,
                JobStatus.failed,
                JobStatus.cancelled,
                JobStatus.interrupted,
                JobStatus.paused,
            }:
                break
            await self._job_store.wait_for_event(job_id, sent)

    async def mark_interrupted_jobs(self) -> int:
        return await self._job_store.mark_incomplete_jobs_interrupted()

    async def shutdown(self) -> None:
        self._shutdown_requested = True
        for task in list(self._local_tasks.values()):
            task.cancel()
        for task in list(self._local_tasks.values()):
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self._job_store.close()

    async def _mark_job_resumable(self, job_id: str, job: JobSummary) -> None:
        checkpoint = await self._job_store.get_checkpoint(job_id)
        if checkpoint is None:
            return
        await self._job_store.update_job(
            job_id,
            resume_available=bool(checkpoint.pending_queue or checkpoint.in_progress),
            checkpoint_updated_at=checkpoint.updated_at,
            completion_reason=checkpoint.completion_reason,
        )
