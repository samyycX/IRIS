from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from sse_starlette import EventSourceResponse

from app.models import (
    IndexJobRequest,
    IndexPreparationRequest,
    IndexScope,
    IndexStatusResponse,
    JobRequest,
    JobStatus,
    SearchPreviewRequest,
    SearchPreviewResponse,
)

router = APIRouter(prefix="/api", tags=["api"])


def _container(request: Request):
    return request.app.state.container


@router.post("/jobs")
async def create_job(request: Request, payload: JobRequest):
    container = _container(request)
    return await container.jobs.create_job(payload)


@router.get("/jobs")
async def list_jobs(request: Request):
    container = _container(request)
    return await container.jobs.list_jobs()


@router.get("/jobs/{job_id}")
async def get_job(request: Request, job_id: str):
    container = _container(request)
    job = await container.jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/jobs/{job_id}/resume")
async def resume_job(request: Request, job_id: str):
    container = _container(request)
    job = await container.jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    resumed = await container.jobs.resume_job(job_id)
    if resumed is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if resumed.status not in {JobStatus.queued, JobStatus.running}:
        raise HTTPException(status_code=409, detail="Job is not resumable")
    return resumed


@router.post("/jobs/{job_id}/pause")
async def pause_job(request: Request, job_id: str):
    container = _container(request)
    job = await container.jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    paused = await container.jobs.pause_job(job_id)
    if paused is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if paused.status != JobStatus.paused:
        raise HTTPException(status_code=409, detail="Job is not pausable")
    return paused


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(request: Request, job_id: str):
    container = _container(request)
    job = await container.jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    cancelled = await container.jobs.cancel_job(job_id)
    if cancelled is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if cancelled.status != JobStatus.cancelled:
        raise HTTPException(status_code=409, detail="Job is not cancellable")
    return cancelled


@router.get("/jobs/{job_id}/events")
async def get_job_events(request: Request, job_id: str):
    container = _container(request)
    job = await container.jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return await container.jobs.get_events(job_id)


@router.get("/jobs/{job_id}/stream")
async def stream_job_events(request: Request, job_id: str):
    container = _container(request)
    job = await container.jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return EventSourceResponse(container.jobs.stream_events(job_id))


@router.post("/indexing/backfill")
async def create_index_backfill_job(request: Request, payload: IndexJobRequest):
    container = _container(request)
    return await container.indexing.create_backfill_job(payload)


@router.post("/indexing/reindex")
async def create_index_reindex_job(request: Request, payload: IndexJobRequest):
    container = _container(request)
    return await container.indexing.create_reindex_job(payload)


@router.post("/indexing/prepare")
async def prepare_index_job(request: Request, payload: IndexPreparationRequest):
    container = _container(request)
    return await container.indexing.prepare(payload)


@router.get("/indexing/jobs")
async def list_index_jobs(request: Request):
    container = _container(request)
    return await container.indexing.list_jobs()


@router.get("/indexing/jobs/{job_id}")
async def get_index_job(request: Request, job_id: str):
    container = _container(request)
    job = await container.indexing.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Index job not found")
    return job


@router.get("/indexing/jobs/{job_id}/events")
async def get_index_job_events(request: Request, job_id: str):
    container = _container(request)
    job = await container.indexing.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Index job not found")
    return await container.indexing.get_events(job_id)


@router.get("/indexing/status")
async def get_index_statuses(request: Request) -> IndexStatusResponse:
    container = _container(request)
    return await container.indexing.get_statuses()


@router.post("/indexing/fulltext/build")
async def ensure_fulltext_indexes(request: Request) -> IndexStatusResponse:
    container = _container(request)
    return await container.indexing.ensure_fulltext_indexes()


@router.post("/indexing/fulltext/rebuild/{scope}")
async def rebuild_fulltext_indexes(request: Request, scope: IndexScope) -> IndexStatusResponse:
    container = _container(request)
    return await container.indexing.rebuild_fulltext_indexes(scope)


@router.post("/indexing/query-preview")
async def query_index_preview(
    request: Request,
    payload: SearchPreviewRequest,
) -> SearchPreviewResponse:
    container = _container(request)
    return await container.indexing.query_preview(payload)
