from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from neo4j import AsyncGraphDatabase
from neo4j.exceptions import Neo4jError

from app.core.config import Settings
from app.core.logging import get_logger
from app.models import utcnow

logger = get_logger(__name__)

MIGRATION_SCOPE = "graph"
MIGRATION_FILENAME_RE = re.compile(r"^V(?P<version>\d+)__(?P<name>[A-Za-z0-9_.-]+)\.cypher$")


@dataclass(frozen=True)
class GraphMigration:
    version: int
    name: str
    path: Path
    checksum: str


class Neo4jMigrationManager:
    def __init__(self, settings: Settings, migrations_dir: Path | None = None) -> None:
        self._settings = settings
        self._driver = None
        self.enabled = bool(
            settings.neo4j_uri and settings.neo4j_username and settings.neo4j_password
        )
        self._migrations_dir = migrations_dir or Path(__file__).with_name("migrations")

    async def connect(self) -> None:
        if not self.enabled or self._driver is not None:
            return
        self._driver = AsyncGraphDatabase.driver(
            self._settings.neo4j_uri,
            auth=(self._settings.neo4j_username, self._settings.neo4j_password),
        )

    async def close(self) -> None:
        if self._driver is not None:
            await self._driver.close()
            self._driver = None

    async def ensure_constraints(self) -> None:
        if not self.enabled:
            return
        await self.connect()
        statements = [
            (
                "CREATE CONSTRAINT migration_state_scope IF NOT EXISTS "
                "FOR (m:MigrationState) REQUIRE m.scope IS UNIQUE"
            ),
            (
                "CREATE CONSTRAINT migration_record_key IF NOT EXISTS "
                "FOR (m:MigrationRecord) REQUIRE m.key IS UNIQUE"
            ),
        ]
        async with self._driver.session() as session:
            for statement in statements:
                await session.run(statement)

    async def run_migrations(self) -> list[int]:
        if not self.enabled:
            return []
        await self.connect()
        await self.ensure_constraints()

        applied_versions: list[int] = []
        current_version = await self._get_current_version()
        for migration in self.discover_migrations():
            if migration.version <= current_version:
                continue
            await self._apply_migration(migration)
            applied_versions.append(migration.version)
            current_version = migration.version
        return applied_versions

    def discover_migrations(self) -> list[GraphMigration]:
        if not self._migrations_dir.exists():
            return []
        migrations: list[GraphMigration] = []
        for path in sorted(self._migrations_dir.glob("*.cypher")):
            migration = self.parse_migration_path(path)
            if migration is not None:
                migrations.append(migration)
        return sorted(migrations, key=lambda item: item.version)

    @staticmethod
    def parse_migration_path(path: Path) -> GraphMigration | None:
        match = MIGRATION_FILENAME_RE.match(path.name)
        if match is None:
            return None
        content = path.read_text(encoding="utf-8")
        checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return GraphMigration(
            version=int(match.group("version")),
            name=match.group("name"),
            path=path,
            checksum=checksum,
        )

    @staticmethod
    def split_statements(content: str) -> list[str]:
        statements: list[str] = []
        current: list[str] = []
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("//"):
                continue
            current.append(line)
            if stripped.endswith(";"):
                statement = "\n".join(current).strip()
                if statement.endswith(";"):
                    statement = statement[:-1].strip()
                if statement:
                    statements.append(statement)
                current = []
        if current:
            statement = "\n".join(current).strip()
            if statement:
                statements.append(statement)
        return statements

    async def _get_current_version(self) -> int:
        async with self._driver.session() as session:
            result = await session.run(
                """
                MATCH (state:MigrationState {scope: $scope})
                RETURN state.current_version AS current_version
                """,
                scope=MIGRATION_SCOPE,
            )
            record = await result.single()
            return int(record["current_version"]) if record and record["current_version"] else 0

    async def _apply_migration(self, migration: GraphMigration) -> None:
        logger.info(
            "neo4j_migration_start",
            scope=MIGRATION_SCOPE,
            version=migration.version,
            name=migration.name,
            path=str(migration.path),
        )
        content = migration.path.read_text(encoding="utf-8")
        statements = self.split_statements(content)
        if not statements:
            logger.warning(
                "neo4j_migration_empty",
                scope=MIGRATION_SCOPE,
                version=migration.version,
                name=migration.name,
                path=str(migration.path),
            )
            return

        applied_at = utcnow().isoformat()
        try:
            async with self._driver.session() as session:
                for statement in statements:
                    await session.run(statement)
                await session.run(
                    """
                    MERGE (state:MigrationState {scope: $scope})
                    SET state.current_version = $version,
                        state.updated_at = datetime($applied_at)
                    MERGE (record:MigrationRecord {key: $key})
                    SET record.scope = $scope,
                        record.version = $version,
                        record.name = $name,
                        record.filename = $filename,
                        record.checksum = $checksum,
                        record.applied_at = datetime($applied_at)
                    """,
                    scope=MIGRATION_SCOPE,
                    version=migration.version,
                    key=f"{MIGRATION_SCOPE}:{migration.version}",
                    name=migration.name,
                    filename=migration.path.name,
                    checksum=migration.checksum,
                    applied_at=applied_at,
                )
        except Neo4jError as exc:
            logger.exception(
                "neo4j_migration_failed",
                scope=MIGRATION_SCOPE,
                version=migration.version,
                name=migration.name,
                path=str(migration.path),
                error=str(exc),
            )
            raise

        logger.info(
            "neo4j_migration_complete",
            scope=MIGRATION_SCOPE,
            version=migration.version,
            name=migration.name,
            path=str(migration.path),
        )
