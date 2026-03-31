from app.core.config import Settings
from app.models import DependencyHealthState
from app.services.runtime_status import RuntimeStatusService


class _FakeGraphRepo:
    def __init__(self, health_results, counts=None):
        self.configured = True
        self._health_results = list(health_results)
        self._counts = counts or {
            "entity_count": 0,
            "source_count": 0,
            "relation_count": 0,
        }

    async def check_health(self):
        if len(self._health_results) > 1:
            return self._health_results.pop(0)
        return self._health_results[0]

    async def get_graph_counts(self):
        return dict(self._counts)


class _FakeProbeClient:
    def __init__(self, *, enabled: bool, health_results=None):
        self.enabled = enabled
        self._health_results = list(health_results or [(True, None)])

    async def check_health(self):
        if len(self._health_results) > 1:
            return self._health_results.pop(0)
        return self._health_results[0]


async def test_runtime_status_service_keeps_last_graph_counts_when_neo4j_degrades():
    graph_repo = _FakeGraphRepo(
        health_results=[(True, None), (False, "connection refused")],
        counts={
            "entity_count": 12,
            "source_count": 7,
            "relation_count": 24,
        },
    )
    llm_client = _FakeProbeClient(enabled=False)
    embedding_client = _FakeProbeClient(enabled=False)
    service = RuntimeStatusService(
        Settings(
            NEO4J_URI="neo4j://127.0.0.1:7687",
            NEO4J_USERNAME="neo4j",
            NEO4J_PASSWORD="pw",
        ),
        graph_repo,
        llm_client,
        embedding_client,
    )

    healthy = await service.refresh_now()
    degraded = await service.refresh_now()

    assert healthy.neo4j.state == DependencyHealthState.healthy
    assert healthy.graph.entity_count == 12
    assert healthy.graph.stale is False

    assert degraded.neo4j.state == DependencyHealthState.degraded
    assert degraded.graph.entity_count == 12
    assert degraded.graph.source_count == 7
    assert degraded.graph.relation_count == 24
    assert degraded.graph.stale is True


async def test_runtime_status_service_get_status_refreshes_on_request():
    graph_repo = _FakeGraphRepo(
        health_results=[(True, None), (False, "connection refused")],
        counts={
            "entity_count": 3,
            "source_count": 2,
            "relation_count": 5,
        },
    )
    llm_client = _FakeProbeClient(enabled=False)
    embedding_client = _FakeProbeClient(enabled=False)
    service = RuntimeStatusService(
        Settings(
            NEO4J_URI="neo4j://127.0.0.1:7687",
            NEO4J_USERNAME="neo4j",
            NEO4J_PASSWORD="pw",
        ),
        graph_repo,
        llm_client,
        embedding_client,
    )

    await service.start()
    status = await service.get_status()

    assert status.neo4j.state == DependencyHealthState.degraded
    assert status.graph.entity_count == 3
    assert status.graph.stale is True