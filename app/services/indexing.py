from __future__ import annotations

import asyncio
import contextlib

from fastapi import HTTPException

from app.core.config import Settings
from app.core.logging import get_logger
from app.models import (
    EmbeddingCandidate,
    IndexJobCreateResponse,
    IndexJobEvent,
    IndexJobMode,
    IndexJobRequest,
    IndexJobStage,
    IndexJobStatus,
    IndexJobSummary,
    IndexPreparationRequest,
    IndexPreparationResponse,
    IndexScope,
    IndexStatusResponse,
    IndexType,
    SearchPreviewRequest,
    SearchPreviewResponse,
    TextIndexCandidate,
)
from app.repos.graph_repo import Neo4jGraphRepository
from app.repos.index_job_store import IndexJobStore
from app.services.llm.embedding_client import EmbeddingClient

logger = get_logger(__name__)


class IndexingService:
    def __init__(
        self,
        settings: Settings,
        graph_repo: Neo4jGraphRepository,
        embedding_client: EmbeddingClient,
        job_store: IndexJobStore,
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

    async def list_jobs(self) -> list[IndexJobSummary]:
        return await self._job_store.list_jobs()

    async def get_job(self, job_id: str) -> IndexJobSummary | None:
        return await self._job_store.get_job(job_id)

    async def get_events(self, job_id: str) -> list[IndexJobEvent]:
        return await self._job_store.get_events(job_id)

    async def prepare(self, request: IndexPreparationRequest) -> IndexPreparationResponse:
        if request.index_type == IndexType.vector:
            self._ensure_embedding_enabled()
            counts, candidates = await self._graph_repo.prepare_embedding_candidates(
                request.scope,
                reindex=request.mode == IndexJobMode.reindex,
                sample_limit=request.sample_limit,
            )
        else:
            counts, candidates = await self._graph_repo.prepare_fulltext_candidates(
                request.scope,
                reindex=request.mode == IndexJobMode.reindex,
                sample_limit=request.sample_limit,
            )
        total_count = sum(counts.values())
        return IndexPreparationResponse(
            index_type=request.index_type,
            mode=request.mode,
            scope=request.scope,
            total_count=total_count,
            counts=counts,
            candidates=candidates,
        )

    async def create_backfill_job(self, request: IndexJobRequest) -> IndexJobCreateResponse:
        summary = await self._create_job(IndexJobMode.backfill, request)
        return IndexJobCreateResponse(job_id=summary.job_id, status=summary.status)

    async def create_reindex_job(self, request: IndexJobRequest) -> IndexJobCreateResponse:
        summary = await self._create_job(IndexJobMode.reindex, request)
        return IndexJobCreateResponse(job_id=summary.job_id, status=summary.status)

    async def get_statuses(self) -> IndexStatusResponse:
        return IndexStatusResponse(indexes=await self._graph_repo.get_index_statuses())

    async def ensure_fulltext_indexes(self) -> IndexStatusResponse:
        return IndexStatusResponse(indexes=await self._graph_repo.ensure_fulltext_indexes())

    async def rebuild_fulltext_indexes(self, scope: IndexScope) -> IndexStatusResponse:
        return IndexStatusResponse(indexes=await self._graph_repo.rebuild_fulltext_indexes(scope))

    async def query_preview(self, request: SearchPreviewRequest) -> SearchPreviewResponse:
        payload = await self._graph_repo.query_preview(
            request.query,
            entity_limit=request.entity_limit,
            source_limit=request.source_limit,
            relation_limit=request.relation_limit,
        )
        return SearchPreviewResponse.model_validate(payload)

    async def _create_job(
        self,
        mode: IndexJobMode,
        request: IndexJobRequest,
    ) -> IndexJobSummary:
        if request.index_type == IndexType.vector:
            self._ensure_embedding_enabled()
        await self._ensure_no_conflicting_job(request.index_type, request.scope)
        batch_size = request.batch_size or self._settings.embedding_batch_size
        summary = await self._job_store.create_job(
            index_type=request.index_type,
            mode=mode,
            request=request,
            batch_size=batch_size,
        )
        await self._job_store.append_event(
            IndexJobEvent(
                job_id=summary.job_id,
                stage=IndexJobStage.queued,
                message=f"{request.index_type.value} 索引任务已创建，等待执行",
                data={
                    "index_type": request.index_type.value,
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
        task = asyncio.create_task(self._run_job(job_id), name=f"indexing:{job_id}")
        self._local_tasks[job_id] = task
        task.add_done_callback(lambda _: self._local_tasks.pop(job_id, None))

    async def _run_job(self, job_id: str) -> None:
        request = await self._job_store.get_request(job_id)
        job = await self._job_store.get_job(job_id)
        if request is None or job is None:
            return
        await self._job_store.update_job(job_id, status=IndexJobStatus.running)
        await self._job_store.append_event(
            IndexJobEvent(
                job_id=job_id,
                stage=IndexJobStage.scanning,
                message="开始扫描待同步索引对象",
                data={
                    "index_type": request.index_type.value,
                    "scope": request.scope.value,
                    "mode": job.mode.value,
                },
            )
        )

        attempted: set[str] = set()
        scanned_count = 0
        synced_count = 0
        failed_count = 0
        try:
            while True:
                if request.index_type == IndexType.vector:
                    candidates = await self._graph_repo.list_embedding_candidates(
                        request.scope,
                        limit=job.batch_size,
                        reindex=job.mode == IndexJobMode.reindex,
                        exclude_source_keys=sorted(attempted),
                    )
                    batch_scanned, batch_synced, batch_failed = await self._process_embedding_candidates(
                        candidates
                    )
                else:
                    candidates = await self._graph_repo.list_fulltext_candidates(
                        request.scope,
                        limit=job.batch_size,
                        reindex=job.mode == IndexJobMode.reindex,
                        exclude_source_keys=sorted(attempted),
                    )
                    batch_scanned, batch_synced, batch_failed = await self._process_fulltext_candidates(
                        candidates
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
                    IndexJobEvent(
                        job_id=job_id,
                        stage=IndexJobStage.indexing,
                        message="开始处理一批索引对象",
                        data={
                            "index_type": request.index_type.value,
                            "batch_size": len(candidates),
                            "scope": request.scope.value,
                        },
                    )
                )
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

            await self._job_store.finish_job(job_id, status=IndexJobStatus.completed)
            await self._job_store.append_event(
                IndexJobEvent(
                    job_id=job_id,
                    stage=IndexJobStage.completed,
                    message=f"{request.index_type.value} 索引任务执行完成",
                    data={
                        "scanned_count": scanned_count,
                        "synced_count": synced_count,
                        "failed_count": failed_count,
                    },
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("index_job_failed", job_id=job_id, error=str(exc))
            await self._job_store.finish_job(
                job_id,
                status=IndexJobStatus.failed,
                last_error=str(exc),
            )
            await self._job_store.append_event(
                IndexJobEvent(
                    job_id=job_id,
                    stage=IndexJobStage.failed,
                    message=f"{request.index_type.value} 索引任务执行失败",
                    data={"error": str(exc)},
                )
            )

    async def _process_embedding_candidates(
        self,
        candidates: list[EmbeddingCandidate],
    ) -> tuple[int, int, int]:
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

    async def _process_fulltext_candidates(
        self,
        candidates: list[TextIndexCandidate],
    ) -> tuple[int, int, int]:
        if not candidates:
            return 0, 0, 0
        try:
            await self._graph_repo.upsert_fulltext_documents(candidates)
            return len(candidates), len(candidates), 0
        except Exception:  # noqa: BLE001
            scanned = 0
            synced = 0
            failed = 0
            for candidate in candidates:
                scanned += 1
                try:
                    await self._graph_repo.upsert_fulltext_documents([candidate])
                    synced += 1
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    await self._graph_repo.mark_fulltext_failed(candidate, str(exc))
            return scanned, synced, failed

    async def _ensure_no_conflicting_job(self, index_type: IndexType, scope: IndexScope) -> None:
        active_jobs: list[IndexJobSummary] = []
        for candidate_scope in IndexScope:
            if candidate_scope == IndexScope.all or scope == IndexScope.all or candidate_scope == scope:
                active = await self._job_store.find_active_job(index_type, candidate_scope)
                if active is not None:
                    active_jobs.append(active)
        if active_jobs:
            active = active_jobs[0]
            raise HTTPException(
                status_code=409,
                detail=f"已有运行中的 {index_type.value} 索引任务：{active.job_id}",
            )

    def _ensure_embedding_enabled(self) -> None:
        if self._embedding_client.enabled:
            return
        raise HTTPException(status_code=503, detail="Embedding client is not configured")

