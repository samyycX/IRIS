from __future__ import annotations

import asyncio
import contextlib
from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Callable
from uuid import uuid4

from app.models import (
    GraphUpdateResult,
    JobCheckpoint,
    JobEvent,
    JobRequest,
    JobStatus,
    JobSummary,
    utcnow,
)


class JobStore(ABC):
    @abstractmethod
    async def create_job(self, request: JobRequest, max_depth: int, max_pages: int) -> JobSummary:
        raise NotImplementedError

    @abstractmethod
    async def list_jobs(self) -> list[JobSummary]:
        raise NotImplementedError

    @abstractmethod
    async def get_job(self, job_id: str) -> JobSummary | None:
        raise NotImplementedError

    @abstractmethod
    async def update_job(self, job_id: str, **changes: Any) -> JobSummary | None:
        raise NotImplementedError

    @abstractmethod
    async def finish_job(
        self,
        job_id: str,
        status: JobStatus,
        *,
        graph_update: GraphUpdateResult | None = None,
        last_error: str | None = None,
    ) -> JobSummary | None:
        raise NotImplementedError

    @abstractmethod
    async def append_event(self, event: JobEvent) -> JobEvent:
        raise NotImplementedError

    @abstractmethod
    async def get_events(self, job_id: str) -> list[JobEvent]:
        raise NotImplementedError

    @abstractmethod
    async def remember_visited_url(self, job_id: str, canonical_url: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def has_job_visited_url(self, job_id: str, canonical_url: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def has_seen_url_globally(self, canonical_url: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def set_status(self, job_id: str, status: JobStatus, last_error: str | None = None) -> None:
        raise NotImplementedError

    @abstractmethod
    async def set_queue_size(self, job_id: str, queue_size: int) -> None:
        raise NotImplementedError

    @abstractmethod
    async def increment_failed(self, job_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_request(self, job_id: str) -> JobRequest | None:
        raise NotImplementedError

    @abstractmethod
    async def save_checkpoint(self, job_id: str, checkpoint: JobCheckpoint | None) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_checkpoint(self, job_id: str) -> JobCheckpoint | None:
        raise NotImplementedError

    @abstractmethod
    async def wait_for_event(self, job_id: str, after_count: int) -> None:
        raise NotImplementedError

    @abstractmethod
    async def mark_incomplete_jobs_interrupted(self) -> int:
        raise NotImplementedError

    async def close(self) -> None:
        return None

    @staticmethod
    def is_terminal_status(job: JobSummary | None) -> bool:
        return bool(
            job
            and job.status
            in {
                JobStatus.completed,
                JobStatus.failed,
                JobStatus.cancelled,
                JobStatus.interrupted,
                JobStatus.paused,
            }
        )


class InMemoryJobStore(JobStore):
    def __init__(
        self,
        global_seen_ttl_days: int = 10,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._lock = asyncio.Lock()
        self._event_condition = asyncio.Condition()
        self._global_seen_ttl = timedelta(days=global_seen_ttl_days)
        self._now_provider = now_provider or utcnow
        self._jobs: dict[str, JobSummary] = {}
        self._requests: dict[str, JobRequest] = {}
        self._events: dict[str, list[JobEvent]] = defaultdict(list)
        self._visited_by_job: dict[str, set[str]] = defaultdict(set)
        self._global_visited: dict[str, datetime] = {}
        self._checkpoints: dict[str, JobCheckpoint] = {}

    async def create_job(self, request: JobRequest, max_depth: int, max_pages: int) -> JobSummary:
        async with self._lock:
            job_id = str(uuid4())
            job = JobSummary(
                job_id=job_id,
                input_type=request.input_type,
                seed=request.seed(),
                status=JobStatus.queued,
                max_depth=max_depth,
                max_pages=max_pages,
            )
            self._jobs[job_id] = job
            self._requests[job_id] = request.model_copy(deep=True)
            return job.model_copy(deep=True)

    async def list_jobs(self) -> list[JobSummary]:
        async with self._lock:
            return [
                job.model_copy(deep=True)
                for job in sorted(self._jobs.values(), key=lambda item: item.updated_at, reverse=True)
            ]

    async def get_job(self, job_id: str) -> JobSummary | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            return job.model_copy(deep=True) if job else None

    async def update_job(self, job_id: str, **changes: Any) -> JobSummary | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            updated = job.model_copy(
                update={
                    "updated_at": utcnow(),
                    **changes,
                }
            )
            self._jobs[job_id] = updated
            return updated.model_copy(deep=True)

    async def finish_job(
        self,
        job_id: str,
        status: JobStatus,
        *,
        graph_update: GraphUpdateResult | None = None,
        last_error: str | None = None,
    ) -> JobSummary | None:
        job = await self.get_job(job_id)
        if job is None:
            return None
        completed_at = utcnow()
        job.status = status
        job.completed_at = completed_at
        job.updated_at = completed_at
        job.last_error = last_error
        if graph_update is not None:
            job.graph_update = graph_update.model_copy(deep=True)
        if status in {JobStatus.completed, JobStatus.cancelled}:
            job.resume_available = False
            job.checkpoint_updated_at = None
            job.completion_reason = status.value
            self._checkpoints.pop(job_id, None)
        async with self._lock:
            self._jobs[job_id] = job
        async with self._event_condition:
            self._event_condition.notify_all()
        return job.model_copy(deep=True)

    async def append_event(self, event: JobEvent) -> JobEvent:
        async with self._lock:
            self._events[event.job_id].append(event.model_copy(deep=True))
            copied = event.model_copy(deep=True)
        async with self._event_condition:
            self._event_condition.notify_all()
        return copied

    async def get_events(self, job_id: str) -> list[JobEvent]:
        async with self._lock:
            return [event.model_copy(deep=True) for event in self._events.get(job_id, [])]

    async def remember_visited_url(self, job_id: str, canonical_url: str) -> bool:
        async with self._lock:
            seen = canonical_url in self._visited_by_job[job_id]
            if not seen:
                self._visited_by_job[job_id].add(canonical_url)
                job = self._jobs.get(job_id)
                if job is not None:
                    job.visited_count = len(self._visited_by_job[job_id])
                    job.updated_at = utcnow()
            self._global_visited[canonical_url] = self._now_provider()
            return not seen

    async def has_job_visited_url(self, job_id: str, canonical_url: str) -> bool:
        async with self._lock:
            return canonical_url in self._visited_by_job[job_id]

    async def has_seen_url_globally(self, canonical_url: str) -> bool:
        async with self._lock:
            cutoff = self._now_provider() - self._global_seen_ttl
            seen_at = self._global_visited.get(canonical_url)
            if seen_at is None:
                return False
            if seen_at < cutoff:
                self._global_visited.pop(canonical_url, None)
                return False
            return True

    async def set_status(self, job_id: str, status: JobStatus, last_error: str | None = None) -> None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.status = status
            job.last_error = last_error
            job.updated_at = utcnow()
            if status not in {JobStatus.completed, JobStatus.failed, JobStatus.cancelled}:
                job.completed_at = None

    async def set_queue_size(self, job_id: str, queue_size: int) -> None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.queued_count = queue_size
            job.updated_at = utcnow()

    async def increment_failed(self, job_id: str) -> None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.failed_count += 1
            job.updated_at = utcnow()

    async def get_request(self, job_id: str) -> JobRequest | None:
        async with self._lock:
            request = self._requests.get(job_id)
            return request.model_copy(deep=True) if request else None

    async def save_checkpoint(self, job_id: str, checkpoint: JobCheckpoint | None) -> None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            if checkpoint is None:
                self._checkpoints.pop(job_id, None)
                job.resume_available = False
                job.checkpoint_updated_at = None
                return
            copied = checkpoint.model_copy(deep=True)
            copied.updated_at = utcnow()
            self._checkpoints[job_id] = copied
            self._visited_by_job[job_id] = set(copied.visited_urls)
            job.resume_available = bool(copied.pending_queue or copied.in_progress)
            job.checkpoint_updated_at = copied.updated_at
            job.completion_reason = copied.completion_reason
            job.visited_count = len(self._visited_by_job[job_id])
            job.queued_count = len(copied.pending_queue)
            job.updated_at = copied.updated_at

    async def get_checkpoint(self, job_id: str) -> JobCheckpoint | None:
        async with self._lock:
            checkpoint = self._checkpoints.get(job_id)
            return checkpoint.model_copy(deep=True) if checkpoint else None

    async def wait_for_event(self, job_id: str, after_count: int) -> None:
        async with self._event_condition:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(
                    self._event_condition.wait_for(
                        lambda: len(self._events.get(job_id, [])) > after_count
                        or self.is_terminal_status(self._jobs.get(job_id))
                    ),
                    timeout=5,
                )

    async def mark_incomplete_jobs_interrupted(self) -> int:
        interrupted = 0
        async with self._lock:
            for job_id, job in self._jobs.items():
                if job.status not in {JobStatus.queued, JobStatus.running}:
                    continue
                job.status = JobStatus.interrupted
                job.updated_at = utcnow()
                checkpoint = self._checkpoints.get(job_id)
                job.resume_available = checkpoint is not None and bool(
                    checkpoint.pending_queue or checkpoint.in_progress
                )
                interrupted += 1
        return interrupted
