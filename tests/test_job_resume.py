import asyncio

from app.core.config import Settings
from app.models import JobCheckpoint, JobInputType, JobQueueItem, JobRequest, JobStatus
from app.repos.job_store import InMemoryJobStore
from app.services.jobs import JobService


class DummyPipeline:
    def __init__(self) -> None:
        self.calls: list[tuple[str, JobRequest, JobCheckpoint | None]] = []

    async def run_job(
        self,
        job_id: str,
        request: JobRequest,
        *,
        checkpoint: JobCheckpoint | None = None,
    ) -> None:
        self.calls.append((job_id, request, checkpoint))


class BlockingPipeline:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def run_job(
        self,
        job_id: str,
        request: JobRequest,
        *,
        checkpoint: JobCheckpoint | None = None,
    ) -> None:
        self.started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


async def test_resume_job_passes_persisted_checkpoint_to_pipeline():
    settings = Settings(NEO4J_PASSWORD="")
    store = InMemoryJobStore()
    pipeline = DummyPipeline()
    service = JobService(settings, store, pipeline)

    request = JobRequest(input_type=JobInputType.url, url="https://example.com/start")
    job = await store.create_job(request, max_depth=2, max_pages=10)
    checkpoint = JobCheckpoint(
        pending_queue=[
            JobQueueItem(url="https://example.com/next", depth=1, referer="https://example.com/start")
        ],
        in_progress=[
            JobQueueItem(url="https://example.com/processing", depth=1, referer="https://example.com/start")
        ],
        visited_urls=["https://example.com/start"],
        completion_reason="interrupted",
    )

    await store.save_checkpoint(job.job_id, checkpoint)
    await store.set_status(job.job_id, JobStatus.interrupted)

    resumed = await service.resume_job(job.job_id)
    await asyncio.sleep(0)
    await service.shutdown()

    assert resumed is not None
    assert pipeline.calls
    _, resumed_request, resumed_checkpoint = pipeline.calls[0]
    assert resumed_request.url == request.url
    assert resumed_checkpoint is not None
    assert [item.url for item in resumed_checkpoint.pending_queue] == [
        "https://example.com/next"
    ]
    assert [item.url for item in resumed_checkpoint.in_progress] == [
        "https://example.com/processing"
    ]


async def test_mark_incomplete_jobs_interrupted_keeps_resume_metadata():
    store = InMemoryJobStore()
    request = JobRequest(input_type=JobInputType.url, url="https://example.com/start")
    job = await store.create_job(request, max_depth=2, max_pages=10)
    checkpoint = JobCheckpoint(
        pending_queue=[JobQueueItem(url="https://example.com/next", depth=1)],
        visited_urls=["https://example.com/start"],
        completion_reason="running",
    )

    await store.save_checkpoint(job.job_id, checkpoint)
    await store.set_status(job.job_id, JobStatus.running)

    affected = await store.mark_incomplete_jobs_interrupted()
    updated = await store.get_job(job.job_id)

    assert affected == 1
    assert updated is not None
    assert updated.status == JobStatus.interrupted
    assert updated.resume_available is True
    assert updated.visited_count == 1


async def test_resume_job_ignores_completed_jobs():
    settings = Settings(NEO4J_PASSWORD="")
    store = InMemoryJobStore()
    pipeline = DummyPipeline()
    service = JobService(settings, store, pipeline)

    request = JobRequest(input_type=JobInputType.instruction, instruction="summarize this")
    job = await store.create_job(request, max_depth=0, max_pages=0)
    await store.finish_job(job.job_id, JobStatus.completed)

    resumed = await service.resume_job(job.job_id)
    await service.shutdown()

    assert resumed is not None
    assert resumed.status == JobStatus.completed
    assert pipeline.calls == []


async def test_pause_job_marks_running_task_paused_and_preserves_resume_flag():
    settings = Settings(NEO4J_PASSWORD="")
    store = InMemoryJobStore()
    pipeline = BlockingPipeline()
    service = JobService(settings, store, pipeline)

    request = JobRequest(input_type=JobInputType.url, url="https://example.com/start")
    created = await service.create_job(request)
    checkpoint = JobCheckpoint(
        pending_queue=[JobQueueItem(url="https://example.com/next", depth=1)],
        visited_urls=["https://example.com/start"],
        completion_reason="running",
    )
    await store.save_checkpoint(created.job_id, checkpoint)

    await asyncio.wait_for(pipeline.started.wait(), timeout=0.2)
    paused = await service.pause_job(created.job_id)
    await service.shutdown()

    assert paused is not None
    assert paused.status == JobStatus.paused
    assert paused.resume_available is True
    assert pipeline.cancelled.is_set()


async def test_cancel_job_marks_running_task_cancelled_and_clears_resume():
    settings = Settings(NEO4J_PASSWORD="")
    store = InMemoryJobStore()
    pipeline = BlockingPipeline()
    service = JobService(settings, store, pipeline)

    request = JobRequest(input_type=JobInputType.url, url="https://example.com/start")
    created = await service.create_job(request)
    checkpoint = JobCheckpoint(
        pending_queue=[JobQueueItem(url="https://example.com/next", depth=1)],
        visited_urls=["https://example.com/start"],
        completion_reason="running",
    )
    await store.save_checkpoint(created.job_id, checkpoint)

    await asyncio.wait_for(pipeline.started.wait(), timeout=0.2)
    cancelled = await service.cancel_job(created.job_id)
    resumed = await service.resume_job(created.job_id)
    await service.shutdown()

    assert cancelled is not None
    assert cancelled.status == JobStatus.cancelled
    assert cancelled.resume_available is False
    assert resumed is not None
    assert resumed.status == JobStatus.cancelled
    assert pipeline.cancelled.is_set()
