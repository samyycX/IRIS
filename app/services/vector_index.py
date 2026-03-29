from __future__ import annotations

import asyncio
import contextlib

from fastapi import HTTPException

from app.core.config import Settings
from app.core.logging import get_logger
from app.models import (
    EmbeddingCandidate,
    VectorIndexJobCreateResponse,
    VectorIndexJobEvent,
    VectorIndexJobMode,
    VectorIndexJobRequest,
    VectorIndexJobStage,
    VectorIndexJobStatus,
    VectorIndexJobSummary,
    VectorIndexQueryPreviewRequest,
    VectorIndexScope,
)
from app.repos.graph_repo import Neo4jGraphRepository
from app.repos.vector_index_job_store import VectorIndexJobStore
from app.services.llm import EmbeddingClient

logger = get_logger(__name__)


class VectorIndexService:
    def __init__(
        self,
        settings: Settings,
        graph_repo: Neo4jGraphRepository,
        embedding_client: EmbeddingClient,
        job_store: VectorIndexJobStore,
    ) -> None:
        self._settings = settings
        self._graph_repo = graph_repo
        self._embedding_client = embedding_client
        self._job_store = job_store
        self._local_tasks: dict[str, asyncio.Task] = {}

    async def initialize(self) -> None:
        await self._job_store.ensure_constraints()

    async def shutdown(self) -> None:
        for task in list(self._local_tasks.values()):
            task.cancel()
        for task in list(self._local_tasks.values()):
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self._job_store.close()

    async def create_backfill_job(
        self,
        request: VectorIndexJobRequest,
    ) -> VectorIndexJobCreateResponse:
        summary = await self._create_job(VectorIndexJobMode.backfill, request)
        return VectorIndexJobCreateResponse(job_id=summary.job_id, status=summary.status)

    async def create_reindex_job(
        self,
        request: VectorIndexJobRequest,
    ) -> VectorIndexJobCreateResponse:
        summary = await self._create_job(VectorIndexJobMode.reindex, request)
        return VectorIndexJobCreateResponse(job_id=summary.job_id, status=summary.status)

    async def get_job(self, job_id: str) -> VectorIndexJobSummary | None:
        return await self._job_store.get_job(job_id)

    async def get_events(self, job_id: str) -> list[VectorIndexJobEvent]:
        return await self._job_store.get_events(job_id)

    async def query_preview(self, request: VectorIndexQueryPreviewRequest) -> dict[str, list[dict]]:
        return await self._graph_repo.query_preview(
            request.query,
            entity_limit=request.entity_limit,
            page_limit=request.page_limit,
            relation_limit=request.relation_limit,
        )

    async def _create_job(
        self,
        mode: VectorIndexJobMode,
        request: VectorIndexJobRequest,
    ) -> VectorIndexJobSummary:
        self._ensure_embedding_enabled()
        await self._ensure_no_conflicting_job(request.scope)
        batch_size = request.batch_size or self._settings.embedding_batch_size
        summary = await self._job_store.create_job(
            mode=mode,
            request=request,
            batch_size=batch_size,
        )
        await self._job_store.append_event(
            VectorIndexJobEvent(
                job_id=summary.job_id,
                stage=VectorIndexJobStage.queued,
                message="向量索引任务已创建，等待执行",
                data={
                    "mode": mode.value,
                    "scope": request.scope.value,
                    "batch_size": batch_size,
                },
            )
        )
        self._enqueue(summary.job_id)
        return summary

    def _enqueue(self, job_id: str) -> None:
        existing = self._local_tasks.get(job_id)
        if existing is not None and not existing.done():
            return
        task = asyncio.create_task(self._run_job(job_id), name=f"vector-index:{job_id}")
        self._local_tasks[job_id] = task
        task.add_done_callback(lambda _: self._local_tasks.pop(job_id, None))

    async def _run_job(self, job_id: str) -> None:
        request = await self._job_store.get_request(job_id)
        job = await self._job_store.get_job(job_id)
        if request is None or job is None:
            return
        await self._job_store.update_job(job_id, status=VectorIndexJobStatus.running)
        await self._job_store.append_event(
            VectorIndexJobEvent(
                job_id=job_id,
                stage=VectorIndexJobStage.scanning,
                message="开始扫描待同步节点",
                data={"scope": request.scope.value, "mode": job.mode.value},
            )
        )

        attempted: set[str] = set()
        scanned_count = 0
        synced_count = 0
        failed_count = 0
        try:
            while True:
                candidates = await self._graph_repo.list_embedding_candidates(
                    request.scope,
                    limit=job.batch_size,
                    reindex=job.mode == VectorIndexJobMode.reindex,
                    exclude_source_keys=sorted(attempted),
                )
                if not candidates:
                    break

                attempted.update(candidate.source_key for candidate in candidates)
                await self._job_store.update_job(
                    job_id,
                    pending_count=len(candidates),
                    scanned_count=scanned_count,
                    synced_count=synced_count,
                    failed_count=failed_count,
                )
                await self._job_store.append_event(
                    VectorIndexJobEvent(
                        job_id=job_id,
                        stage=VectorIndexJobStage.embedding,
                        message="开始为一批节点生成 embedding",
                        data={
                            "batch_size": len(candidates),
                            "scope": request.scope.value,
                        },
                    )
                )
                batch_scanned, batch_synced, batch_failed = await self._process_candidates(candidates)
                scanned_count += batch_scanned
                synced_count += batch_synced
                failed_count += batch_failed
                await self._job_store.update_job(
                    job_id,
                    scanned_count=scanned_count,
                    synced_count=synced_count,
                    failed_count=failed_count,
                    pending_count=0,
                )

            await self._job_store.finish_job(job_id, status=VectorIndexJobStatus.completed)
            await self._job_store.append_event(
                VectorIndexJobEvent(
                    job_id=job_id,
                    stage=VectorIndexJobStage.completed,
                    message="向量索引任务执行完成",
                    data={
                        "scanned_count": scanned_count,
                        "synced_count": synced_count,
                        "failed_count": failed_count,
                    },
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("vector_index_job_failed", job_id=job_id, error=str(exc))
            await self._job_store.finish_job(
                job_id,
                status=VectorIndexJobStatus.failed,
                last_error=str(exc),
            )
            await self._job_store.append_event(
                VectorIndexJobEvent(
                    job_id=job_id,
                    stage=VectorIndexJobStage.failed,
                    message="向量索引任务执行失败",
                    data={"error": str(exc)},
                )
            )

    async def _process_candidates(self, candidates: list[EmbeddingCandidate]) -> tuple[int, int, int]:
        if not candidates:
            return 0, 0, 0
        try:
            embeddings = await self._embedding_client.embed_texts(
                [candidate.input_text for candidate in candidates]
            )
            await self._graph_repo.upsert_embeddings(candidates, embeddings)
            return len(candidates), len(candidates), 0
        except Exception:  # noqa: BLE001
            scanned = 0
            synced = 0
            failed = 0
            for candidate in candidates:
                scanned += 1
                try:
                    embedding = await self._embedding_client.embed_text(candidate.input_text)
                    await self._graph_repo.upsert_embeddings([candidate], [embedding])
                    synced += 1
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    await self._graph_repo.mark_embedding_failed(candidate, str(exc))
            return scanned, synced, failed

    async def _ensure_no_conflicting_job(self, scope: VectorIndexScope) -> None:
        active_jobs: list[VectorIndexJobSummary] = []
        for candidate_scope in VectorIndexScope:
            if candidate_scope == VectorIndexScope.all or scope == VectorIndexScope.all or candidate_scope == scope:
                active = await self._job_store.find_active_job(candidate_scope)
                if active is not None:
                    active_jobs.append(active)
        if active_jobs:
            active = active_jobs[0]
            raise HTTPException(
                status_code=409,
                detail=f"已有运行中的向量索引任务：{active.job_id}",
            )

    def _ensure_embedding_enabled(self) -> None:
        if self._embedding_client.enabled:
            return
        raise HTTPException(status_code=503, detail="Embedding client is not configured")
