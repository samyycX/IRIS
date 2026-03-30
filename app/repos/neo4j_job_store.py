from __future__ import annotations

import asyncio
import contextlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from neo4j import AsyncGraphDatabase
from neo4j.exceptions import Neo4jError

from app.core.config import Settings
from app.core.logging import get_logger
from app.models import (
    GraphUpdateResult,
    JobInputType,
    JobCheckpoint,
    JobEvent,
    JobRequest,
    JobStatus,
    JobSummary,
    utcnow,
)
from app.repos.job_store import JobStore

logger = get_logger(__name__)


@dataclass
class _JobSnapshot:
    job: JobSummary
    request: JobRequest | None = None
    events: list[JobEvent] = field(default_factory=list)
    checkpoint: JobCheckpoint | None = None
    visited_urls: set[str] = field(default_factory=set)


class Neo4jJobStore(JobStore):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._driver = None
        self._enabled = bool(
            settings.neo4j_uri and settings.neo4j_username and settings.neo4j_password
        )
        self._global_seen_ttl = timedelta(days=settings.visited_url_ttl_days)
        self._global_visited: dict[str, datetime] = {}
        self._event_condition = asyncio.Condition()
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

    async def mark_neo4j_unavailable(self) -> None:
        self._enabled = False
        await self.close()

    async def create_job(self, request: JobRequest, max_depth: int, max_pages: int) -> JobSummary:
        job = JobSummary(
            job_id=str(uuid4()),
            input_type=request.input_type,
            seed=request.seed(),
            status=JobStatus.queued,
            max_depth=max_depth,
            max_pages=max_pages,
        )
        snapshot = _JobSnapshot(job=job, request=request.model_copy(deep=True))
        await self._write_snapshot(snapshot)
        return job.model_copy(deep=True)

    async def list_jobs(self) -> list[JobSummary]:
        if not self._enabled:
            return []
        await self.connect()
        async with self._driver.session() as session:
            result = await session.run(
                """
                MATCH (job:CrawlJob)
                RETURN properties(job) AS job
                ORDER BY job.updated_at DESC, job.created_at DESC
                """
            )
            jobs: list[JobSummary] = []
            async for record in result:
                jobs.append(self._job_from_properties(record["job"]))
            return jobs

    async def get_job(self, job_id: str) -> JobSummary | None:
        snapshot = await self._read_snapshot(job_id)
        return snapshot.job.model_copy(deep=True) if snapshot else None

    async def update_job(self, job_id: str, **changes: Any) -> JobSummary | None:
        async with self._job_lock(job_id):
            snapshot = await self._read_snapshot_locked(job_id)
            if snapshot is None:
                return None
            job = snapshot.job.model_copy(deep=True)
            for key, value in changes.items():
                if key == "graph_update" and value is not None and not isinstance(
                    value, GraphUpdateResult
                ):
                    value = GraphUpdateResult.model_validate(value)
                setattr(job, key, value)
            job.updated_at = utcnow()
            snapshot.job = job
            await self._write_snapshot_locked(snapshot)
            return job.model_copy(deep=True)

    async def finish_job(
        self,
        job_id: str,
        status: JobStatus,
        *,
        graph_update: GraphUpdateResult | None = None,
        last_error: str | None = None,
    ) -> JobSummary | None:
        async with self._job_lock(job_id):
            snapshot = await self._read_snapshot_locked(job_id)
            if snapshot is None:
                return None
            completed_at = utcnow()
            snapshot.job.status = status
            snapshot.job.completed_at = completed_at
            snapshot.job.updated_at = completed_at
            snapshot.job.last_error = last_error
            if graph_update is not None:
                snapshot.job.graph_update = graph_update.model_copy(deep=True)
            if status in {JobStatus.completed, JobStatus.cancelled}:
                snapshot.job.resume_available = False
                snapshot.job.checkpoint_updated_at = None
                snapshot.job.completion_reason = status.value
                snapshot.checkpoint = None
            await self._write_snapshot_locked(snapshot)
        async with self._event_condition:
            self._event_condition.notify_all()
            return snapshot.job.model_copy(deep=True)

    async def append_event(self, event: JobEvent) -> JobEvent:
        async with self._job_lock(event.job_id):
            snapshot = await self._read_snapshot_locked(event.job_id)
            if snapshot is None:
                return event.model_copy(deep=True)
            snapshot.events.append(event.model_copy(deep=True))
            await self._write_snapshot_locked(snapshot)
        async with self._event_condition:
            self._event_condition.notify_all()
        return event.model_copy(deep=True)

    async def get_events(self, job_id: str) -> list[JobEvent]:
        snapshot = await self._read_snapshot(job_id)
        if snapshot is None:
            return []
        return [event.model_copy(deep=True) for event in snapshot.events]

    async def remember_visited_url(self, job_id: str, canonical_url: str) -> bool:
        async with self._job_lock(job_id):
            snapshot = await self._read_snapshot_locked(job_id)
            if snapshot is None:
                return False
            seen = canonical_url in snapshot.visited_urls
            if not seen:
                snapshot.visited_urls.add(canonical_url)
                snapshot.job.visited_count = len(snapshot.visited_urls)
                snapshot.job.updated_at = utcnow()
                if snapshot.checkpoint is not None:
                    snapshot.checkpoint.visited_urls = sorted(snapshot.visited_urls)
                    snapshot.checkpoint.updated_at = snapshot.job.updated_at
                    snapshot.job.checkpoint_updated_at = snapshot.checkpoint.updated_at
                await self._write_snapshot_locked(snapshot)
            self._global_visited[canonical_url] = utcnow()
            return not seen

    async def has_job_visited_url(self, job_id: str, canonical_url: str) -> bool:
        snapshot = await self._read_snapshot(job_id)
        return bool(snapshot and canonical_url in snapshot.visited_urls)

    async def has_seen_url_globally(self, canonical_url: str) -> bool:
        cutoff = utcnow() - self._global_seen_ttl
        seen_at = self._global_visited.get(canonical_url)
        if seen_at is None:
            return False
        if seen_at < cutoff:
            self._global_visited.pop(canonical_url, None)
            return False
        return True

    async def set_status(self, job_id: str, status: JobStatus, last_error: str | None = None) -> None:
        async with self._job_lock(job_id):
            snapshot = await self._read_snapshot_locked(job_id)
            if snapshot is None:
                return
            snapshot.job.status = status
            snapshot.job.last_error = last_error
            snapshot.job.updated_at = utcnow()
            if status not in {JobStatus.completed, JobStatus.failed, JobStatus.cancelled}:
                snapshot.job.completed_at = None
            await self._write_snapshot_locked(snapshot)

    async def set_queue_size(self, job_id: str, queue_size: int) -> None:
        async with self._job_lock(job_id):
            snapshot = await self._read_snapshot_locked(job_id)
            if snapshot is None:
                return
            snapshot.job.queued_count = queue_size
            snapshot.job.updated_at = utcnow()
            await self._write_snapshot_locked(snapshot)

    async def increment_failed(self, job_id: str) -> None:
        async with self._job_lock(job_id):
            snapshot = await self._read_snapshot_locked(job_id)
            if snapshot is None:
                return
            snapshot.job.failed_count += 1
            snapshot.job.updated_at = utcnow()
            await self._write_snapshot_locked(snapshot)

    async def get_request(self, job_id: str) -> JobRequest | None:
        snapshot = await self._read_snapshot(job_id)
        return snapshot.request.model_copy(deep=True) if snapshot and snapshot.request else None

    async def save_checkpoint(self, job_id: str, checkpoint: JobCheckpoint | None) -> None:
        async with self._job_lock(job_id):
            snapshot = await self._read_snapshot_locked(job_id)
            if snapshot is None:
                return
            if checkpoint is None:
                snapshot.checkpoint = None
                snapshot.job.resume_available = False
                snapshot.job.checkpoint_updated_at = None
            else:
                copied = checkpoint.model_copy(deep=True)
                copied.updated_at = utcnow()
                if not copied.visited_urls:
                    copied.visited_urls = sorted(snapshot.visited_urls)
                snapshot.checkpoint = copied
                snapshot.visited_urls = set(copied.visited_urls)
                snapshot.job.resume_available = bool(copied.pending_queue or copied.in_progress)
                snapshot.job.checkpoint_updated_at = copied.updated_at
                snapshot.job.completion_reason = copied.completion_reason
                snapshot.job.visited_count = len(snapshot.visited_urls)
                snapshot.job.queued_count = len(copied.pending_queue)
            snapshot.job.updated_at = utcnow()
            await self._write_snapshot_locked(snapshot)

    async def get_checkpoint(self, job_id: str) -> JobCheckpoint | None:
        snapshot = await self._read_snapshot(job_id)
        return snapshot.checkpoint.model_copy(deep=True) if snapshot and snapshot.checkpoint else None

    async def wait_for_event(self, job_id: str, after_count: int) -> None:
        async with self._event_condition:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._event_condition.wait(), timeout=5)

    async def mark_incomplete_jobs_interrupted(self) -> int:
        if not self._enabled:
            return 0
        await self.connect()
        now = utcnow().isoformat()
        async with self._driver.session() as session:
            result = await session.run(
                """
                MATCH (job:CrawlJob)
                WHERE job.status IN $active_statuses
                SET job.status = $interrupted_status,
                    job.updated_at = datetime($updated_at),
                    job.completed_at = null,
                    job.resume_available = coalesce(job.checkpoint_json, "") <> "",
                    job.completion_reason = coalesce(job.completion_reason, "interrupted")
                RETURN count(job) AS affected
                """,
                active_statuses=[JobStatus.queued.value, JobStatus.running.value],
                interrupted_status=JobStatus.interrupted.value,
                updated_at=now,
            )
            record = await result.single()
            return int(record["affected"]) if record else 0

    async def _read_snapshot(self, job_id: str) -> _JobSnapshot | None:
        async with self._job_lock(job_id):
            return await self._read_snapshot_locked(job_id)

    async def _read_snapshot_locked(self, job_id: str) -> _JobSnapshot | None:
        if not self._enabled:
            return None
        await self.connect()
        async with self._driver.session() as session:
            result = await session.run(
                """
                MATCH (job:CrawlJob {job_id: $job_id})
                RETURN properties(job) AS job
                """,
                job_id=job_id,
            )
            record = await result.single()
        if record is None:
            return None
        return self._snapshot_from_properties(record["job"])

    async def _write_snapshot(self, snapshot: _JobSnapshot) -> None:
        async with self._job_lock(snapshot.job.job_id):
            await self._write_snapshot_locked(snapshot)

    async def _write_snapshot_locked(self, snapshot: _JobSnapshot) -> None:
        if not self._enabled:
            return
        await self.connect()
        payload = self._snapshot_payload(snapshot)
        try:
            async with self._driver.session() as session:
                await session.run(
                    """
                    MERGE (job:CrawlJob {job_id: $job_id})
                    SET job.input_type = $input_type,
                        job.seed = $seed,
                        job.status = $status,
                        job.created_at = datetime($created_at),
                        job.started_at = coalesce(job.started_at, datetime($created_at)),
                        job.updated_at = datetime($updated_at),
                        job.completed_at = CASE
                            WHEN $completed_at IS NULL THEN null
                            ELSE datetime($completed_at)
                        END,
                        job.max_depth = $max_depth,
                        job.max_pages = $max_pages,
                        job.visited_count = $visited_count,
                        job.queued_count = $queued_count,
                        job.failed_count = $failed_count,
                        job.last_error = $last_error,
                        job.summary = $summary,
                        job.change_log = $change_log,
                        job.request_json = $request_json,
                        job.graph_update_json = $graph_update_json,
                        job.created_entities = $created_entities,
                        job.updated_entities = $updated_entities,
                        job.created_sources = $created_sources,
                        job.created_relationships = $created_relationships,
                        job.deleted_relationships = $deleted_relationships,
                        job.resume_available = $resume_available,
                        job.checkpoint_updated_at = CASE
                            WHEN $checkpoint_updated_at IS NULL THEN null
                            ELSE datetime($checkpoint_updated_at)
                        END,
                        job.completion_reason = $completion_reason,
                        job.events_json = $events_json,
                        job.checkpoint_json = $checkpoint_json,
                        job.visited_urls_json = $visited_urls_json
                    """,
                    **payload,
                )
        except Neo4jError as exc:
            logger.warning("neo4j_job_store_write_failed", job_id=snapshot.job.job_id, error=str(exc))
            raise

    def _snapshot_from_properties(self, properties: dict[str, Any]) -> _JobSnapshot:
        job = self._job_from_properties(properties)
        request_json = properties.get("request_json")
        events_json = properties.get("events_json")
        checkpoint_json = properties.get("checkpoint_json")
        visited_urls_json = properties.get("visited_urls_json")
        request = JobRequest.model_validate(json.loads(request_json)) if request_json else None
        events = [
            JobEvent.model_validate(payload)
            for payload in self._loads_json_list(events_json, [])
        ]
        checkpoint = (
            JobCheckpoint.model_validate(json.loads(checkpoint_json))
            if checkpoint_json
            else None
        )
        visited_urls = set(self._loads_json_list(visited_urls_json, []))
        if checkpoint is not None and not checkpoint.visited_urls:
            checkpoint.visited_urls = sorted(visited_urls)
        return _JobSnapshot(
            job=job,
            request=request,
            events=events,
            checkpoint=checkpoint,
            visited_urls=visited_urls,
        )

    def _snapshot_payload(self, snapshot: _JobSnapshot) -> dict[str, Any]:
        graph_update = (
            snapshot.job.graph_update.model_dump(mode="json") if snapshot.job.graph_update else None
        )
        return {
            "job_id": snapshot.job.job_id,
            "input_type": snapshot.job.input_type.value,
            "seed": snapshot.job.seed,
            "status": snapshot.job.status.value,
            "created_at": snapshot.job.created_at.isoformat(),
            "updated_at": snapshot.job.updated_at.isoformat(),
            "completed_at": snapshot.job.completed_at.isoformat()
            if snapshot.job.completed_at
            else None,
            "max_depth": snapshot.job.max_depth,
            "max_pages": snapshot.job.max_pages,
            "visited_count": snapshot.job.visited_count,
            "queued_count": snapshot.job.queued_count,
            "failed_count": snapshot.job.failed_count,
            "last_error": snapshot.job.last_error,
            "summary": self._build_job_summary_text(snapshot.job),
            "change_log": self._build_job_change_log_text(snapshot.job),
            "request_json": json.dumps(
                snapshot.request.model_dump(mode="json") if snapshot.request else None,
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
            if snapshot.request
            else None,
            "graph_update_json": json.dumps(graph_update, ensure_ascii=False, sort_keys=True, default=str)
            if graph_update is not None
            else None,
            "created_entities": list(snapshot.job.graph_update.created_entities)
            if snapshot.job.graph_update
            else [],
            "updated_entities": list(snapshot.job.graph_update.updated_entities)
            if snapshot.job.graph_update
            else [],
            "created_sources": list(snapshot.job.graph_update.created_sources)
            if snapshot.job.graph_update
            else [],
            "created_relationships": snapshot.job.graph_update.created_relationships
            if snapshot.job.graph_update
            else 0,
            "deleted_relationships": snapshot.job.graph_update.deleted_relationships
            if snapshot.job.graph_update
            else 0,
            "resume_available": snapshot.job.resume_available,
            "checkpoint_updated_at": snapshot.job.checkpoint_updated_at.isoformat()
            if snapshot.job.checkpoint_updated_at
            else None,
            "completion_reason": snapshot.job.completion_reason,
            "events_json": json.dumps(
                [event.model_dump(mode="json") for event in snapshot.events],
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ),
            "checkpoint_json": json.dumps(
                snapshot.checkpoint.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
            if snapshot.checkpoint
            else None,
            "visited_urls_json": json.dumps(
                sorted(snapshot.visited_urls),
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ),
        }

    def _job_from_properties(self, properties: dict[str, Any]) -> JobSummary:
        request_payload = self._loads_json_dict(properties.get("request_json"))
        graph_update_json = properties.get("graph_update_json")
        graph_update = (
            GraphUpdateResult.model_validate(json.loads(graph_update_json))
            if graph_update_json
            else None
        )
        return JobSummary(
            job_id=str(properties.get("job_id", "")),
            input_type=self._resolve_input_type(properties, request_payload),
            seed=str(properties.get("seed", "")),
            status=self._resolve_status(properties),
            created_at=self._to_datetime(properties.get("created_at")) or utcnow(),
            updated_at=self._to_datetime(properties.get("updated_at")) or utcnow(),
            completed_at=self._to_datetime(properties.get("completed_at")),
            max_depth=int(properties.get("max_depth", 0) or 0),
            max_pages=int(properties.get("max_pages", 0) or 0),
            visited_count=int(properties.get("visited_count", 0) or 0),
            queued_count=int(properties.get("queued_count", 0) or 0),
            failed_count=int(properties.get("failed_count", 0) or 0),
            last_error=properties.get("last_error"),
            graph_update=graph_update,
            resume_available=bool(properties.get("resume_available")),
            checkpoint_updated_at=self._to_datetime(properties.get("checkpoint_updated_at")),
            completion_reason=properties.get("completion_reason"),
        )

    def _job_lock(self, job_id: str) -> asyncio.Lock:
        lock = self._job_locks.get(job_id)
        if lock is None:
            lock = asyncio.Lock()
            self._job_locks[job_id] = lock
        return lock

    @staticmethod
    def _loads_json_list(value: str | None, default: list[Any]) -> list[Any]:
        if not value:
            return list(default)
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return list(default)
        return payload if isinstance(payload, list) else list(default)

    @staticmethod
    def _loads_json_dict(value: str | None) -> dict[str, Any]:
        if not value:
            return {}
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

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

    @staticmethod
    def _resolve_input_type(
        properties: dict[str, Any],
        request_payload: dict[str, Any],
    ) -> JobInputType:
        raw = properties.get("input_type") or request_payload.get("input_type")
        if raw in {item.value for item in JobInputType}:
            return JobInputType(raw)
        seed = str(properties.get("seed") or "").strip()
        if request_payload.get("url") or seed.startswith(("http://", "https://")):
            return JobInputType.url
        if request_payload.get("instruction"):
            return JobInputType.instruction
        return JobInputType.entity

    @staticmethod
    def _resolve_status(properties: dict[str, Any]) -> JobStatus:
        raw = properties.get("status")
        if raw in {item.value for item in JobStatus}:
            return JobStatus(raw)
        if properties.get("completed_at"):
            return JobStatus.completed
        if properties.get("last_error"):
            return JobStatus.failed
        if properties.get("checkpoint_json"):
            return JobStatus.interrupted
        return JobStatus.completed if properties.get("graph_update_json") else JobStatus.interrupted

    @staticmethod
    def _build_job_summary_text(job: JobSummary) -> str:
        parts = [
            f"任务状态：{job.status.value}",
            f"输入类型：{job.input_type.value}",
            f"种子：{job.seed}",
            f"访问页面：{job.visited_count}",
            f"队列长度：{job.queued_count}",
            f"失败数：{job.failed_count}",
            f"抓取限制：深度 {job.max_depth} / 页面 {job.max_pages}",
        ]
        if job.graph_update is not None:
            parts.append(
                "图谱变更："
                f"新增来源 {len(job.graph_update.created_sources)} 个，"
                f"新增实体 {len(job.graph_update.created_entities)} 个，"
                f"更新实体 {len(job.graph_update.updated_entities)} 个，"
                f"新增关系 {job.graph_update.created_relationships} 条，"
                f"删除关系 {job.graph_update.deleted_relationships} 条"
            )
        if job.last_error:
            parts.append(f"最近错误：{job.last_error}")
        if job.completed_at:
            parts.append(f"完成时间：{job.completed_at.isoformat()}")
        return "；".join(parts)

    @staticmethod
    def _build_job_change_log_text(job: JobSummary) -> str:
        lines = [
            "任务概览",
            f"- 状态：{job.status.value}",
            f"- 输入类型：{job.input_type.value}",
            f"- 种子：{job.seed}",
            f"- 创建时间：{job.created_at.isoformat()}",
            f"- 更新时间：{job.updated_at.isoformat()}",
            f"- 完成时间：{job.completed_at.isoformat() if job.completed_at else '未完成'}",
            f"- 抓取限制：最大深度 {job.max_depth}，最大页面数 {job.max_pages}",
            f"- 执行统计：访问页面 {job.visited_count}，队列剩余 {job.queued_count}，失败数 {job.failed_count}",
        ]
        if job.graph_update is not None:
            lines.extend(
                [
                    "",
                    "修改记录",
                    f"- 新增来源（{len(job.graph_update.created_sources)}）：{Neo4jJobStore._format_string_list(job.graph_update.created_sources)}",
                    f"- 新增实体（{len(job.graph_update.created_entities)}）：{Neo4jJobStore._format_string_list(job.graph_update.created_entities)}",
                    f"- 更新实体（{len(job.graph_update.updated_entities)}）：{Neo4jJobStore._format_string_list(job.graph_update.updated_entities)}",
                    f"- 新增关系：{job.graph_update.created_relationships}",
                    f"- 删除关系：{job.graph_update.deleted_relationships}",
                ]
            )
        if job.last_error:
            lines.extend(["", "错误信息", f"- {job.last_error}"])
        return "\n".join(lines)

    @staticmethod
    def _format_string_list(values: list[str], limit: int = 20) -> str:
        cleaned = [value for value in values if isinstance(value, str) and value.strip()]
        if not cleaned:
            return "无"
        if len(cleaned) <= limit:
            return "、".join(cleaned)
        remaining = len(cleaned) - limit
        return f"{'、'.join(cleaned[:limit])} 等 {len(cleaned)} 项（其余 {remaining} 项省略）"
