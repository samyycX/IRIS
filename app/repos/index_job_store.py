from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Any
from uuid import uuid4

from app.models import (
    IndexJobEvent,
    IndexJobMode,
    IndexJobRequest,
    IndexJobStatus,
    IndexJobSummary,
    IndexScope,
    IndexType,
    utcnow,
)


class IndexJobStore(ABC):
    @abstractmethod
    async def ensure_constraints(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def create_job(
        self,
        *,
        index_type: IndexType,
        mode: IndexJobMode,
        request: IndexJobRequest,
        batch_size: int,
    ) -> IndexJobSummary:
        raise NotImplementedError

    @abstractmethod
    async def get_job(self, job_id: str) -> IndexJobSummary | None:
        raise NotImplementedError

    @abstractmethod
    async def get_request(self, job_id: str) -> IndexJobRequest | None:
        raise NotImplementedError

    @abstractmethod
    async def get_events(self, job_id: str) -> list[IndexJobEvent]:
        raise NotImplementedError

    @abstractmethod
    async def list_jobs(self) -> list[IndexJobSummary]:
        raise NotImplementedError

    @abstractmethod
    async def update_job(self, job_id: str, **changes: Any) -> IndexJobSummary | None:
        raise NotImplementedError

    @abstractmethod
    async def finish_job(
        self,
        job_id: str,
        *,
        status: IndexJobStatus,
        last_error: str | None = None,
    ) -> IndexJobSummary | None:
        raise NotImplementedError

    @abstractmethod
    async def append_event(self, event: IndexJobEvent) -> IndexJobEvent:
        raise NotImplementedError

    @abstractmethod
    async def find_active_job(self, index_type: IndexType, scope: IndexScope) -> IndexJobSummary | None:
        raise NotImplementedError

    async def close(self) -> None:
        return None


class InMemoryIndexJobStore(IndexJobStore):
    def __init__(self) -> None:
        self._jobs: dict[str, IndexJobSummary] = {}
        self._requests: dict[str, IndexJobRequest] = {}
        self._events: dict[str, list[IndexJobEvent]] = defaultdict(list)

    async def ensure_constraints(self) -> None:
        return None

    async def create_job(
        self,
        *,
        index_type: IndexType,
        mode: IndexJobMode,
        request: IndexJobRequest,
        batch_size: int,
    ) -> IndexJobSummary:
        job = IndexJobSummary(
            job_id=str(uuid4()),
            index_type=index_type,
            mode=mode,
            scope=request.scope,
            status=IndexJobStatus.queued,
            batch_size=batch_size,
        )
        self._jobs[job.job_id] = job
        self._requests[job.job_id] = request.model_copy(deep=True)
        return job.model_copy(deep=True)

    async def get_job(self, job_id: str) -> IndexJobSummary | None:
        job = self._jobs.get(job_id)
        return job.model_copy(deep=True) if job else None

    async def get_request(self, job_id: str) -> IndexJobRequest | None:
        request = self._requests.get(job_id)
        return request.model_copy(deep=True) if request else None

    async def get_events(self, job_id: str) -> list[IndexJobEvent]:
        return [event.model_copy(deep=True) for event in self._events.get(job_id, [])]

    async def list_jobs(self) -> list[IndexJobSummary]:
        return [
            job.model_copy(deep=True)
            for job in sorted(self._jobs.values(), key=lambda item: item.updated_at, reverse=True)
        ]

    async def update_job(self, job_id: str, **changes: Any) -> IndexJobSummary | None:
        job = self._jobs.get(job_id)
        if job is None:
            return None
        updated = job.model_copy(update={"updated_at": utcnow(), **changes})
        self._jobs[job_id] = updated
        return updated.model_copy(deep=True)

    async def finish_job(
        self,
        job_id: str,
        *,
        status: IndexJobStatus,
        last_error: str | None = None,
    ) -> IndexJobSummary | None:
        job = self._jobs.get(job_id)
        if job is None:
            return None
        completed_at = utcnow()
        updated = job.model_copy(
            update={
                "status": status,
                "last_error": last_error,
                "updated_at": completed_at,
                "completed_at": completed_at,
            }
        )
        self._jobs[job_id] = updated
        return updated.model_copy(deep=True)

    async def append_event(self, event: IndexJobEvent) -> IndexJobEvent:
        self._events[event.job_id].append(event.model_copy(deep=True))
        return event.model_copy(deep=True)

    async def find_active_job(self, index_type: IndexType, scope: IndexScope) -> IndexJobSummary | None:
        for job in self._jobs.values():
            if job.index_type != index_type:
                continue
            if job.scope != scope and job.scope != IndexScope.all and scope != IndexScope.all:
                continue
            if job.status in {IndexJobStatus.queued, IndexJobStatus.running}:
                return job.model_copy(deep=True)
        return None

