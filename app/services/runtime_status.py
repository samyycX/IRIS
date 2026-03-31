from __future__ import annotations

import asyncio

from app.core.config import Settings
from app.models import (
    DependencyHealthState,
    DependencyStatus,
    GraphStatistics,
    RuntimeStatusResponse,
    utcnow,
)
from app.repos.graph_repo import Neo4jGraphRepository
from app.services.llm.client import LLMClient
from app.services.llm.embedding_client import EmbeddingClient


class RuntimeStatusService:
    def __init__(
        self,
        settings: Settings,
        graph_repo: Neo4jGraphRepository,
        llm_client: LLMClient,
        embedding_client: EmbeddingClient,
    ) -> None:
        self._settings = settings
        self._graph_repo = graph_repo
        self._llm_client = llm_client
        self._embedding_client = embedding_client
        self._refresh_lock = asyncio.Lock()
        self._snapshot = self._build_initial_snapshot()

    async def start(self) -> None:
        await self.refresh_now()

    async def shutdown(self) -> None:
        return None

    async def get_status(self) -> RuntimeStatusResponse:
        return await self.refresh_now()

    async def refresh_now(self) -> RuntimeStatusResponse:
        async with self._refresh_lock:
            neo4j_status, llm_status, embedding_status = await asyncio.gather(
                self._probe_neo4j(),
                self._probe_llm(),
                self._probe_embedding(),
            )
            graph_stats = await self._resolve_graph_statistics(neo4j_status)
            checked_at = utcnow()
            self._snapshot = RuntimeStatusResponse(
                status=_overall_state([neo4j_status, llm_status, embedding_status]),
                checked_at=checked_at,
                neo4j=neo4j_status,
                llm=llm_status,
                embedding=embedding_status,
                graph=graph_stats,
            )
            return self._snapshot.model_copy(deep=True)

    def _build_initial_snapshot(self) -> RuntimeStatusResponse:
        checked_at = utcnow()
        neo4j = self._base_status(
            configured=self._graph_repo.configured,
            details={"uri": self._settings.neo4j_uri} if self._settings.neo4j_uri else {},
        )
        llm_details = {}
        if self._settings.openai_base_url:
            llm_details["base_url"] = self._settings.openai_base_url
        if self._settings.openai_model:
            llm_details["model"] = self._settings.openai_model
        llm = self._base_status(configured=self._llm_client.enabled, details=llm_details)
        embedding_details = {}
        if self._settings.openai_embedding_base_url:
            embedding_details["base_url"] = self._settings.openai_embedding_base_url
        if self._settings.openai_embedding_model:
            embedding_details["model"] = self._settings.openai_embedding_model
        embedding = self._base_status(
            configured=self._embedding_client.enabled,
            details=embedding_details,
        )
        return RuntimeStatusResponse(
            status=_overall_state([neo4j, llm, embedding]),
            checked_at=checked_at,
            neo4j=neo4j,
            llm=llm,
            embedding=embedding,
        )

    def _base_status(self, *, configured: bool, details: dict[str, str]) -> DependencyStatus:
        if configured:
            return DependencyStatus(
                state=DependencyHealthState.degraded,
                configured=True,
                available=False,
                last_error="Status check pending",
                details=details,
            )
        return DependencyStatus(
            state=DependencyHealthState.unconfigured,
            configured=False,
            available=False,
            details=details,
        )

    async def _probe_neo4j(self) -> DependencyStatus:
        checked_at = utcnow()
        details = {"uri": self._settings.neo4j_uri} if self._settings.neo4j_uri else {}
        if not self._graph_repo.configured:
            return DependencyStatus(
                state=DependencyHealthState.unconfigured,
                configured=False,
                available=False,
                last_checked_at=checked_at,
                details=details,
            )
        healthy, error = await self._graph_repo.check_health()
        return DependencyStatus(
            state=DependencyHealthState.healthy if healthy else DependencyHealthState.degraded,
            configured=True,
            available=healthy,
            last_checked_at=checked_at,
            last_error=error,
            details=details,
        )

    async def _probe_llm(self) -> DependencyStatus:
        checked_at = utcnow()
        details = {}
        if self._settings.openai_base_url:
            details["base_url"] = self._settings.openai_base_url
        if self._settings.openai_model:
            details["model"] = self._settings.openai_model
        if not self._llm_client.enabled:
            return DependencyStatus(
                state=DependencyHealthState.unconfigured,
                configured=False,
                available=False,
                last_checked_at=checked_at,
                details=details,
            )
        healthy, error = await self._llm_client.check_health()
        return DependencyStatus(
            state=DependencyHealthState.healthy if healthy else DependencyHealthState.degraded,
            configured=True,
            available=healthy,
            last_checked_at=checked_at,
            last_error=error,
            details=details,
        )

    async def _probe_embedding(self) -> DependencyStatus:
        checked_at = utcnow()
        details = {}
        if self._settings.openai_embedding_base_url:
            details["base_url"] = self._settings.openai_embedding_base_url
        if self._settings.openai_embedding_model:
            details["model"] = self._settings.openai_embedding_model
        if not self._embedding_client.enabled:
            return DependencyStatus(
                state=DependencyHealthState.unconfigured,
                configured=False,
                available=False,
                last_checked_at=checked_at,
                details=details,
            )
        healthy, error = await self._embedding_client.check_health()
        return DependencyStatus(
            state=DependencyHealthState.healthy if healthy else DependencyHealthState.degraded,
            configured=True,
            available=healthy,
            last_checked_at=checked_at,
            last_error=error,
            details=details,
        )

    async def _resolve_graph_statistics(self, neo4j_status: DependencyStatus) -> GraphStatistics:
        previous = self._snapshot.graph.model_copy(deep=True)
        if neo4j_status.available:
            counts = await self._graph_repo.get_graph_counts()
            return GraphStatistics(
                entity_count=counts["entity_count"],
                source_count=counts["source_count"],
                relation_count=counts["relation_count"],
                stale=False,
                last_updated_at=utcnow(),
            )
        if previous.last_updated_at is not None:
            previous.stale = True
            return previous
        return GraphStatistics(stale=neo4j_status.configured)


def _overall_state(statuses: list[DependencyStatus]) -> DependencyHealthState:
    if any(status.state == DependencyHealthState.degraded for status in statuses):
        return DependencyHealthState.degraded
    if any(status.state == DependencyHealthState.healthy for status in statuses):
        return DependencyHealthState.healthy
    return DependencyHealthState.unconfigured