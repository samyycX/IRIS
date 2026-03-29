from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import datetime
from typing import Any
from uuid import uuid4

from neo4j import AsyncGraphDatabase

from app.core.config import Settings
from app.models import (
    VectorIndexJobEvent,
    VectorIndexJobMode,
    VectorIndexJobRequest,
    VectorIndexJobStatus,
    VectorIndexJobSummary,
    VectorIndexScope,
    utcnow,
)


class VectorIndexJobStore(ABC):
    @abstractmethod
    async def ensure_constraints(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def create_job(
        self,
        *,
        mode: VectorIndexJobMode,
        request: VectorIndexJobRequest,
        batch_size: int,
    ) -> VectorIndexJobSummary:
        raise NotImplementedError

    @abstractmethod
    async def get_job(self, job_id: str) -> VectorIndexJobSummary | None:
        raise NotImplementedError

    @abstractmethod
    async def get_request(self, job_id: str) -> VectorIndexJobRequest | None:
        raise NotImplementedError

    @abstractmethod
    async def get_events(self, job_id: str) -> list[VectorIndexJobEvent]:
        raise NotImplementedError

    @abstractmethod
    async def update_job(self, job_id: str, **changes: Any) -> VectorIndexJobSummary | None:
        raise NotImplementedError

    @abstractmethod
    async def finish_job(
        self,
        job_id: str,
        *,
        status: VectorIndexJobStatus,
        last_error: str | None = None,
    ) -> VectorIndexJobSummary | None:
        raise NotImplementedError

    @abstractmethod
    async def append_event(self, event: VectorIndexJobEvent) -> VectorIndexJobEvent:
        raise NotImplementedError

    @abstractmethod
    async def find_active_job(self, scope: VectorIndexScope) -> VectorIndexJobSummary | None:
        raise NotImplementedError

    async def close(self) -> None:
        return None


class InMemoryVectorIndexJobStore(VectorIndexJobStore):
    def __init__(self) -> None:
        self._jobs: dict[str, VectorIndexJobSummary] = {}
        self._requests: dict[str, VectorIndexJobRequest] = {}
        self._events: dict[str, list[VectorIndexJobEvent]] = defaultdict(list)

    async def ensure_constraints(self) -> None:
        return None

    async def create_job(
        self,
        *,
        mode: VectorIndexJobMode,
        request: VectorIndexJobRequest,
        batch_size: int,
    ) -> VectorIndexJobSummary:
        job = VectorIndexJobSummary(
            job_id=str(uuid4()),
            mode=mode,
            scope=request.scope,
            status=VectorIndexJobStatus.queued,
            batch_size=batch_size,
        )
        self._jobs[job.job_id] = job
        self._requests[job.job_id] = request.model_copy(deep=True)
        return job.model_copy(deep=True)

    async def get_job(self, job_id: str) -> VectorIndexJobSummary | None:
        job = self._jobs.get(job_id)
        return job.model_copy(deep=True) if job else None

    async def get_request(self, job_id: str) -> VectorIndexJobRequest | None:
        request = self._requests.get(job_id)
        return request.model_copy(deep=True) if request else None

    async def get_events(self, job_id: str) -> list[VectorIndexJobEvent]:
        return [event.model_copy(deep=True) for event in self._events.get(job_id, [])]

    async def update_job(self, job_id: str, **changes: Any) -> VectorIndexJobSummary | None:
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
        status: VectorIndexJobStatus,
        last_error: str | None = None,
    ) -> VectorIndexJobSummary | None:
        job = self._jobs.get(job_id)
        if job is None:
            return None
        completed_at = utcnow()
        job.status = status
        job.last_error = last_error
        job.updated_at = completed_at
        job.completed_at = completed_at
        self._jobs[job_id] = job
        return job.model_copy(deep=True)

    async def append_event(self, event: VectorIndexJobEvent) -> VectorIndexJobEvent:
        self._events[event.job_id].append(event.model_copy(deep=True))
        return event.model_copy(deep=True)

    async def find_active_job(self, scope: VectorIndexScope) -> VectorIndexJobSummary | None:
        for job in self._jobs.values():
            if job.scope == scope and job.status in {
                VectorIndexJobStatus.queued,
                VectorIndexJobStatus.running,
            }:
                return job.model_copy(deep=True)
        return None


