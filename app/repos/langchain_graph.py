from __future__ import annotations

import asyncio
import inspect
from typing import Any

from app.core.config import Settings


class Neo4jGraphReadAdapter:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._graph = None
        self.enabled = bool(
            settings.neo4j_uri and settings.neo4j_username and settings.neo4j_password
        )

    async def query(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        graph = self._get_graph()
        return await asyncio.to_thread(graph.query, cypher, params or {})

    async def close(self) -> None:
        if self._graph is None:
            return
        driver = getattr(self._graph, "_driver", None)
        close = getattr(driver, "close", None)
        if close is None:
            return
        result = close()
        if inspect.isawaitable(result):
            await result

    def _get_graph(self):
        if self._graph is None:
            from langchain_neo4j import Neo4jGraph

            self._graph = Neo4jGraph(
                url=self._settings.neo4j_uri,
                username=self._settings.neo4j_username,
                password=self._settings.neo4j_password,
                refresh_schema=False,
                sanitize=False,
            )
        return self._graph
