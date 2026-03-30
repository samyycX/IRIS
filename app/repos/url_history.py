from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

from app.repos.graph_repo import Neo4jGraphRepository


class UrlHistoryRepository:
    def __init__(
        self,
        graph_repo: Neo4jGraphRepository,
        ttl_days: int = 10,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._graph_repo = graph_repo
        self._ttl = timedelta(days=ttl_days)
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    async def has_seen(self, canonical_url: str) -> bool:
        cutoff = self._cutoff()
        return await self._graph_repo.source_fetched_since(canonical_url, cutoff)

    def _cutoff(self) -> datetime:
        return self._now_provider() - self._ttl
