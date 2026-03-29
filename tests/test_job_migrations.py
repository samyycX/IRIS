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
            "graph_update_json": json.dumps({"created_pages": ["https://example.com/page"]}),
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


def test_bundled_crawl_job_migration_file_exists():
    path = Path("E:/programming/IRIS/app/repos/migrations/V1__backfill_crawl_job_schema.cypher")
    assert path.exists()
    assert "MATCH (job:CrawlJob)" in path.read_text(encoding="utf-8")


def test_bundled_embedding_migration_file_exists():
    path = Path("E:/programming/IRIS/app/repos/migrations/V2__add_embedding_nodes_and_vector_index.cypher")
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "CREATE VECTOR INDEX embedding_index" in content
    assert "CREATE CONSTRAINT embedding_embedding_key" in content


def test_bundled_relation_embedding_migration_file_exists():
    path = Path(
        "E:/programming/IRIS/app/repos/migrations/V3__remove_sync_status_and_add_relation_embedding.cypher"
    )
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "REMOVE page.embedding_sync_status" in content
    assert "SET embedding:RelationEmbedding" in content
