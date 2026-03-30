import json
from pathlib import Path

from app.core.config import Settings
from app.models import JobInputType, JobStatus
from app.repos.graph_migrations import Neo4jMigrationManager
from app.repos.neo4j_job_store import Neo4jJobStore


def test_job_store_can_read_legacy_crawl_job_without_input_type_and_status():
    store = Neo4jJobStore(Settings(NEO4J_PASSWORD=""))

    job = store._job_from_properties(  # noqa: SLF001
        {
            "job_id": "legacy-job",
            "seed": "https://example.com/page",
            "created_at": "2026-03-29T12:00:00+00:00",
            "updated_at": "2026-03-29T12:05:00+00:00",
            "graph_update_json": json.dumps({"created_sources": ["https://example.com/page"]}),
            "request_json": json.dumps({"url": "https://example.com/page"}),
        }
    )

    assert job.input_type == JobInputType.url
    assert job.status == JobStatus.completed


def test_migration_manager_discovers_versioned_cypher_files(tmp_path):
    (tmp_path / "V2__second.cypher").write_text("RETURN 2;", encoding="utf-8")
    (tmp_path / "V1__first.cypher").write_text("RETURN 1;", encoding="utf-8")
    (tmp_path / "README.txt").write_text("ignore", encoding="utf-8")

    manager = Neo4jMigrationManager(Settings(NEO4J_PASSWORD=""), migrations_dir=tmp_path)
    migrations = manager.discover_migrations()

    assert [migration.version for migration in migrations] == [1, 2]
    assert [migration.name for migration in migrations] == ["first", "second"]


def test_migration_manager_splits_multiple_statements():
    content = """
    // comment
    MATCH (n)
    RETURN count(n);

    CREATE (:Marker {name: 'done'});
    """

    statements = Neo4jMigrationManager.split_statements(content)

    assert statements == [
        "MATCH (n)\n    RETURN count(n)",
        "CREATE (:Marker {name: 'done'})",
    ]


def test_bundled_graph_schema_migration_file_exists():
    path = Path("E:/programming/IRIS/app/repos/migrations/V1__initialize_graph_schema.cypher")
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "CREATE CONSTRAINT source_canonical_url" in content
    assert "CREATE CONSTRAINT embedding_embedding_key" in content
    assert "CREATE VECTOR INDEX entity_embedding_index" in content
    assert "CREATE VECTOR INDEX source_embedding_index" in content
    assert "CREATE VECTOR INDEX relation_embedding_index" in content


def test_bundled_mentioned_in_relevance_migration_file_exists():
    path = Path("E:/programming/IRIS/app/repos/migrations/V2__backfill_mentioned_in_relevance.cypher")
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "MATCH ()-[rel:MENTIONED_IN]->()" in content
    assert "SET rel.relevance = 0.5" in content
