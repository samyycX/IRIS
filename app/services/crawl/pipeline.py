from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from time import monotonic

from app.core.logging import get_logger
from app.models import GraphUpdateResult, JobEvent, JobRequest, JobStage, JobStatus
from app.repos.event_store import InMemoryEventStore
from app.repos.graph_repo import Neo4jGraphRepository
from app.repos.url_history import UrlHistoryRepository
from app.services.crawl.canonicalizer import URLCanonicalizer
from app.services.llm.orchestrator import LlmOrchestrator
from app.services.tools.executor import ToolExecutor

logger = get_logger(__name__)


class CrawlPipeline:
    def __init__(
        self,
        event_store: InMemoryEventStore,
        graph_repo: Neo4jGraphRepository,
        url_history: UrlHistoryRepository,
        canonicalizer: URLCanonicalizer,
        tool_executor: ToolExecutor,
        llm_orchestrator: LlmOrchestrator,
        crawl_concurrency: int = 1,
        llm_timeout_seconds: int = 90,
        skip_history_seen_urls: bool = True,
    ) -> None:
        self._event_store = event_store
        self._graph_repo = graph_repo
        self._url_history = url_history
        self._canonicalizer = canonicalizer
        self._tool_executor = tool_executor
        self._llm_orchestrator = llm_orchestrator
        self._crawl_concurrency = max(1, crawl_concurrency)
        self._llm_timeout_seconds = llm_timeout_seconds
        self._skip_history_seen_urls = skip_history_seen_urls

    async def run_job(self, job_id: str, request: JobRequest) -> GraphUpdateResult:
        started_at = monotonic()
        await self._event_store.set_status(job_id, JobStatus.running)
        await self._emit(
            job_id,
            JobStage.queued,
            "任务已开始执行",
            data={
                "input_type": request.input_type.value,
                "seed": request.seed(),
            },
        )
        if request.url is not None:
            return await self._run_url_job(job_id, request, started_at=started_at)
        return await self._run_manual_job(job_id, request, started_at=started_at)

    async def _run_manual_job(
        self, job_id: str, request: JobRequest, *, started_at: float
    ) -> GraphUpdateResult:
        seed_text = request.instruction or request.entity_name or request.seed()
        llm_started_at = monotonic()
        await self._emit(
            job_id,
            JobStage.summarizing,
            "开始处理手工输入内容",
            data={"seed_length": len(seed_text)},
        )
        extraction = await _await_with_timeout(
            self._llm_orchestrator.analyze_manual_seed(
                source_id=f"manual://{job_id}",
                seed_text=seed_text,
            ),
            timeout_seconds=self._llm_timeout_seconds,
            timeout_message=f"手工输入摘要与实体抽取超时（>{self._llm_timeout_seconds} 秒）",
        )
        await self._emit(
            job_id,
            JobStage.summarizing,
            "手工输入内容已完成摘要与实体抽取",
            url=extraction.canonical_url,
            data={
                "elapsed_ms": _elapsed_ms(llm_started_at),
                "entity_count": len(extraction.extracted_entities),
                "summary_length": len(extraction.summary),
            },
        )
        graph_started_at = monotonic()
        await self._emit(
            job_id,
            JobStage.updating_graph,
            "开始写入知识图谱",
            url=extraction.canonical_url,
            data={"entity_count": len(extraction.extracted_entities)},
        )
        result = GraphUpdateResult.model_validate(
            await self._tool_executor.execute(
                "upsert_kg_entity",
                job_id=job_id,
                extraction=extraction.model_dump(),
            )
        )
        completed_job = await self._event_store.finish_job(job_id, JobStatus.completed, graph_update=result)
        if completed_job is not None:
            await self._graph_repo.sync_job(completed_job, request=request)
        await self._emit(
            job_id,
            JobStage.completed,
            "手工输入已完成知识图谱更新",
            url=extraction.canonical_url,
            data={
                **result.model_dump(),
                "graph_elapsed_ms": _elapsed_ms(graph_started_at),
                "elapsed_ms": _elapsed_ms(started_at),
            },
        )
        return result

    async def _run_url_job(self, job_id: str, request: JobRequest, *, started_at: float) -> GraphUpdateResult:
        seed_url = self._canonicalizer.canonicalize(str(request.url))
        crawl_concurrency = (
            request.crawl_concurrency
            if request.crawl_concurrency is not None
            else self._crawl_concurrency
        )
        job = await self._event_store.get_job(job_id)
        max_depth = job.max_depth if job is not None else (request.max_depth or 0)
        max_pages = job.max_pages if job is not None else (request.max_pages or 0)
        state = _UrlJobState(
            queue=deque([(seed_url, 0, None)]),
            queued_urls={seed_url},
        )
        await self._event_store.set_queue_size(job_id, len(state.queue))
        await self._emit(
            job_id,
            JobStage.discovering,
            "已初始化 URL 抓取队列",
            url=seed_url,
            data={
                "seed_url": seed_url,
                "queue_size": len(state.queue),
                "max_depth": max_depth,
                "max_pages": max_pages,
                "crawl_concurrency": crawl_concurrency,
            },
        )

        workers = [
            asyncio.create_task(
                self._run_url_worker(
                    job_id=job_id,
                    request=request,
                    seed_url=seed_url,
                    max_depth=max_depth,
                    max_pages=max_pages,
                    state=state,
                ),
                name=f"crawl-worker:{job_id}:{index}",
            )
            for index in range(crawl_concurrency)
        ]
        await asyncio.gather(*workers)

        if state.completion_reason == "max_pages_reached":
            await self._emit(
                job_id,
                JobStage.discovering,
                "达到页面数量上限，停止继续抓取",
                data={"visited_count": state.visited_count, "max_pages": max_pages},
            )

        completed_job = await self._event_store.finish_job(
            job_id,
            JobStatus.completed,
            graph_update=state.total_update,
        )
        if completed_job is not None:
            await self._graph_repo.sync_job(completed_job, request=request)
        await self._emit(
            job_id,
            JobStage.completed,
            "任务执行完成",
            data={
                **state.total_update.model_dump(),
                "completion_reason": state.completion_reason,
                "elapsed_ms": _elapsed_ms(started_at),
            },
        )
        return state.total_update

    async def _run_url_worker(
        self,
        *,
        job_id: str,
        request: JobRequest,
        seed_url: str,
        max_depth: int,
        max_pages: int,
        state: _UrlJobState,
    ) -> None:
        while True:
            next_item = await self._claim_next_url(job_id=job_id, max_pages=max_pages, state=state)
            if next_item is None:
                return
            url, depth, referer, queue_remaining = next_item
            try:
                await self._process_url(
                    job_id=job_id,
                    request=request,
                    seed_url=seed_url,
                    max_depth=max_depth,
                    state=state,
                    url=url,
                    depth=depth,
                    referer=referer,
                    queue_remaining=queue_remaining,
                )
            finally:
                await self._release_claim(state=state, url=url)

    async def _claim_next_url(
        self,
        *,
        job_id: str,
        max_pages: int,
        state: _UrlJobState,
    ) -> tuple[str, int, str | None, int] | None:
        async with state.condition:
            while True:
                if state.stop_requested:
                    if state.active_claims == 0:
                        return None
                    await state.condition.wait()
                    continue
                if state.visited_count >= max_pages:
                    state.stop_requested = True
                    state.completion_reason = "max_pages_reached"
                    if state.active_claims == 0:
                        return None
                    await state.condition.wait()
                    continue
                if state.visited_count + state.active_claims >= max_pages:
                    if state.active_claims == 0:
                        return None
                    await state.condition.wait()
                    continue
                if state.queue:
                    url, depth, referer = state.queue.popleft()
                    state.queued_urls.discard(url)
                    state.processing_urls.add(url)
                    state.active_claims += 1
                    queue_remaining = len(state.queue)
                    await self._event_store.set_queue_size(job_id, queue_remaining)
                    return url, depth, referer, queue_remaining
                if state.active_claims == 0:
                    return None
                await state.condition.wait()

    async def _release_claim(self, *, state: _UrlJobState, url: str) -> None:
        async with state.condition:
            state.processing_urls.discard(url)
            state.active_claims -= 1
            state.condition.notify_all()

    async def _remember_visited_url(
        self,
        *,
        job_id: str,
        state: _UrlJobState,
        canonical_url: str,
    ) -> bool:
        remembered = await self._event_store.remember_visited_url(job_id, canonical_url)
        if not remembered:
            return False
        async with state.condition:
            state.visited_count += 1
            state.condition.notify_all()
        return True

    async def _enqueue_discovered_urls(
        self,
        *,
        job_id: str,
        discovered_urls: list[str],
        next_depth: int,
        referer: str,
        state: _UrlJobState,
    ) -> tuple[int, int, int]:
        queued_count = 0
        skipped_count = 0
        async with state.condition:
            for canonical in discovered_urls:
                if canonical in state.queued_urls or canonical in state.processing_urls:
                    skipped_count += 1
                    continue
                if await self._event_store.has_job_visited_url(job_id, canonical):
                    skipped_count += 1
                    continue
                state.queued_urls.add(canonical)
                state.queue.append((canonical, next_depth, referer))
                queued_count += 1
            queue_size = len(state.queue)
            await self._event_store.set_queue_size(job_id, queue_size)
            if queued_count:
                state.condition.notify_all()
            return queued_count, skipped_count, queue_size

    async def _process_url(
        self,
        *,
        job_id: str,
        request: JobRequest,
        seed_url: str,
        max_depth: int,
        state: _UrlJobState,
        url: str,
        depth: int,
        referer: str | None,
        queue_remaining: int,
    ) -> None:
        await self._emit(
            job_id,
            JobStage.discovering,
            "从队列中取出一个页面准备处理",
            url=url,
            data={
                "depth": depth,
                "queue_remaining": queue_remaining,
                "referer": referer,
            },
        )

        if depth > max_depth:
            await self._emit(
                job_id,
                JobStage.discovering,
                "跳过超过最大深度的 URL",
                url=url,
                data={"depth": depth, "max_depth": max_depth},
            )
            return
        if await self._event_store.has_job_visited_url(job_id, url):
            await self._emit(
                job_id,
                JobStage.discovering,
                "跳过当前任务内已访问的 URL",
                url=url,
                data={"depth": depth},
            )
            return
        bypass_history_seen_check = _should_bypass_history_seen_check(
            url=url,
            depth=depth,
            seed_url=seed_url,
        )
        if bypass_history_seen_check:
            await self._emit(
                job_id,
                JobStage.discovering,
                "当前种子 URL 为用户主动输入，绕过历史访问判重",
                url=url,
                data={"depth": depth, "reason": "seed_url_bypass_history"},
            )
        elif self._skip_history_seen_urls:
            if await self._url_history.has_seen(url):
                await self._remember_visited_url(job_id=job_id, state=state, canonical_url=url)
                await self._emit(
                    job_id,
                    JobStage.discovering,
                    "跳过历史已处理的 URL",
                    url=url,
                    data={"depth": depth, "reason": "history_seen"},
                )
                return

        page_started_at = monotonic()
        await self._emit(job_id, JobStage.fetching, "开始抓取页面", url=url, data={"depth": depth})
        try:
            page_payload = await self._tool_executor.execute(
                "fetch_url",
                url=url,
                referer=referer,
            )
            remembered = await self._remember_visited_url(
                job_id=job_id,
                state=state,
                canonical_url=page_payload["canonical_url"],
            )
            if not remembered:
                await self._emit(
                    job_id,
                    JobStage.discovering,
                    "跳过当前任务内已访问的规范化 URL",
                    url=page_payload["canonical_url"],
                    data={"depth": depth, "reason": "canonical_url_seen"},
                )
                return
            await self._emit(
                job_id,
                JobStage.extracting,
                "页面抓取成功，开始正文抽取",
                url=page_payload["canonical_url"],
                data={
                    "depth": depth,
                    "status_code": page_payload["status_code"],
                    "fetch_mode": page_payload.get("fetch_mode", "http"),
                    "title": page_payload.get("title"),
                    "text_length": len(page_payload.get("text", "")),
                    "link_count": len(page_payload.get("links", [])),
                    "fetch_elapsed_ms": _elapsed_ms(page_started_at),
                },
            )
            llm_started_at = monotonic()
            await self._emit(
                job_id,
                JobStage.summarizing,
                "开始查询图谱上下文并调用 LLM",
                url=page_payload["canonical_url"],
                data={
                    "depth": depth,
                    "text_length": len(page_payload["text"]),
                    "link_count": len(page_payload.get("links", [])),
                },
            )
            candidate_urls, history_skipped_count = await self._filter_unseen_candidate_urls(
                job_id=job_id,
                candidate_urls=page_payload.get("links", []),
                base_url=page_payload["canonical_url"],
            )
            extraction = await _await_with_timeout(
                self._llm_orchestrator.analyze_page(
                    canonical_url=page_payload["canonical_url"],
                    title=page_payload.get("title"),
                    text=page_payload["text"],
                    content_hash=page_payload["content_hash"],
                    discovered_urls=candidate_urls,
                    filter_candidate_urls=request.filter_candidate_urls,
                ),
                timeout_seconds=self._llm_timeout_seconds,
                timeout_message=(
                    f"查询图谱上下文并调用 LLM 超时（>{self._llm_timeout_seconds} 秒）"
                ),
            )
            summarizing_message = (
                "LLM 已完成页面摘要、实体抽取与关联链接排序"
                if request.filter_candidate_urls
                else "LLM 已完成页面摘要与实体抽取，待选 URL 未筛选"
            )
            await self._emit(
                job_id,
                JobStage.summarizing,
                summarizing_message,
                url=extraction.canonical_url,
                data={
                    "entity_count": len(extraction.extracted_entities),
                    "summary_length": len(extraction.summary),
                    "candidate_link_count": len(candidate_urls),
                    "selected_link_count": len(extraction.discovered_urls),
                    "history_skipped_link_count": history_skipped_count,
                    "filter_candidate_urls": request.filter_candidate_urls,
                    "llm_elapsed_ms": _elapsed_ms(llm_started_at),
                },
            )
            graph_started_at = monotonic()
            await self._emit(
                job_id,
                JobStage.updating_graph,
                "开始写入知识图谱",
                url=extraction.canonical_url,
                data={"entity_count": len(extraction.extracted_entities)},
            )
            update = GraphUpdateResult.model_validate(
                await self._tool_executor.execute(
                    "upsert_kg_entity",
                    job_id=job_id,
                    extraction=extraction.model_dump(),
                )
            )
            async with state.condition:
                state.total_update = merge_graph_updates(state.total_update, update)
            await self._emit(
                job_id,
                JobStage.updating_graph,
                "知识图谱更新完成",
                url=extraction.canonical_url,
                data={
                    **update.model_dump(),
                    "graph_elapsed_ms": _elapsed_ms(graph_started_at),
                    "page_elapsed_ms": _elapsed_ms(page_started_at),
                },
            )

            if depth < max_depth:
                discovered_count = len(page_payload.get("links", []))
                queued_count, skipped_count, queue_size = await self._enqueue_discovered_urls(
                    job_id=job_id,
                    discovered_urls=extraction.discovered_urls,
                    next_depth=depth + 1,
                    referer=page_payload["canonical_url"],
                    state=state,
                )
                await self._emit(
                    job_id,
                    JobStage.discovering,
                    (
                        "已根据 LLM 排序后的关联链接更新抓取队列"
                        if request.filter_candidate_urls
                        else "已根据未筛选的候选链接更新抓取队列"
                    ),
                    url=page_payload["canonical_url"],
                    data={
                        "discovered_links": discovered_count,
                        "history_skipped_links": history_skipped_count,
                        "selected_links": len(extraction.discovered_urls),
                        "queued_links": queued_count,
                        "skipped_links": skipped_count,
                        "queue_size": queue_size,
                        "filter_candidate_urls": request.filter_candidate_urls,
                    },
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception("crawl_page_failed", job_id=job_id, url=url, error=str(exc))
            await self._event_store.increment_failed(job_id)
            await self._event_store.set_status(job_id, JobStatus.running, last_error=str(exc))
            await self._emit(
                job_id,
                JobStage.failed,
                "页面处理失败",
                url=url,
                data={"error": str(exc), "page_elapsed_ms": _elapsed_ms(page_started_at)},
            )

    async def _emit(
        self,
        job_id: str,
        stage: JobStage,
        message: str,
        *,
        url: str | None = None,
        data: dict | None = None,
    ) -> None:
        payload = dict(data or {})
        job = await self._event_store.get_job(job_id)
        if job is not None:
            payload.setdefault("job_status", job.status.value)
            payload.setdefault("visited_count", job.visited_count)
            payload.setdefault("queued_count", job.queued_count)
            payload.setdefault("failed_count", job.failed_count)
            payload.setdefault("last_error", job.last_error)
            payload.setdefault("max_depth", job.max_depth)
            payload.setdefault("max_pages", job.max_pages)
        event = JobEvent(
            job_id=job_id,
            stage=stage,
            message=message,
            url=url,
            data=payload,
        )
        await self._event_store.append_event(event)

    async def _filter_unseen_candidate_urls(
        self,
        *,
        job_id: str,
        candidate_urls: list[str],
        base_url: str,
    ) -> tuple[list[str], int]:
        unseen_candidates: list[str] = []
        skipped_history_count = 0
        seen_candidates: set[str] = set()

        for candidate in candidate_urls:
            canonical = self._canonicalizer.canonicalize(candidate, base_url=base_url)
            if not canonical.startswith(("http://", "https://")):
                continue
            lowered = canonical.casefold()
            if lowered in seen_candidates:
                continue
            seen_candidates.add(lowered)

            if await self._event_store.has_job_visited_url(job_id, canonical):
                skipped_history_count += 1
                continue

            if self._skip_history_seen_urls:
                if await self._url_history.has_seen(canonical):
                    skipped_history_count += 1
                    continue

            unseen_candidates.append(canonical)

        return unseen_candidates, skipped_history_count


def merge_graph_updates(left: GraphUpdateResult, right: GraphUpdateResult) -> GraphUpdateResult:
    return GraphUpdateResult(
        created_entities=sorted(set(left.created_entities + right.created_entities)),
        updated_entities=sorted(set(left.updated_entities + right.updated_entities)),
        created_pages=sorted(set(left.created_pages + right.created_pages)),
        created_relationships=left.created_relationships + right.created_relationships,
        deleted_relationships=left.deleted_relationships + right.deleted_relationships,
    )


def _elapsed_ms(started_at: float) -> int:
    return int((monotonic() - started_at) * 1000)


def _should_bypass_history_seen_check(*, url: str, depth: int, seed_url: str) -> bool:
    return depth == 0 and url == seed_url


async def _await_with_timeout(coro, *, timeout_seconds: int, timeout_message: str):
    if timeout_seconds <= 0:
        return await coro
    started_at = monotonic()
    try:
        return await asyncio.wait_for(coro, timeout=timeout_seconds)
    except TimeoutError as exc:
        logger.warning(
            "pipeline_stage_timeout",
            timeout_seconds=timeout_seconds,
            elapsed_ms=_elapsed_ms(started_at),
            error=timeout_message,
        )
        raise RuntimeError(timeout_message) from exc


@dataclass
class _UrlJobState:
    queue: deque[tuple[str, int, str | None]]
    queued_urls: set[str]
    processing_urls: set[str] = field(default_factory=set)
    total_update: GraphUpdateResult = field(default_factory=GraphUpdateResult)
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    active_claims: int = 0
    visited_count: int = 0
    stop_requested: bool = False
    completion_reason: str = "queue_exhausted"