class Neo4jVectorIndexJobStore(VectorIndexJobStore):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._enabled = bool(
            settings.neo4j_uri and settings.neo4j_username and settings.neo4j_password
        )
        self._driver = None
        self._job_locks: dict[str, asyncio.Lock] = {}

    async def connect(self) -> None:
        if not self._enabled or self._driver is not None:
            return
        self._driver = AsyncGraphDatabase.driver(
            self._settings.neo4j_uri,
            auth=(self._settings.neo4j_username, self._settings.neo4j_password),
        )

    async def close(self) -> None:
        if self._driver is not None:
            await self._driver.close()
            self._driver = None

    async def ensure_constraints(self) -> None:
        if not self._enabled:
            return
        await self.connect()
        async with self._driver.session() as session:
            await session.run(
                "CREATE CONSTRAINT vector_index_job_id IF NOT EXISTS "
                "FOR (job:VectorIndexJob) REQUIRE job.job_id IS UNIQUE"
            )

    async def create_job(
        self,
        *,
        mode: VectorIndexJobMode,
        request: VectorIndexJobRequest,
        batch_size: int,
    ) -> VectorIndexJobSummary:
        summary = VectorIndexJobSummary(
            job_id=str(uuid4()),
            mode=mode,
            scope=request.scope,
            status=VectorIndexJobStatus.queued,
            batch_size=batch_size,
        )
        await self._write_snapshot(summary, request, [])
        return summary.model_copy(deep=True)

    async def get_job(self, job_id: str) -> VectorIndexJobSummary | None:
        snapshot = await self._read_snapshot(job_id)
        return snapshot[0].model_copy(deep=True) if snapshot else None

    async def get_request(self, job_id: str) -> VectorIndexJobRequest | None:
        snapshot = await self._read_snapshot(job_id)
        return snapshot[1].model_copy(deep=True) if snapshot else None

    async def get_events(self, job_id: str) -> list[VectorIndexJobEvent]:
        snapshot = await self._read_snapshot(job_id)
        return [event.model_copy(deep=True) for event in snapshot[2]] if snapshot else []

    async def update_job(self, job_id: str, **changes: Any) -> VectorIndexJobSummary | None:
        async with self._job_lock(job_id):
            snapshot = await self._read_snapshot_locked(job_id)
            if snapshot is None:
                return None
            job, request, events = snapshot
            updated = job.model_copy(update={"updated_at": utcnow(), **changes})
            await self._write_snapshot_locked(updated, request, events)
            return updated.model_copy(deep=True)

    async def finish_job(
        self,
        job_id: str,
        *,
        status: VectorIndexJobStatus,
        last_error: str | None = None,
    ) -> VectorIndexJobSummary | None:
        async with self._job_lock(job_id):
            snapshot = await self._read_snapshot_locked(job_id)
            if snapshot is None:
                return None
            job, request, events = snapshot
            completed_at = utcnow()
            updated = job.model_copy(
                update={
                    "status": status,
                    "last_error": last_error,
                    "updated_at": completed_at,
                    "completed_at": completed_at,
                }
            )
            await self._write_snapshot_locked(updated, request, events)
            return updated.model_copy(deep=True)

    async def append_event(self, event: VectorIndexJobEvent) -> VectorIndexJobEvent:
        async with self._job_lock(event.job_id):
            snapshot = await self._read_snapshot_locked(event.job_id)
            if snapshot is None:
                return event.model_copy(deep=True)
            job, request, events = snapshot
            events.append(event.model_copy(deep=True))
            await self._write_snapshot_locked(job, request, events)
        return event.model_copy(deep=True)

    async def find_active_job(self, scope: VectorIndexScope) -> VectorIndexJobSummary | None:
        if not self._enabled:
            return None
        await self.connect()
        async with self._driver.session() as session:
            result = await session.run(
                """
                MATCH (job:VectorIndexJob)
                WHERE job.scope = $scope AND job.status IN $statuses
                RETURN properties(job) AS job
                ORDER BY job.updated_at DESC
                LIMIT 1
                """,
                scope=scope.value,
                statuses=[
                    VectorIndexJobStatus.queued.value,
                    VectorIndexJobStatus.running.value,
                ],
            )
            record = await result.single()
        if record is None:
            return None
        return self._job_from_properties(record["job"])

    async def _read_snapshot(
        self,
        job_id: str,
    ) -> tuple[VectorIndexJobSummary, VectorIndexJobRequest, list[VectorIndexJobEvent]] | None:
        async with self._job_lock(job_id):
            return await self._read_snapshot_locked(job_id)

    async def _read_snapshot_locked(
        self,
        job_id: str,
    ) -> tuple[VectorIndexJobSummary, VectorIndexJobRequest, list[VectorIndexJobEvent]] | None:
        if not self._enabled:
            return None
        await self.connect()
        async with self._driver.session() as session:
            result = await session.run(
                """
                MATCH (job:VectorIndexJob {job_id: $job_id})
                RETURN properties(job) AS job
                """,
                job_id=job_id,
            )
            record = await result.single()
        if record is None:
            return None
        properties = record["job"]
        request = VectorIndexJobRequest.model_validate(json.loads(properties["request_json"]))
        events = [
            VectorIndexJobEvent.model_validate(payload)
            for payload in json.loads(properties.get("events_json") or "[]")
        ]
        return self._job_from_properties(properties), request, events

    async def _write_snapshot(
        self,
        job: VectorIndexJobSummary,
        request: VectorIndexJobRequest,
        events: list[VectorIndexJobEvent],
    ) -> None:
        async with self._job_lock(job.job_id):
            await self._write_snapshot_locked(job, request, events)

    async def _write_snapshot_locked(
        self,
        job: VectorIndexJobSummary,
        request: VectorIndexJobRequest,
        events: list[VectorIndexJobEvent],
    ) -> None:
        if not self._enabled:
            return
        await self.connect()
        payload = {
            "job_id": job.job_id,
            "mode": job.mode.value,
            "scope": job.scope.value,
            "status": job.status.value,
            "created_at": job.created_at.isoformat(),
            "updated_at": job.updated_at.isoformat(),
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "batch_size": job.batch_size,
            "scanned_count": job.scanned_count,
            "synced_count": job.synced_count,
            "failed_count": job.failed_count,
            "pending_count": job.pending_count,
            "last_error": job.last_error,
            "request_json": json.dumps(request.model_dump(mode="json"), ensure_ascii=False),
            "events_json": json.dumps(
                [event.model_dump(mode="json") for event in events],
                ensure_ascii=False,
                default=str,
            ),
        }
        async with self._driver.session() as session:
            await session.run(
                """
                MERGE (job:VectorIndexJob {job_id: $job_id})
                SET job.mode = $mode,
                    job.scope = $scope,
                    job.status = $status,
                    job.created_at = datetime($created_at),
                    job.updated_at = datetime($updated_at),
                    job.completed_at = CASE
                        WHEN $completed_at IS NULL THEN null
                        ELSE datetime($completed_at)
                    END,
                    job.batch_size = $batch_size,
                    job.scanned_count = $scanned_count,
                    job.synced_count = $synced_count,
                    job.failed_count = $failed_count,
                    job.pending_count = $pending_count,
                    job.last_error = $last_error,
                    job.request_json = $request_json,
                    job.events_json = $events_json
                """,
                **payload,
            )

    def _job_from_properties(self, properties: dict[str, Any]) -> VectorIndexJobSummary:
        return VectorIndexJobSummary(
            job_id=str(properties["job_id"]),
            mode=VectorIndexJobMode(str(properties["mode"])),
            scope=VectorIndexScope(str(properties["scope"])),
            status=VectorIndexJobStatus(str(properties["status"])),
            created_at=self._to_datetime(properties.get("created_at")) or utcnow(),
            updated_at=self._to_datetime(properties.get("updated_at")) or utcnow(),
            completed_at=self._to_datetime(properties.get("completed_at")),
            batch_size=int(properties.get("batch_size") or 1),
            scanned_count=int(properties.get("scanned_count") or 0),
            synced_count=int(properties.get("synced_count") or 0),
            failed_count=int(properties.get("failed_count") or 0),
            pending_count=int(properties.get("pending_count") or 0),
            last_error=properties.get("last_error"),
        )

    def _job_lock(self, job_id: str) -> asyncio.Lock:
        lock = self._job_locks.get(job_id)
        if lock is None:
            lock = asyncio.Lock()
            self._job_locks[job_id] = lock
        return lock

    @staticmethod
    def _to_datetime(value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if hasattr(value, "to_native"):
            native = value.to_native()
            if isinstance(native, datetime):
                return native
        if isinstance(value, str):
            return datetime.fromisoformat(value)
        return None
