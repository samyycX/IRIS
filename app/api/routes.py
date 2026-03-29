from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from sse_starlette import EventSourceResponse

from app.models import JobRequest

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
