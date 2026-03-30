from __future__ import annotations

import json
import re
from datetime import datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlsplit

from neo4j import AsyncGraphDatabase
from neo4j.exceptions import Neo4jError

from app.core.config import Settings
from app.core.logging import get_logger
from app.models import (
    EmbeddingCandidate,
    EmbeddingSourceType,
    ExtractedEntity,
    GraphUpdateResult,
    IndexCandidateSample,
    IndexQueryResult,
    IndexScope,
    IndexStatusEntry,
    IndexType,
    JobRequest,
    JobSummary,
    PageExtraction,
    TextIndexCandidate,
    utcnow,
)
from app.repos.langchain_graph import Neo4jGraphReadAdapter
from app.services.llm.embedding_utils import (
    build_embedding_key,
    build_entity_embedding_text,
    build_source_embedding_text,
    build_relation_embedding_text,
    build_relation_pair_key,
    compute_embedding_content_hash,
    parse_relation_pair_key,
)

if TYPE_CHECKING:
    from app.services.llm.embedding_client import EmbeddingClient

logger = get_logger(__name__)

ENTITY_EMBEDDING_INDEX_NAME = "entity_embedding_index"
SOURCE_EMBEDDING_INDEX_NAME = "source_embedding_index"
RELATION_EMBEDDING_INDEX_NAME = "relation_embedding_index"
ENTITY_FULLTEXT_INDEX_NAME = "entity_fulltext_index"
SOURCE_FULLTEXT_INDEX_NAME = "source_fulltext_index"
RELATION_FULLTEXT_INDEX_NAME = "relation_fulltext_index"
DEFAULT_MENTIONED_IN_RELEVANCE = 0.5


class Neo4jGraphRepository:
    def __init__(self, settings: Settings, embedding_client: EmbeddingClient | None = None) -> None:
        self._settings = settings
        self._embedding_client = embedding_client
        self._driver = None
        self._read_adapter = Neo4jGraphReadAdapter(settings)
        self.enabled = bool(
            settings.neo4j_uri and settings.neo4j_username and settings.neo4j_password
        )

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
        await self._read_adapter.close()

    async def ensure_constraints(self) -> None:
        if not self.enabled:
            return
        await self.connect()
        statements = [
            (
                "CREATE CONSTRAINT source_canonical_url IF NOT EXISTS "
                "FOR (s:Source) REQUIRE s.canonical_url IS UNIQUE"
            ),
            (
                "CREATE CONSTRAINT crawl_job_id IF NOT EXISTS "
                "FOR (j:CrawlJob) REQUIRE j.job_id IS UNIQUE"
            ),
            (
                "CREATE CONSTRAINT entity_entity_id IF NOT EXISTS "
                "FOR (e:Entity) REQUIRE e.entity_id IS UNIQUE"
            ),
            (
                "CREATE CONSTRAINT embedding_embedding_key IF NOT EXISTS "
                "FOR (e:Embedding) REQUIRE e.embedding_key IS UNIQUE"
            ),
        ]
        async with self._driver.session() as session:
            for statement in statements:
                await session.run(statement)

    async def source_exists(self, canonical_url: str) -> bool:
        if not self.enabled:
            return False
        records = await self._query_read_records(
            "source_exists",
            "MATCH (s:Source {canonical_url: $canonical_url}) RETURN count(s) > 0 AS exists",
            canonical_url=canonical_url,
        )
        return bool(records and records[0].get("exists"))

    async def source_fetched_since(self, canonical_url: str, cutoff: datetime) -> bool:
        if not self.enabled:
            return False
        records = await self._query_read_records(
            "source_fetched_since",
            """
            MATCH (s:Source {canonical_url: $canonical_url})
            RETURN s.fetched_at IS NOT NULL
               AND s.fetched_at >= datetime($cutoff) AS is_recent
            """,
            canonical_url=canonical_url,
            cutoff=cutoff.isoformat(),
        )
        return bool(records and records[0].get("is_recent"))

    async def query_entity_context(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        if not self.enabled or not query.strip():
            return []
        fulltext_matches = await self.query_fulltext_entities(query, limit=limit)
        keyword_matches = [
            _enrich_entity_context_record(record)
            for record in await self._query_read_records(
                "query_entity_context",
                _ENTITY_CONTEXT_CYPHER,
                search_text=query,
                limit=limit,
            )
        ]
        keyword_matches = _merge_entity_context_matches(
            keyword_matches,
            [result.model_dump(mode="json") for result in fulltext_matches],
            limit=limit,
            vector_field="fulltext_score",
        )

        if not self._embedding_client or not self._embedding_client.enabled:
            return keyword_matches

        await self.connect()
        async with self._driver.session() as session:
            try:
                query_embedding = await self._embedding_client.embed_text(query.strip())
                vector_result = await session.run(
                    _ENTITY_VECTOR_CONTEXT_CYPHER,
                    index_name=ENTITY_EMBEDDING_INDEX_NAME,
                    query_embedding=query_embedding,
                    limit=limit,
                )
                vector_matches = [
                    _enrich_entity_context_record(record.data()) async for record in vector_result
                ]
            except Exception as exc:  # noqa: BLE001
                logger.warning("entity_vector_query_failed", query=query, error=str(exc))
                return keyword_matches

        return _merge_entity_context_matches(keyword_matches, vector_matches, limit=limit)

    async def query_related_url_entity_context(
        self,
        candidate_urls: list[str],
        *,
        limit_per_url: int = 2,
    ) -> list[dict[str, Any]]:
        if not self.enabled or not candidate_urls:
            return []
        contexts: list[dict[str, Any]] = []
        for candidate_url in candidate_urls:
            lookup_terms = _build_related_url_lookup_terms(candidate_url)
            if not lookup_terms:
                continue
            matches_by_id: dict[str, dict[str, Any]] = {}
            for term in lookup_terms[:RELATED_URL_LOOKUP_TERM_LIMIT]:
                records = await self._query_read_records(
                    "query_related_url_entity_context",
                    _ENTITY_CONTEXT_CYPHER,
                    search_text=term,
                    limit=limit_per_url,
                )
                for record in records:
                    match = _enrich_entity_context_record(record)
                    candidate_match = {**match, "matched_term": term}
                    match_id = str(match.get("entity_id") or f"{match.get('name', '')}:{term}")
                    current = matches_by_id.get(match_id)
                    if current is None or _related_url_match_sort_key(
                        candidate_match
                    ) > _related_url_match_sort_key(current):
                        matches_by_id[match_id] = candidate_match
            if not matches_by_id:
                continue
            matches = sorted(
                matches_by_id.values(),
                key=_related_url_match_sort_key,
                reverse=True,
            )[:limit_per_url]
            contexts.append(
                {
                    "url": candidate_url,
                    "lookup_terms": lookup_terms,
                    "matches": matches,
                    "best_match": matches[0],
                }
            )
        return contexts

    async def query_entity_neighborhoods(
        self,
        entity_ids: list[str],
        *,
        hops: int = 2,
        limit_per_entity: int = 6,
    ) -> list[dict[str, Any]]:
        if not self.enabled or not entity_ids:
            return []
        return await self._query_read_records(
            "query_entity_neighborhoods",
            _ENTITY_NEIGHBORHOOD_CYPHER,
            entity_ids=entity_ids,
            hops=max(1, min(hops, 2)),
            limit_per_entity=limit_per_entity,
        )

    async def query_graphrag_context(
        self,
        *,
        query: str,
        entity_limit: int,
        source_limit: int,
        relation_limit: int,
        neighborhood_limit: int,
        neighborhood_hops: int = 2,
        candidate_urls: list[str] | None = None,
    ) -> dict[str, Any]:
        entities = await self.query_entity_context(query, limit=entity_limit)
        sources = await self.query_source_context(query, limit=source_limit)
        relations = await self.query_relation_context(query, limit=relation_limit)
        candidate_url_entity_context = await self.query_related_url_entity_context(
            candidate_urls or [],
            limit_per_url=2,
        )

        seed_entity_ids: list[str] = []
        for entity in entities:
            entity_id = str(entity.get("entity_id") or "").strip()
            if entity_id and entity_id not in seed_entity_ids:
                seed_entity_ids.append(entity_id)
        for relation in relations:
            for entity_id in (relation.left_entity_id, relation.right_entity_id):
                candidate_id = str(entity_id or "").strip()
                if candidate_id and candidate_id not in seed_entity_ids:
                    seed_entity_ids.append(candidate_id)
        neighborhoods = await self.query_entity_neighborhoods(
            seed_entity_ids[:entity_limit],
            hops=neighborhood_hops,
            limit_per_entity=neighborhood_limit,
        )
        return {
            "query": query,
            "entities": entities,
            "sources": [result.model_dump(mode="json") for result in sources],
            "relations": [result.model_dump(mode="json") for result in relations],
            "neighborhoods": neighborhoods,
            "candidate_url_entity_context": candidate_url_entity_context,
        }

    async def query_source_context(self, query: str, limit: int = 5) -> list[IndexQueryResult]:
        if not self.enabled or not query.strip():
            return []
        vector_results: list[IndexQueryResult] = []
        if self._embedding_client and self._embedding_client.enabled:
            try:
                await self.connect()
                query_embedding = await self._embedding_client.embed_text(query.strip())
                async with self._driver.session() as session:
                    result = await session.run(
                        _SOURCE_VECTOR_QUERY_CYPHER,
                        index_name=SOURCE_EMBEDDING_INDEX_NAME,
                        query_embedding=query_embedding,
                        limit=limit,
                    )
                    vector_results = [
                        IndexQueryResult(
                            source_type=EmbeddingSourceType.source,
                            source_key=str(record["source_key"]),
                            score=float(record["score"]),
                            vector_score=float(record["score"]),
                            hybrid_score=float(record["score"]),
                            title=record.get("title"),
                            summary=record.get("summary"),
                        )
                        async for record in result
                    ]
            except Exception as exc:  # noqa: BLE001
                logger.warning("source_vector_query_failed", query=query, error=str(exc))
        fulltext_results = await self.query_fulltext_sources(query, limit=limit)
        return _merge_index_query_results(fulltext_results, vector_results, limit=limit)

    async def query_relation_context(self, query: str, limit: int = 5) -> list[IndexQueryResult]:
        if not self.enabled or not query.strip():
            return []
        vector_results: list[IndexQueryResult] = []
        if self._embedding_client and self._embedding_client.enabled:
            try:
                await self.connect()
                query_embedding = await self._embedding_client.embed_text(query.strip())
                async with self._driver.session() as session:
                    result = await session.run(
                        _RELATION_VECTOR_QUERY_CYPHER,
                        index_name=RELATION_EMBEDDING_INDEX_NAME,
                        query_embedding=query_embedding,
                        limit=limit,
                    )
                    vector_results = [
                        IndexQueryResult(
                            source_type=EmbeddingSourceType.relation,
                            source_key=str(record["source_key"]),
                            score=float(record["score"]),
                            vector_score=float(record["score"]),
                            hybrid_score=float(record["score"]),
                            left_entity_id=record.get("left_entity_id"),
                            right_entity_id=record.get("right_entity_id"),
                            left_entity_name=record.get("left_entity_name"),
                            right_entity_name=record.get("right_entity_name"),
                            aggregated_text=record.get("aggregated_text"),
                        )
                        async for record in result
                    ]
            except Exception as exc:  # noqa: BLE001
                logger.warning("relation_vector_query_failed", query=query, error=str(exc))
        fulltext_results = await self.query_fulltext_relations(query, limit=limit)
        return _merge_index_query_results(fulltext_results, vector_results, limit=limit)

    async def query_fulltext_entities(self, query: str, limit: int = 5) -> list[IndexQueryResult]:
        if not self.enabled or not query.strip():
            return []
        try:
            records = await self._query_read_records(
                "query_fulltext_entities",
                _ENTITY_FULLTEXT_QUERY_CYPHER,
                index_name=ENTITY_FULLTEXT_INDEX_NAME,
                query=query.strip(),
                limit=limit,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("entity_fulltext_query_failed", query=query, error=str(exc))
            return []
        return [
            IndexQueryResult(
                source_type=EmbeddingSourceType.entity,
                source_key=str(record["entity_id"]),
                entity_id=str(record["entity_id"]),
                score=float(record["score"]),
                fulltext_score=float(record["score"]),
                hybrid_score=float(record["score"]),
                name=record.get("name"),
                summary=record.get("summary"),
                category=record.get("category"),
                aliases=record.get("aliases", []),
            )
            for record in records
        ]

    async def query_fulltext_sources(self, query: str, limit: int = 5) -> list[IndexQueryResult]:
        if not self.enabled or not query.strip():
            return []
        try:
            records = await self._query_read_records(
                "query_fulltext_sources",
                _SOURCE_FULLTEXT_QUERY_CYPHER,
                index_name=SOURCE_FULLTEXT_INDEX_NAME,
                query=query.strip(),
                limit=limit,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("source_fulltext_query_failed", query=query, error=str(exc))
            return []
        return [
            IndexQueryResult(
                source_type=EmbeddingSourceType.source,
                source_key=str(record["source_key"]),
                score=float(record["score"]),
                fulltext_score=float(record["score"]),
                hybrid_score=float(record["score"]),
                title=record.get("title"),
                summary=record.get("summary"),
            )
            for record in records
        ]

    async def query_fulltext_relations(self, query: str, limit: int = 5) -> list[IndexQueryResult]:
        if not self.enabled or not query.strip():
            return []
        try:
            records = await self._query_read_records(
                "query_fulltext_relations",
                _RELATION_FULLTEXT_QUERY_CYPHER,
                index_name=RELATION_FULLTEXT_INDEX_NAME,
                query=query.strip(),
                limit=limit,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("relation_fulltext_query_failed", query=query, error=str(exc))
            return []
        return [
            IndexQueryResult(
                source_type=EmbeddingSourceType.relation,
                source_key=str(record["source_key"]),
                score=float(record["score"]),
                fulltext_score=float(record["score"]),
                hybrid_score=float(record["score"]),
                left_entity_id=record.get("left_entity_id"),
                right_entity_id=record.get("right_entity_id"),
                left_entity_name=record.get("left_entity_name"),
                right_entity_name=record.get("right_entity_name"),
                aggregated_text=record.get("aggregated_text"),
            )
            for record in records
        ]

    async def get_index_statuses(self) -> list[IndexStatusEntry]:
        if not self.enabled:
            return []
        await self.connect()
        managed = {
            (IndexType.vector.value, IndexScope.entity.value): ENTITY_EMBEDDING_INDEX_NAME,
            (IndexType.vector.value, IndexScope.source.value): SOURCE_EMBEDDING_INDEX_NAME,
            (IndexType.vector.value, IndexScope.relation.value): RELATION_EMBEDDING_INDEX_NAME,
            (IndexType.fulltext.value, IndexScope.entity.value): ENTITY_FULLTEXT_INDEX_NAME,
            (IndexType.fulltext.value, IndexScope.source.value): SOURCE_FULLTEXT_INDEX_NAME,
            (IndexType.fulltext.value, IndexScope.relation.value): RELATION_FULLTEXT_INDEX_NAME,
        }
        async with self._driver.session() as session:
            result = await session.run(_SHOW_INDEXES_CYPHER, index_names=list(managed.values()))
            rows = [record.data() async for record in result]
        by_name = {str(row["name"]): row for row in rows}
        statuses: list[IndexStatusEntry] = []
        for (index_type, scope), name in managed.items():
            row = by_name.get(name)
            statuses.append(
                IndexStatusEntry(
                    index_type=IndexType(index_type),
                    scope=IndexScope(scope),
                    name=name,
                    exists=row is not None,
                    state=row.get("state") if row else None,
                    population_percent=float(row["population_percent"]) if row and row.get("population_percent") is not None else None,
                    failure_message=row.get("failure_message") if row else None,
                )
            )
        return statuses

    async def ensure_fulltext_indexes(self) -> list[IndexStatusEntry]:
        if not self.enabled:
            return []
        await self.connect()
        async with self._driver.session() as session:
            for statement in _FULLTEXT_INDEX_CREATE_STATEMENTS:
                await session.run(statement)
        return await self.get_index_statuses()

    async def rebuild_fulltext_indexes(self, scope: IndexScope = IndexScope.all) -> list[IndexStatusEntry]:
        if not self.enabled:
            return []
        await self.connect()
        statements = _fulltext_rebuild_statements(scope)
        async with self._driver.session() as session:
            for statement in statements:
                await session.run(statement)
        return await self.get_index_statuses()

    async def query_entity_merge_candidates(
        self,
        name: str,
        aliases: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if not self.enabled or not name.strip():
            return []
        search_terms = _build_search_terms(name, aliases or [])
        cypher = """
        MATCH (e:Entity)
        WHERE e.normalized_name IN $search_terms
           OR toLower(trim(e.name)) IN $search_terms
           OR any(alias IN coalesce(e.aliases, []) WHERE toLower(trim(alias)) IN $search_terms)
        RETURN e.entity_id AS entity_id,
               e.name AS name,
               e.normalized_name AS normalized_name,
               e.category AS category,
               e.summary AS summary,
               coalesce(e.aliases, []) AS aliases,
               [(e)-[rel:RELATED_TO]->(target:Entity) |
                   {
                       type: coalesce(rel.relation_type, "RELATED_TO"),
                       target: target.name,
                       evidence: rel.evidence
                   }
               ] AS outgoing_relations,
               [(source:Entity)-[rel:RELATED_TO]->(e) |
                   {
                       type: coalesce(rel.relation_type, "RELATED_TO"),
                       source: source.name,
                       evidence: rel.evidence
                   }
               ] AS incoming_relations,
               [(e)-[:MENTIONED_IN]->(source:Source) | source.canonical_url] AS mentioned_in_sources
        """
        return await self._query_read_records(
            "query_entity_merge_candidates",
            cypher,
            search_terms=search_terms,
        )

    async def sync_job(
        self,
        job: JobSummary,
        *,
        request: JobRequest | None = None,
    ) -> None:
        if not self.enabled:
            return
        await self.connect()
        payload = _build_job_node_payload(job, request=request)
        try:
            async with self._driver.session() as session:
                await session.execute_write(self._upsert_job_tx, payload)
        except Neo4jError as exc:
            logger.warning(
                "neo4j_sync_job_failed",
                job_id=job.job_id,
                error=str(exc),
            )

    async def upsert_source_and_entities(
        self,
        job_id: str,
        extraction: PageExtraction,
    ) -> GraphUpdateResult:
        update = GraphUpdateResult()
        entity_ids_to_refresh: set[str] = set()
        if not self.enabled:
            update.created_sources.append(extraction.canonical_url)
            update.created_entities = [entity.name for entity in extraction.extracted_entities]
            return update

        await self.connect()
        source_was_present = await self.source_exists(extraction.canonical_url)

        try:
            async with self._driver.session() as session:
                source_target_hash = _build_source_embedding_target_hash(
                    summary=extraction.summary,
                    version=self._settings.embedding_version,
                )
                retained_entity_ids: set[str] = set()
                await session.execute_write(
                    self._upsert_source_tx,
                    job_id,
                    extraction,
                    source_target_hash,
                )
                for entity in extraction.extracted_entities:
                    entity_update = await session.execute_write(
                        self._upsert_entity_tx,
                        extraction.canonical_url,
                        entity,
                    )
                    if entity_update["created"]:
                        update.created_entities.append(entity.name)
                    else:
                        update.updated_entities.append(entity.name)
                    update.created_relationships += entity_update["created_relationships"]
                    update.deleted_relationships += entity_update["deleted_relationships"]
                    retained_entity_ids.update(entity_update["mentioned_entity_ids"])
                    entity_ids_to_refresh.update(entity_update["mentioned_entity_ids"])
                stale_mentioned_in = await session.execute_write(
                    self._delete_stale_mentioned_in_tx,
                    canonical_url=extraction.canonical_url,
                    retained_entity_ids=sorted(retained_entity_ids),
                )
                update.deleted_relationships += stale_mentioned_in["deleted_relationships"]
                entity_ids_to_refresh.update(stale_mentioned_in["entity_ids"])
                await session.execute_write(
                    self._update_visited_relation_tx,
                    job_id=job_id,
                    extraction=extraction,
                    source_created=not source_was_present,
                    source_update=update.model_dump(mode="json"),
                )
        except Neo4jError as exc:
            logger.exception(
                "neo4j_write_failed",
                job_id=job_id,
                canonical_url=extraction.canonical_url,
                error=str(exc),
            )
            raise

        for entity_id in sorted(entity_ids_to_refresh):
            await self.refresh_entity_embedding_target(entity_id)

        if not source_was_present:
            update.created_sources.append(extraction.canonical_url)
        return update

    async def refresh_entity_embedding_target(self, entity_id: str) -> str | None:
        if not self.enabled:
            return None
        await self.connect()
        async with self._driver.session() as session:
            payload = await session.execute_read(self._get_entity_embedding_source_tx, entity_id)
            if payload is None:
                return None
            embedding_text = build_entity_embedding_text(
                name=str(payload.get("name") or ""),
                category=str(payload.get("category") or "unknown"),
                summary=str(payload.get("summary") or ""),
                aliases=payload.get("aliases", []),
                outgoing_relations=payload.get("outgoing_relations", []),
                incoming_relations=payload.get("incoming_relations", []),
                mentioned_in_sources=payload.get("mentioned_in_sources", []),
                text_max_chars=self._settings.embedding_text_max_chars,
            )
            target_hash = compute_embedding_content_hash(
                version=self._settings.embedding_version,
                text=embedding_text,
            )
            await session.execute_write(
                self._mark_entity_embedding_target_tx,
                entity_id=entity_id,
                target_hash=target_hash,
            )
            return target_hash

    async def list_embedding_candidates(
        self,
        scope: IndexScope,
        *,
        limit: int,
        reindex: bool,
        exclude_source_keys: list[str] | None = None,
    ) -> list[EmbeddingCandidate]:
        if not self.enabled:
            return []
        exclude_source_keys = exclude_source_keys or []
        candidates: list[EmbeddingCandidate] = []
        if scope in {IndexScope.entity, IndexScope.all}:
            candidates.extend(
                await self._list_entity_embedding_candidates(
                    limit=limit,
                    reindex=reindex,
                    exclude_source_keys=exclude_source_keys,
                )
            )
        if scope in {IndexScope.source, IndexScope.all} and len(candidates) < limit:
            candidates.extend(
                await self._list_source_embedding_candidates(
                    limit=limit - len(candidates),
                    reindex=reindex,
                    exclude_source_keys=exclude_source_keys,
                )
            )
        if scope in {IndexScope.relation, IndexScope.all} and len(candidates) < limit:
            candidates.extend(
                await self._list_relation_embedding_candidates(
                    limit=limit - len(candidates),
                    reindex=reindex,
                    exclude_source_keys=exclude_source_keys,
                )
            )
        return candidates[:limit]

    async def prepare_embedding_candidates(
        self,
        scope: IndexScope,
        *,
        reindex: bool,
        sample_limit: int,
    ) -> tuple[dict[str, int], list[IndexCandidateSample]]:
        counts = {
            IndexScope.entity.value: 0,
            IndexScope.source.value: 0,
            IndexScope.relation.value: 0,
        }
        samples: list[IndexCandidateSample] = []
        page_size = max(sample_limit, 128)
        if scope in {IndexScope.entity, IndexScope.all}:
            entity_candidates = await self._collect_embedding_candidates(
                self._list_entity_embedding_candidates,
                reindex=reindex,
                page_size=page_size,
            )
            counts[IndexScope.entity.value] = len(entity_candidates)
            samples.extend(_embedding_candidates_to_samples(entity_candidates[:sample_limit]))
        if scope in {IndexScope.source, IndexScope.all}:
            source_candidates = await self._collect_embedding_candidates(
                self._list_source_embedding_candidates,
                reindex=reindex,
                page_size=page_size,
            )
            counts[IndexScope.source.value] = len(source_candidates)
            samples.extend(_embedding_candidates_to_samples(source_candidates[:sample_limit]))
        if scope in {IndexScope.relation, IndexScope.all}:
            relation_candidates = await self._collect_embedding_candidates(
                self._list_relation_embedding_candidates,
                reindex=reindex,
                page_size=page_size,
            )
            counts[IndexScope.relation.value] = len(relation_candidates)
            samples.extend(_embedding_candidates_to_samples(relation_candidates[:sample_limit]))
        return counts, samples[:sample_limit]

    async def list_fulltext_candidates(
        self,
        scope: IndexScope,
        *,
        limit: int,
        reindex: bool,
        exclude_source_keys: list[str] | None = None,
    ) -> list[TextIndexCandidate]:
        if not self.enabled:
            return []
        exclude_source_keys = exclude_source_keys or []
        candidates: list[TextIndexCandidate] = []
        if scope in {IndexScope.entity, IndexScope.all}:
            candidates.extend(
                await self._list_entity_fulltext_candidates(
                    limit=limit,
                    reindex=reindex,
                    exclude_source_keys=exclude_source_keys,
                )
            )
        if scope in {IndexScope.source, IndexScope.all} and len(candidates) < limit:
            candidates.extend(
                await self._list_source_fulltext_candidates(
                    limit=limit - len(candidates),
                    reindex=reindex,
                    exclude_source_keys=exclude_source_keys,
                )
            )
        if scope in {IndexScope.relation, IndexScope.all} and len(candidates) < limit:
            candidates.extend(
                await self._list_relation_fulltext_candidates(
                    limit=limit - len(candidates),
                    reindex=reindex,
                    exclude_source_keys=exclude_source_keys,
                )
            )
        return candidates[:limit]

    async def prepare_fulltext_candidates(
        self,
        scope: IndexScope,
        *,
        reindex: bool,
        sample_limit: int,
    ) -> tuple[dict[str, int], list[IndexCandidateSample]]:
        counts = {
            IndexScope.entity.value: 0,
            IndexScope.source.value: 0,
            IndexScope.relation.value: 0,
        }
        samples: list[IndexCandidateSample] = []
        page_size = max(sample_limit, 128)
        if scope in {IndexScope.entity, IndexScope.all}:
            entity_candidates = await self._collect_text_candidates(
                self._list_entity_fulltext_candidates,
                reindex=reindex,
                page_size=page_size,
            )
            counts[IndexScope.entity.value] = len(entity_candidates)
            samples.extend(_text_candidates_to_samples(entity_candidates[:sample_limit]))
        if scope in {IndexScope.source, IndexScope.all}:
            source_candidates = await self._collect_text_candidates(
                self._list_source_fulltext_candidates,
                reindex=reindex,
                page_size=page_size,
            )
            counts[IndexScope.source.value] = len(source_candidates)
            samples.extend(_text_candidates_to_samples(source_candidates[:sample_limit]))
        if scope in {IndexScope.relation, IndexScope.all}:
            relation_candidates = await self._collect_text_candidates(
                self._list_relation_fulltext_candidates,
                reindex=reindex,
                page_size=page_size,
            )
            counts[IndexScope.relation.value] = len(relation_candidates)
            samples.extend(_text_candidates_to_samples(relation_candidates[:sample_limit]))
        return counts, samples[:sample_limit]

    async def _collect_embedding_candidates(
        self,
        loader,
        *,
        reindex: bool,
        page_size: int,
    ) -> list[EmbeddingCandidate]:
        collected: list[EmbeddingCandidate] = []
        seen: set[str] = set()
        while True:
            batch = await loader(
                limit=page_size,
                reindex=reindex,
                exclude_source_keys=sorted(seen),
            )
            if not batch:
                break
            collected.extend(batch)
            seen.update(candidate.source_key for candidate in batch)
            if len(batch) < page_size:
                break
        return collected

    async def _collect_text_candidates(
        self,
        loader,
        *,
        reindex: bool,
        page_size: int,
    ) -> list[TextIndexCandidate]:
        collected: list[TextIndexCandidate] = []
        seen: set[str] = set()
        while True:
            batch = await loader(
                limit=page_size,
                reindex=reindex,
                exclude_source_keys=sorted(seen),
            )
            if not batch:
                break
            collected.extend(batch)
            seen.update(candidate.source_key for candidate in batch)
            if len(batch) < page_size:
                break
        return collected

    async def upsert_embeddings(
        self,
        records: list[EmbeddingCandidate],
        embeddings: list[list[float]],
    ) -> None:
        if not self.enabled or not records:
            return
        if len(records) != len(embeddings):
            raise ValueError("Embedding records and vectors must have the same length.")
        await self.connect()
        payload = [
            (
                {
                    "embedding_key": record.embedding_key,
                    "source_type": record.source_type.value,
                    "source_key": record.source_key,
                    "content_hash": record.target_hash,
                    "embedding": vector,
                    "embedding_model": self._settings.openai_embedding_model,
                    "embedding_dim": len(vector),
                    "embedding_version": self._settings.embedding_version,
                    "updated_at": utcnow().isoformat(),
                }
                | (
                    {
                        "left_entity_id": parse_relation_pair_key(record.source_key)[0],
                        "right_entity_id": parse_relation_pair_key(record.source_key)[1],
                        "left_entity_name": parse_relation_pair_key(record.source_key)[0],
                        "right_entity_name": parse_relation_pair_key(record.source_key)[1],
                        "aggregated_text": record.input_text,
                    }
                    if record.source_type == EmbeddingSourceType.relation
                    else {}
                )
            )
            for record, vector in zip(records, embeddings, strict=True)
        ]
        async with self._driver.session() as session:
            await session.execute_write(self._upsert_embeddings_tx, payload)

    async def upsert_fulltext_documents(self, records: list[TextIndexCandidate]) -> None:
        if not self.enabled or not records:
            return
        await self.connect()
        payload = [
            {
                "source_type": record.source_type.value,
                "source_key": record.source_key,
                "title": record.title,
                "name": record.name,
                "summary": record.summary,
                "aggregated_text": record.aggregated_text,
                "left_entity_name": record.left_entity_name,
                "right_entity_name": record.right_entity_name,
                "document_text": record.document_text,
                "target_hash": record.target_hash,
                "updated_at": utcnow().isoformat(),
            }
            for record in records
        ]
        async with self._driver.session() as session:
            await session.execute_write(
                self._upsert_fulltext_documents_tx,
                payload,
                self._settings.embedding_version,
            )

    async def mark_embedding_failed(self, record: EmbeddingCandidate, error: str) -> None:
        if not self.enabled:
            return
        await self.connect()
        async with self._driver.session() as session:
            await session.execute_write(
                self._mark_embedding_failed_tx,
                source_type=record.source_type.value,
                source_key=record.source_key,
                error=error,
            )

    async def mark_fulltext_failed(self, record: TextIndexCandidate, error: str) -> None:
        if not self.enabled:
            return
        await self.connect()
        async with self._driver.session() as session:
            await session.execute_write(
                self._mark_fulltext_failed_tx,
                source_type=record.source_type.value,
                source_key=record.source_key,
                error=error,
            )

    async def query_preview(
        self,
        query: str,
        *,
        entity_limit: int,
        source_limit: int,
        relation_limit: int,
    ) -> dict[str, list[dict[str, Any]]]:
        return await self.query_graphrag_context(
            query=query,
            entity_limit=entity_limit,
            source_limit=source_limit,
            relation_limit=relation_limit,
            neighborhood_limit=max(entity_limit, relation_limit),
            neighborhood_hops=2,
            candidate_urls=[],
        )

    @staticmethod
    async def _upsert_job_tx(tx, payload: dict[str, Any]) -> None:
        await tx.run(
            """
            MERGE (job:CrawlJob {job_id: $job_id})
            SET job.input_type = $input_type,
                job.seed = $seed,
                job.status = $status,
                job.created_at = datetime($created_at),
                job.started_at = coalesce(job.started_at, datetime($created_at)),
                job.updated_at = datetime($updated_at),
                job.completed_at = CASE
                    WHEN $completed_at IS NULL THEN null
                    ELSE datetime($completed_at)
                END,
                job.max_depth = $max_depth,
                job.max_pages = $max_pages,
                job.visited_count = $visited_count,
                job.queued_count = $queued_count,
                job.failed_count = $failed_count,
                job.last_error = $last_error,
                job.summary = $summary,
                job.change_log = $change_log,
                job.request_json = coalesce($request_json, job.request_json),
                job.graph_update_json = coalesce($graph_update_json, job.graph_update_json),
                job.created_entities = $created_entities,
                job.updated_entities = $updated_entities,
                job.created_sources = $created_sources,
                job.created_relationships = $created_relationships,
                job.deleted_relationships = $deleted_relationships
            """,
            **payload,
        )

    @staticmethod
    async def _upsert_source_tx(
        tx,
        job_id: str,
        extraction: PageExtraction,
        source_target_hash: str,
    ) -> None:
        query = """
        MERGE (job:CrawlJob {job_id: $job_id})
        ON CREATE SET job.started_at = datetime(),
                      job.created_at = datetime()
        MERGE (source:Source {canonical_url: $canonical_url})
        SET source.title = $title,
            source.summary = $summary,
            source.content_hash = $content_hash,
            source.fetched_at = datetime(),
            source.updated_at = datetime(),
            source.created_at = coalesce(source.created_at, datetime()),
            source.raw_text_excerpt = $raw_text_excerpt,
            source.embedding_target_hash = $source_target_hash,
            source.embedding_last_error = CASE
                WHEN coalesce(source.embedding_content_hash, '') = $source_target_hash
                THEN source.embedding_last_error
                ELSE null
            END,
            source.embedding_last_dirty_at = CASE
                WHEN coalesce(source.embedding_content_hash, '') = $source_target_hash
                THEN source.embedding_last_dirty_at
                ELSE datetime()
            END
        MERGE (job)-[:VISITED]->(source)
        """
        await tx.run(
            query,
            job_id=job_id,
            canonical_url=extraction.canonical_url,
            title=extraction.title,
            summary=extraction.summary,
            content_hash=extraction.content_hash,
            raw_text_excerpt=extraction.raw_text_excerpt,
            source_target_hash=source_target_hash,
        )

        for discovered_url in extraction.discovered_urls:
            await tx.run(
                """
                MERGE (origin:Source {canonical_url: $source_url})
                MERGE (target:Source {canonical_url: $target_url})
                MERGE (origin)-[:LINKS_TO]->(target)
                """,
                source_url=extraction.canonical_url,
                target_url=discovered_url,
            )

    @staticmethod
    async def _update_visited_relation_tx(
        tx,
        *,
        job_id: str,
        extraction: PageExtraction,
        source_created: bool,
        source_update: dict[str, Any],
    ) -> None:
        await tx.run(
            """
            MATCH (job:CrawlJob {job_id: $job_id})
            MATCH (source:Source {canonical_url: $canonical_url})
            MERGE (job)-[visited:VISITED]->(source)
            SET visited.source_created = $source_created,
                visited.source_title = $source_title,
                visited.source_summary = $source_summary,
                visited.content_hash = $content_hash,
                visited.extracted_entity_count = $extracted_entity_count,
                visited.discovered_url_count = $discovered_url_count,
                visited.created_entities = $created_entities,
                visited.updated_entities = $updated_entities,
                visited.created_sources = $created_sources,
                visited.created_relationships = $created_relationships,
                visited.deleted_relationships = $deleted_relationships,
                visited.modification_summary = $modification_summary,
                visited.change_log = $change_log,
                visited.source_update_json = $source_update_json,
                visited.updated_at = datetime()
            """,
            job_id=job_id,
            canonical_url=extraction.canonical_url,
            source_created=source_created,
            source_title=extraction.title,
            source_summary=extraction.summary,
            content_hash=extraction.content_hash,
            extracted_entity_count=len(extraction.extracted_entities),
            discovered_url_count=len(extraction.discovered_urls),
            created_entities=source_update.get("created_entities", []),
            updated_entities=source_update.get("updated_entities", []),
            created_sources=source_update.get("created_sources", []),
            created_relationships=source_update.get("created_relationships", 0),
            deleted_relationships=source_update.get("deleted_relationships", 0),
            modification_summary=_build_source_modification_summary(
                extraction=extraction,
                source_created=source_created,
                source_update=source_update,
            ),
            change_log=_build_source_change_log(
                extraction=extraction,
                source_created=source_created,
                source_update=source_update,
            ),
            source_update_json=_to_json_string(source_update),
        )

    @staticmethod
    async def _upsert_entity_tx(
        tx,
        canonical_url: str,
        entity: ExtractedEntity,
    ) -> dict[str, Any]:
        mentioned_entity_ids: set[str] = set()
        matches = await Neo4jGraphRepository._find_matching_entities_tx(
            tx,
            entity.name,
            entity.aliases,
        )
        preferred_entity_id = _entity_id(entity.name)
        canonical_match = _select_canonical_match(matches, preferred_entity_id)
        canonical_entity_id = canonical_match["entity_id"] if canonical_match else preferred_entity_id
        created = canonical_match is None

        for match in matches:
            if match["entity_id"] == canonical_entity_id:
                continue
            await Neo4jGraphRepository._merge_entity_into_canonical_tx(
                tx,
                canonical_entity_id=canonical_entity_id,
                duplicate_entity_id=match["entity_id"],
            )

        merged_payload = _build_entity_payload(matches, entity, canonical_entity_id)
        await Neo4jGraphRepository._upsert_entity_node_tx(
            tx,
            canonical_url=canonical_url,
            entity_id=canonical_entity_id,
            name=merged_payload["name"],
            normalized_name=merged_payload["normalized_name"],
            category=merged_payload["category"],
            summary=merged_payload["summary"],
            aliases=merged_payload["aliases"],
            mentioned_in_score=entity.mentioned_in_score,
        )
        if entity.mentioned_in_score is not None:
            mentioned_entity_ids.add(canonical_entity_id)

        created_relationships = 0
        deleted_relationships = 0
        deleted_relation_keys: set[tuple[str, str]] = set()
        for relation in entity.deleted_relations:
            target_name = relation.get("target")
            relation_type = relation.get("type", "RELATED_TO")
            if not target_name:
                continue
            target_entity_id, _ = await Neo4jGraphRepository._resolve_relation_target_entity_tx(
                tx,
                target_name=target_name,
            )
            deleted_relation_keys.add((str(relation_type).strip().casefold(), target_entity_id))
            relation_deleted = await Neo4jGraphRepository._delete_relation_tx(
                tx,
                source_entity_id=canonical_entity_id,
                target_entity_id=target_entity_id,
                relation_type=relation_type,
            )
            deleted_relationships += int(relation_deleted)

        for relation in entity.relations:
            target_name = relation.get("target")
            relation_type = relation.get("type", "RELATED_TO")
            evidence = relation.get("evidence")
            if not target_name:
                continue
            target_entity_id, target_matches = await Neo4jGraphRepository._resolve_relation_target_entity_tx(
                tx,
                target_name=target_name,
            )
            relation_key = (str(relation_type).strip().casefold(), target_entity_id)
            if relation_key in deleted_relation_keys:
                continue
            target_placeholder = ExtractedEntity(
                name=target_name,
                category="unknown",
                summary=_build_relation_target_summary(
                    source_name=merged_payload["name"],
                    relation_type=relation_type,
                    evidence=evidence,
                ),
                aliases=[],
                relations=[],
            )
            target_payload = _build_entity_payload(
                target_matches,
                target_placeholder,
                target_entity_id,
            )
            await Neo4jGraphRepository._upsert_entity_node_tx(
                tx,
                canonical_url=canonical_url,
                entity_id=target_entity_id,
                name=target_payload["name"],
                normalized_name=target_payload["normalized_name"],
                category=target_payload["category"],
                summary=target_payload["summary"],
                aliases=target_payload["aliases"],
                mentioned_in_score=None,
            )
            relation_created = await Neo4jGraphRepository._upsert_relation_tx(
                tx,
                source_entity_id=canonical_entity_id,
                target_entity_id=target_entity_id,
                relation_type=relation_type,
                evidence=evidence,
            )
            created_relationships += int(relation_created)

        return {
            "created": created,
            "entity_id": canonical_entity_id,
            "created_relationships": created_relationships,
            "deleted_relationships": deleted_relationships,
            "mentioned_entity_ids": sorted(mentioned_entity_ids),
        }

    @staticmethod
    async def _resolve_relation_target_entity_tx(
        tx,
        *,
        target_name: str,
    ) -> tuple[str, list[dict[str, Any]]]:
        target_matches = await Neo4jGraphRepository._find_matching_entities_tx(tx, target_name, [])
        target_preferred_id = _entity_id(target_name)
        target_canonical = _select_canonical_match(target_matches, target_preferred_id)
        target_entity_id = target_canonical["entity_id"] if target_canonical else target_preferred_id
        for match in target_matches:
            if match["entity_id"] == target_entity_id:
                continue
            await Neo4jGraphRepository._merge_entity_into_canonical_tx(
                tx,
                canonical_entity_id=target_entity_id,
                duplicate_entity_id=match["entity_id"],
            )
        return target_entity_id, target_matches

    @staticmethod
    async def _find_matching_entities_tx(
        tx,
        name: str,
        aliases: list[str],
    ) -> list[dict[str, Any]]:
        search_terms = _build_search_terms(name, aliases)
        result = await tx.run(
            """
            MATCH (e:Entity)
            WHERE e.normalized_name IN $search_terms
               OR toLower(trim(e.name)) IN $search_terms
               OR any(alias IN coalesce(e.aliases, []) WHERE toLower(trim(alias)) IN $search_terms)
            RETURN e.entity_id AS entity_id,
                   e.name AS name,
                   e.normalized_name AS normalized_name,
                   e.category AS category,
                   e.summary AS summary,
                   coalesce(e.aliases, []) AS aliases
            """,
            search_terms=search_terms,
        )
        return [record.data() async for record in result]

    @staticmethod
    async def _upsert_entity_node_tx(
        tx,
        *,
        canonical_url: str,
        entity_id: str,
        name: str,
        normalized_name: str,
        category: str,
        summary: str,
        aliases: list[str],
        mentioned_in_score: float | None,
    ) -> None:
        await tx.run(
            """
            MATCH (source:Source {canonical_url: $canonical_url})
            MERGE (entity:Entity {entity_id: $entity_id})
            SET entity.name = $name,
                entity.normalized_name = $normalized_name,
                entity.category = $category,
                entity.summary = $summary,
                entity.aliases = $aliases,
                entity.updated_at = datetime(),
                entity.created_at = coalesce(entity.created_at, datetime())
            FOREACH (_ IN CASE WHEN $mentioned_in_score IS NULL THEN [] ELSE [1] END |
                MERGE (entity)-[rel:MENTIONED_IN]->(source)
                SET rel.relevance = $mentioned_in_score
            )
            """,
            canonical_url=canonical_url,
            entity_id=entity_id,
            name=name,
            normalized_name=normalized_name,
            category=category,
            summary=summary,
            aliases=aliases,
            mentioned_in_score=mentioned_in_score,
        )

    @staticmethod
    async def _delete_stale_mentioned_in_tx(
        tx,
        *,
        canonical_url: str,
        retained_entity_ids: list[str],
    ) -> dict[str, Any]:
        result = await tx.run(
            """
            MATCH (source:Source {canonical_url: $canonical_url})
            OPTIONAL MATCH (entity:Entity)-[rel:MENTIONED_IN]->(source)
            WHERE NOT entity.entity_id IN $retained_entity_ids
            WITH collect(DISTINCT entity.entity_id) AS entity_ids, collect(rel) AS rels
            FOREACH (rel IN rels | DELETE rel)
            RETURN [entity_id IN entity_ids WHERE entity_id IS NOT NULL] AS entity_ids,
                   size(rels) AS deleted_relationships
            """,
            canonical_url=canonical_url,
            retained_entity_ids=retained_entity_ids,
        )
        record = await result.single()
        if record is None:
            return {"entity_ids": [], "deleted_relationships": 0}
        return {
            "entity_ids": list(record["entity_ids"] or []),
            "deleted_relationships": int(record["deleted_relationships"] or 0),
        }

    @staticmethod
    async def _merge_entity_into_canonical_tx(
        tx,
        *,
        canonical_entity_id: str,
        duplicate_entity_id: str,
    ) -> None:
        if canonical_entity_id == duplicate_entity_id:
            return
        await tx.run(
            """
            MATCH (duplicate:Entity {entity_id: $duplicate_entity_id})-[rel:MENTIONED_IN]->(source:Source)
            MATCH (canonical:Entity {entity_id: $canonical_entity_id})
            MERGE (canonical)-[merged:MENTIONED_IN]->(source)
            SET merged.relevance = CASE
                WHEN merged.relevance IS NULL THEN coalesce(rel.relevance, $default_relevance)
                WHEN merged.relevance >= coalesce(rel.relevance, $default_relevance) THEN merged.relevance
                ELSE coalesce(rel.relevance, $default_relevance)
            END
            """,
            canonical_entity_id=canonical_entity_id,
            duplicate_entity_id=duplicate_entity_id,
            default_relevance=DEFAULT_MENTIONED_IN_RELEVANCE,
        )
        await tx.run(
            """
            MATCH (duplicate:Entity {entity_id: $duplicate_entity_id})-[rel:RELATED_TO]->(target:Entity)
            MATCH (canonical:Entity {entity_id: $canonical_entity_id})
            WITH canonical, rel, CASE
                WHEN target.entity_id = $duplicate_entity_id THEN canonical
                ELSE target
            END AS resolved_target
            WHERE resolved_target.entity_id <> $canonical_entity_id
            MERGE (canonical)-[merged:RELATED_TO {relation_type: coalesce(rel.relation_type, "RELATED_TO")}]->(resolved_target)
            SET merged.evidence = coalesce(merged.evidence, rel.evidence)
            """,
            canonical_entity_id=canonical_entity_id,
            duplicate_entity_id=duplicate_entity_id,
        )
        await tx.run(
            """
            MATCH (source:Entity)-[rel:RELATED_TO]->(duplicate:Entity {entity_id: $duplicate_entity_id})
            MATCH (canonical:Entity {entity_id: $canonical_entity_id})
            WITH canonical, rel, CASE
                WHEN source.entity_id = $duplicate_entity_id THEN canonical
                ELSE source
            END AS resolved_source
            WHERE resolved_source.entity_id <> $canonical_entity_id
            MERGE (resolved_source)-[merged:RELATED_TO {relation_type: coalesce(rel.relation_type, "RELATED_TO")}]->(canonical)
            SET merged.evidence = coalesce(merged.evidence, rel.evidence)
            """,
            canonical_entity_id=canonical_entity_id,
            duplicate_entity_id=duplicate_entity_id,
        )
        await tx.run(
            """
            MATCH (embedding:Embedding {source_type: 'entity', source_key: $duplicate_entity_id})
            DETACH DELETE embedding
            """,
            duplicate_entity_id=duplicate_entity_id,
        )
        await tx.run(
            """
            MATCH (embedding:RelationEmbedding)-[:EMBEDS]->(:Entity {entity_id: $duplicate_entity_id})
            DETACH DELETE embedding
            """,
            duplicate_entity_id=duplicate_entity_id,
        )
        await tx.run(
            """
            MATCH (duplicate:Entity {entity_id: $duplicate_entity_id})
            DETACH DELETE duplicate
            """,
            duplicate_entity_id=duplicate_entity_id,
        )

    @staticmethod
    async def _upsert_relation_tx(
        tx,
        *,
        source_entity_id: str,
        target_entity_id: str,
        relation_type: str,
        evidence: str | None,
    ) -> bool:
        result = await tx.run(
            """
            MATCH (source:Entity {entity_id: $source_entity_id})
            MATCH (target:Entity {entity_id: $target_entity_id})
            OPTIONAL MATCH (source)-[existing:RELATED_TO {relation_type: $relation_type}]->(target)
            WITH source, target, existing IS NOT NULL AS existed
            MERGE (source)-[rel:RELATED_TO {relation_type: $relation_type}]->(target)
            SET rel.evidence = $evidence
            RETURN existed
            """,
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            relation_type=relation_type,
            evidence=evidence,
        )
        record = await result.single()
        return not bool(record and record["existed"])

    @staticmethod
    async def _delete_relation_tx(
        tx,
        *,
        source_entity_id: str,
        target_entity_id: str,
        relation_type: str,
    ) -> bool:
        result = await tx.run(
            """
            MATCH (source:Entity {entity_id: $source_entity_id})-[rel:RELATED_TO {relation_type: $relation_type}]->(target:Entity {entity_id: $target_entity_id})
            WITH collect(rel) AS rels
            FOREACH (rel IN rels | DELETE rel)
            RETURN size(rels) > 0 AS deleted
            """,
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            relation_type=relation_type,
        )
        record = await result.single()
        await tx.run(
            """
            MATCH (left:Entity {entity_id: $left_entity_id})
            MATCH (right:Entity {entity_id: $right_entity_id})
            OPTIONAL MATCH (left)-[remaining:RELATED_TO]-(right)
            WITH count(remaining) AS remaining_count
            MATCH (embedding:RelationEmbedding {embedding_key: $embedding_key})
            WHERE remaining_count = 0
            DETACH DELETE embedding
            """,
            left_entity_id=min(source_entity_id, target_entity_id),
            right_entity_id=max(source_entity_id, target_entity_id),
            embedding_key=build_embedding_key(
                EmbeddingSourceType.relation,
                build_relation_pair_key(source_entity_id, target_entity_id),
            ),
        )
        return bool(record and record["deleted"])

    async def _list_entity_embedding_candidates(
        self,
        *,
        limit: int,
        reindex: bool,
        exclude_source_keys: list[str],
    ) -> list[EmbeddingCandidate]:
        candidates: list[EmbeddingCandidate] = []
        offset = 0
        page_size = max(limit * 4, 64)
        await self.connect()
        async with self._driver.session() as session:
            while len(candidates) < limit:
                result = await session.run(
                    _ENTITY_EMBEDDING_CANDIDATES_CYPHER,
                    limit=page_size,
                    skip=offset,
                    exclude_keys=exclude_source_keys,
                )
                records = [record.data() async for record in result]
                if not records:
                    break
                for record in records:
                    input_text = build_entity_embedding_text(
                        name=str(record.get("name") or ""),
                        category=str(record.get("category") or "unknown"),
                        summary=str(record.get("summary") or ""),
                        aliases=record.get("aliases", []),
                        outgoing_relations=record.get("outgoing_relations", []),
                        incoming_relations=record.get("incoming_relations", []),
                        mentioned_in_sources=record.get("mentioned_in_sources", []),
                        text_max_chars=self._settings.embedding_text_max_chars,
                    )
                    target_hash = compute_embedding_content_hash(
                        version=self._settings.embedding_version,
                        text=input_text,
                    )
                    if (
                        not reindex
                        and not _embedding_record_is_stale(
                            record=record,
                            target_hash=target_hash,
                            embedding_version=self._settings.embedding_version,
                            embedding_model=self._settings.openai_embedding_model,
                        )
                    ):
                        continue
                    candidates.append(
                        EmbeddingCandidate(
                            source_type=EmbeddingSourceType.entity,
                            source_key=str(record["entity_id"]),
                            embedding_key=build_embedding_key(
                                EmbeddingSourceType.entity,
                                str(record["entity_id"]),
                            ),
                            input_text=input_text,
                            target_hash=target_hash,
                        )
                    )
                    if len(candidates) >= limit:
                        break
                if len(records) < page_size:
                    break
                offset += page_size
        return candidates

    async def _list_source_embedding_candidates(
        self,
        *,
        limit: int,
        reindex: bool,
        exclude_source_keys: list[str],
    ) -> list[EmbeddingCandidate]:
        candidates: list[EmbeddingCandidate] = []
        offset = 0
        page_size = max(limit * 4, 64)
        await self.connect()
        async with self._driver.session() as session:
            while len(candidates) < limit:
                result = await session.run(
                    _SOURCE_EMBEDDING_CANDIDATES_CYPHER,
                    limit=page_size,
                    skip=offset,
                    exclude_keys=exclude_source_keys,
                )
                records = [record.data() async for record in result]
                if not records:
                    break
                for record in records:
                    input_text = build_source_embedding_text(record.get("summary"))
                    target_hash = compute_embedding_content_hash(
                        version=self._settings.embedding_version,
                        text=input_text,
                    )
                    if (
                        not reindex
                        and not _embedding_record_is_stale(
                            record=record,
                            target_hash=target_hash,
                            embedding_version=self._settings.embedding_version,
                            embedding_model=self._settings.openai_embedding_model,
                        )
                    ):
                        continue
                    candidates.append(
                        EmbeddingCandidate(
                            source_type=EmbeddingSourceType.source,
                            source_key=str(record["canonical_url"]),
                            embedding_key=build_embedding_key(
                                EmbeddingSourceType.source,
                                str(record["canonical_url"]),
                            ),
                            input_text=input_text,
                            target_hash=target_hash,
                        )
                    )
                    if len(candidates) >= limit:
                        break
                if len(records) < page_size:
                    break
                offset += page_size
        return candidates

    async def _list_relation_embedding_candidates(
        self,
        *,
        limit: int,
        reindex: bool,
        exclude_source_keys: list[str],
    ) -> list[EmbeddingCandidate]:
        candidates: list[EmbeddingCandidate] = []
        offset = 0
        page_size = max(limit * 4, 64)
        await self.connect()
        async with self._driver.session() as session:
            while len(candidates) < limit:
                result = await session.run(
                    _RELATION_EMBEDDING_CANDIDATES_CYPHER,
                    limit=page_size,
                    skip=offset,
                    exclude_keys=exclude_source_keys,
                )
                records = [record.data() async for record in result]
                if not records:
                    break
                for record in records:
                    pair_key = build_relation_pair_key(
                        str(record["left_entity_id"]),
                        str(record["right_entity_id"]),
                    )
                    input_text = build_relation_embedding_text(
                        left_entity_id=str(record["left_entity_id"]),
                        left_entity_name=str(record.get("left_entity_name") or record["left_entity_id"]),
                        right_entity_id=str(record["right_entity_id"]),
                        right_entity_name=str(record.get("right_entity_name") or record["right_entity_id"]),
                        relations=record.get("relations", []),
                        text_max_chars=self._settings.embedding_text_max_chars,
                    )
                    target_hash = compute_embedding_content_hash(
                        version=self._settings.embedding_version,
                        text=input_text,
                    )
                    if (
                        not reindex
                        and not _embedding_record_is_stale(
                            record=record,
                            target_hash=target_hash,
                            embedding_version=self._settings.embedding_version,
                            embedding_model=self._settings.openai_embedding_model,
                        )
                    ):
                        continue
                    candidates.append(
                        EmbeddingCandidate(
                            source_type=EmbeddingSourceType.relation,
                            source_key=pair_key,
                            embedding_key=build_embedding_key(EmbeddingSourceType.relation, pair_key),
                            input_text=input_text,
                            target_hash=target_hash,
                        )
                    )
                    if len(candidates) >= limit:
                        break
                if len(records) < page_size:
                    break
                offset += page_size
        return candidates

    async def _list_entity_fulltext_candidates(
        self,
        *,
        limit: int,
        reindex: bool,
        exclude_source_keys: list[str],
    ) -> list[TextIndexCandidate]:
        candidates: list[TextIndexCandidate] = []
        offset = 0
        page_size = max(limit * 4, 64)
        await self.connect()
        async with self._driver.session() as session:
            while len(candidates) < limit:
                result = await session.run(
                    _ENTITY_FULLTEXT_CANDIDATES_CYPHER,
                    limit=page_size,
                    skip=offset,
                    exclude_keys=exclude_source_keys,
                )
                records = [record.data() async for record in result]
                if not records:
                    break
                for record in records:
                    document_text = _build_entity_fulltext_text(
                        name=str(record.get("name") or ""),
                        aliases=record.get("aliases", []),
                        summary=str(record.get("summary") or ""),
                    )
                    target_hash = _compute_fulltext_content_hash(
                        version=self._settings.embedding_version,
                        text=document_text,
                    )
                    if not reindex and not _fulltext_record_is_stale(
                        record=record,
                        target_hash=target_hash,
                        version=self._settings.embedding_version,
                    ):
                        continue
                    candidates.append(
                        TextIndexCandidate(
                            source_type=EmbeddingSourceType.entity,
                            source_key=str(record["entity_id"]),
                            name=record.get("name"),
                            summary=record.get("summary"),
                            document_text=document_text,
                            target_hash=target_hash,
                        )
                    )
                    if len(candidates) >= limit:
                        break
                if len(records) < page_size:
                    break
                offset += page_size
        return candidates

    async def _list_source_fulltext_candidates(
        self,
        *,
        limit: int,
        reindex: bool,
        exclude_source_keys: list[str],
    ) -> list[TextIndexCandidate]:
        candidates: list[TextIndexCandidate] = []
        offset = 0
        page_size = max(limit * 4, 64)
        await self.connect()
        async with self._driver.session() as session:
            while len(candidates) < limit:
                result = await session.run(
                    _SOURCE_FULLTEXT_CANDIDATES_CYPHER,
                    limit=page_size,
                    skip=offset,
                    exclude_keys=exclude_source_keys,
                )
                records = [record.data() async for record in result]
                if not records:
                    break
                for record in records:
                    document_text = _build_source_fulltext_text(
                        canonical_url=str(record["canonical_url"]),
                        title=str(record.get("title") or ""),
                        summary=str(record.get("summary") or ""),
                    )
                    target_hash = _compute_fulltext_content_hash(
                        version=self._settings.embedding_version,
                        text=document_text,
                    )
                    if not reindex and not _fulltext_record_is_stale(
                        record=record,
                        target_hash=target_hash,
                        version=self._settings.embedding_version,
                    ):
                        continue
                    candidates.append(
                        TextIndexCandidate(
                            source_type=EmbeddingSourceType.source,
                            source_key=str(record["canonical_url"]),
                            title=record.get("title"),
                            summary=record.get("summary"),
                            document_text=document_text,
                            target_hash=target_hash,
                        )
                    )
                    if len(candidates) >= limit:
                        break
                if len(records) < page_size:
                    break
                offset += page_size
        return candidates

    async def _list_relation_fulltext_candidates(
        self,
        *,
        limit: int,
        reindex: bool,
        exclude_source_keys: list[str],
    ) -> list[TextIndexCandidate]:
        candidates: list[TextIndexCandidate] = []
        offset = 0
        page_size = max(limit * 4, 64)
        await self.connect()
        async with self._driver.session() as session:
            while len(candidates) < limit:
                result = await session.run(
                    _RELATION_FULLTEXT_CANDIDATES_CYPHER,
                    limit=page_size,
                    skip=offset,
                    exclude_keys=exclude_source_keys,
                )
                records = [record.data() async for record in result]
                if not records:
                    break
                for record in records:
                    pair_key = build_relation_pair_key(
                        str(record["left_entity_id"]),
                        str(record["right_entity_id"]),
                    )
                    document_text = _build_relation_fulltext_text(
                        left_entity_name=str(record.get("left_entity_name") or record["left_entity_id"]),
                        right_entity_name=str(record.get("right_entity_name") or record["right_entity_id"]),
                        aggregated_text=str(record.get("aggregated_text") or ""),
                    )
                    target_hash = _compute_fulltext_content_hash(
                        version=self._settings.embedding_version,
                        text=document_text,
                    )
                    if not reindex and not _fulltext_record_is_stale(
                        record=record,
                        target_hash=target_hash,
                        version=self._settings.embedding_version,
                    ):
                        continue
                    candidates.append(
                        TextIndexCandidate(
                            source_type=EmbeddingSourceType.relation,
                            source_key=pair_key,
                            aggregated_text=record.get("aggregated_text"),
                            left_entity_name=record.get("left_entity_name"),
                            right_entity_name=record.get("right_entity_name"),
                            document_text=document_text,
                            target_hash=target_hash,
                        )
                    )
                    if len(candidates) >= limit:
                        break
                if len(records) < page_size:
                    break
                offset += page_size
        return candidates

    @staticmethod
    async def _get_entity_embedding_source_tx(tx, entity_id: str) -> dict[str, Any] | None:
        result = await tx.run(_ENTITY_EMBEDDING_SOURCE_CYPHER, entity_id=entity_id)
        record = await result.single()
        return record.data() if record else None

    @staticmethod
    async def _mark_entity_embedding_target_tx(
        tx,
        *,
        entity_id: str,
        target_hash: str,
    ) -> None:
        await tx.run(
            """
            MATCH (entity:Entity {entity_id: $entity_id})
            SET entity.embedding_target_hash = $target_hash,
                entity.embedding_last_error = CASE
                    WHEN coalesce(entity.embedding_content_hash, '') = $target_hash
                    THEN entity.embedding_last_error
                    ELSE null
                END,
                entity.embedding_last_dirty_at = CASE
                    WHEN coalesce(entity.embedding_content_hash, '') = $target_hash
                    THEN entity.embedding_last_dirty_at
                    ELSE datetime()
                END
            """,
            entity_id=entity_id,
            target_hash=target_hash,
        )

    @staticmethod
    async def _upsert_embeddings_tx(tx, records: list[dict[str, Any]]) -> None:
        await tx.run(
            """
            UNWIND $records AS record
            CALL {
                WITH record
                OPTIONAL MATCH (entity:Entity {entity_id: record.source_key})
                WHERE record.source_type = 'entity'
                RETURN entity AS node, null AS related_node, 'entity' AS resolved_type
                UNION
                WITH record
                OPTIONAL MATCH (source:Source {canonical_url: record.source_key})
                WHERE record.source_type = 'source'
                RETURN source AS node, null AS related_node, 'source' AS resolved_type
                UNION
                WITH record
                OPTIONAL MATCH (left:Entity {entity_id: record.left_entity_id})
                OPTIONAL MATCH (right:Entity {entity_id: record.right_entity_id})
                WHERE record.source_type = 'relation'
                RETURN left AS node, right AS related_node, 'relation' AS resolved_type
            }
            WITH record, node, related_node, resolved_type
            WHERE node IS NOT NULL
            FOREACH (_ IN CASE WHEN resolved_type IN ['entity', 'source'] THEN [1] ELSE [] END |
                SET node.embedding = record.embedding,
                    node.embedding_dim = record.embedding_dim,
                    node.embedding_model = record.embedding_model,
                    node.embedding_version = record.embedding_version,
                    node.embedding_content_hash = record.content_hash,
                    node.embedding_target_hash = record.content_hash,
                    node.embedding_last_synced_at = datetime(record.updated_at),
                    node.embedding_last_error = null
            )
            FOREACH (_ IN CASE WHEN resolved_type = 'relation' AND related_node IS NOT NULL THEN [1] ELSE [] END |
                MERGE (embedding:Embedding {embedding_key: record.embedding_key})
                SET embedding.left_entity_id = record.left_entity_id,
                    embedding.left_entity_name = record.left_entity_name,
                    embedding.source_type = record.source_type,
                    embedding.source_key = record.source_key,
                    embedding.embedding = record.embedding,
                    embedding.embedding_model = record.embedding_model,
                    embedding.embedding_dim = record.embedding_dim,
                    embedding.embedding_version = record.embedding_version,
                    embedding.content_hash = record.content_hash,
                    embedding.embedding_updated_at = datetime(record.updated_at),
                    embedding.last_error = null,
                    embedding.right_entity_id = record.right_entity_id,
                    embedding.right_entity_name = record.right_entity_name,
                    embedding.aggregated_text = record.aggregated_text,
                    embedding:RelationEmbedding
                MERGE (embedding)-[:EMBEDS {position: 'left'}]->(node)
                MERGE (embedding)-[:EMBEDS {position: 'right'}]->(related_node)
            )
            """,
            records=records,
        )

    @staticmethod
    async def _upsert_fulltext_documents_tx(tx, records: list[dict[str, Any]], version: str) -> None:
        await tx.run(
            """
            UNWIND $records AS record
            CALL {
                WITH record
                OPTIONAL MATCH (entity:Entity {entity_id: record.source_key})
                WHERE record.source_type = 'entity'
                SET entity.fulltext_text = record.document_text,
                    entity.fulltext_content_hash = record.target_hash,
                    entity.fulltext_version = $version,
                    entity.fulltext_last_synced_at = datetime(record.updated_at),
                    entity.fulltext_last_error = null
                RETURN entity IS NOT NULL AS updated
                UNION
                WITH record
                OPTIONAL MATCH (source:Source {canonical_url: record.source_key})
                WHERE record.source_type = 'source'
                SET source.fulltext_text = record.document_text,
                    source.fulltext_content_hash = record.target_hash,
                    source.fulltext_version = $version,
                    source.fulltext_last_synced_at = datetime(record.updated_at),
                    source.fulltext_last_error = null
                RETURN source IS NOT NULL AS updated
                UNION
                WITH record
                WHERE record.source_type = 'relation'
                MERGE (embedding:Embedding {embedding_key: 'relation:' + record.source_key})
                SET embedding.source_type = record.source_type,
                    embedding.source_key = record.source_key,
                    embedding.aggregated_text = record.aggregated_text,
                    embedding.left_entity_id = split(record.source_key, '::')[0],
                    embedding.right_entity_id = split(record.source_key, '::')[1],
                    embedding.left_entity_name = record.left_entity_name,
                    embedding.right_entity_name = record.right_entity_name,
                    embedding.fulltext_text = record.document_text,
                    embedding.fulltext_content_hash = record.target_hash,
                    embedding.fulltext_version = $version,
                    embedding.fulltext_last_synced_at = datetime(record.updated_at),
                    embedding.fulltext_last_error = null,
                    embedding:RelationEmbedding
                RETURN true AS updated
            }
            RETURN count(*) AS updated_count
            """,
            records=records,
            version=version,
        )

    @staticmethod
    async def _mark_embedding_failed_tx(
        tx,
        *,
        source_type: str,
        source_key: str,
        error: str,
    ) -> None:
        await tx.run(
            """
            OPTIONAL MATCH (node)
            WHERE ($source_type = 'entity' AND node:Entity AND node.entity_id = $source_key)
               OR ($source_type = 'source' AND node:Source AND node.canonical_url = $source_key)
            FOREACH (_ IN CASE WHEN node IS NOT NULL THEN [1] ELSE [] END |
                SET node.embedding_last_error = $error,
                    node.embedding_last_dirty_at = coalesce(node.embedding_last_dirty_at, datetime())
            )
            OPTIONAL MATCH (embedding:Embedding {embedding_key: $embedding_key})
            FOREACH (_ IN CASE WHEN embedding IS NOT NULL AND $source_type = 'relation' THEN [1] ELSE [] END |
                SET embedding.last_error = $error
            )
            """,
            source_type=source_type,
            source_key=source_key,
            error=error,
            embedding_key=build_embedding_key(EmbeddingSourceType(source_type), source_key),
        )

    @staticmethod
    async def _mark_fulltext_failed_tx(
        tx,
        *,
        source_type: str,
        source_key: str,
        error: str,
    ) -> None:
        await tx.run(
            """
            OPTIONAL MATCH (node)
            WHERE ($source_type = 'entity' AND node:Entity AND node.entity_id = $source_key)
               OR ($source_type = 'source' AND node:Source AND node.canonical_url = $source_key)
            FOREACH (_ IN CASE WHEN node IS NOT NULL THEN [1] ELSE [] END |
                SET node.fulltext_last_error = $error
            )
            OPTIONAL MATCH (embedding:RelationEmbedding {embedding_key: 'relation:' + $source_key})
            FOREACH (_ IN CASE WHEN embedding IS NOT NULL AND $source_type = 'relation' THEN [1] ELSE [] END |
                SET embedding.fulltext_last_error = $error
            )
            """,
            source_type=source_type,
            source_key=source_key,
            error=error,
        )

    async def _query_read_records(
        self,
        query_name: str,
        cypher: str,
        **params: Any,
    ) -> list[dict[str, Any]]:
        if self._read_adapter.enabled:
            try:
                return await self._read_adapter.query(cypher, params)
            except Exception as exc:  # noqa: BLE001
                logger.warning("langchain_graph_read_failed", query_name=query_name, error=str(exc))

        await self.connect()
        async with self._driver.session() as session:
            result = await session.run(cypher, **params)
            return [record.data() async for record in result]


def _build_entity_payload(
    matches: list[dict[str, Any]],
    entity: ExtractedEntity,
    canonical_entity_id: str,
) -> dict[str, Any]:
    canonical_match = _select_canonical_match(matches, canonical_entity_id)
    names = [match.get("name", "") for match in matches]
    aliases: list[str] = []
    for match in matches:
        aliases.extend(match.get("aliases", []))
        match_name = match.get("name")
        if match_name:
            aliases.append(match_name)
    aliases.extend(entity.aliases)

    canonical_name = (
        canonical_match.get("name")
        if canonical_match and canonical_match.get("name")
        else entity.name
    )
    if not canonical_name.strip():
        canonical_name = next((name for name in names if name.strip()), entity.name)

    return {
        "name": canonical_name,
        "normalized_name": _normalize_entity_name(canonical_name),
        "category": _choose_category([entity.category, *[match.get("category") for match in matches]]),
        "summary": _choose_summary([entity.summary, *[match.get("summary") for match in matches]]),
        "aliases": _merge_aliases([alias for alias in aliases if alias != canonical_name]),
    }


def _select_canonical_match(
    matches: list[dict[str, Any]],
    preferred_entity_id: str,
) -> dict[str, Any] | None:
    if not matches:
        return None
    return max(matches, key=lambda match: _match_priority(match, preferred_entity_id))


def _match_priority(match: dict[str, Any], preferred_entity_id: str) -> tuple[int, int, int, int]:
    return (
        int(match.get("entity_id") == preferred_entity_id),
        int((match.get("category") or "unknown").lower() != "unknown"),
        len(match.get("summary") or ""),
        len(match.get("aliases") or []),
    )


def _choose_category(categories: list[str | None]) -> str:
    for category in categories:
        if category and category.strip() and category.lower() != "unknown":
            return category
    return "unknown"


def _choose_summary(summaries: list[str | None]) -> str:
    non_empty = [summary.strip() for summary in summaries if summary and summary.strip()]
    if not non_empty:
        return ""
    return max(non_empty, key=len)


def _merge_aliases(values: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = " ".join(value.split()).strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        merged.append(cleaned)
    return merged


def _build_relation_target_summary(
    *,
    source_name: str,
    relation_type: str,
    evidence: str | None,
) -> str:
    cleaned_evidence = " ".join((evidence or "").split()).strip()
    if cleaned_evidence:
        return cleaned_evidence
    cleaned_source = " ".join(source_name.split()).strip() or "其他实体"
    cleaned_relation = " ".join(relation_type.split()).strip() or "RELATED_TO"
    return f"在关系 {cleaned_relation} 中与 {cleaned_source} 有关联。"


def _build_search_terms(name: str, aliases: list[str]) -> list[str]:
    terms: list[str] = []
    for value in [name, *aliases]:
        lookup_term = _normalize_lookup_term(value)
        if lookup_term:
            terms.append(lookup_term)
        normalized_name = _normalize_entity_name(value)
        if normalized_name:
            terms.append(normalized_name)
    return sorted({term for term in terms if term})


def _normalize_lookup_term(value: str) -> str:
    return " ".join(value.split()).strip().casefold()


def _normalize_entity_name(name: str) -> str:
    normalized = re.sub(r"[\s/\-]+", "_", name.strip().casefold())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or "unknown_entity"


def _entity_id(name: str) -> str:
    return _normalize_entity_name(name)


def _enrich_entity_context_record(record: dict[str, Any]) -> dict[str, Any]:
    aliases = [alias for alias in record.get("aliases", []) if isinstance(alias, str) and alias.strip()]
    outgoing_relations = int(record.get("outgoing_relations") or 0)
    incoming_relations = int(record.get("incoming_relations") or 0)
    mentioned_in_count = int(record.get("mentioned_in_count") or 0)
    relation_count = outgoing_relations + incoming_relations
    completeness_score = _calculate_entity_completeness_score(
        summary=str(record.get("summary") or ""),
        alias_count=len(aliases),
        relation_count=relation_count,
        mentioned_in_count=mentioned_in_count,
    )
    return {
        **record,
        "aliases": aliases,
        "outgoing_relations": outgoing_relations,
        "incoming_relations": incoming_relations,
        "relation_count": relation_count,
        "mentioned_in_count": mentioned_in_count,
        "completeness_score": completeness_score,
        "completeness_level": _classify_entity_completeness(completeness_score),
    }


def _calculate_entity_completeness_score(
    *,
    summary: str,
    alias_count: int,
    relation_count: int,
    mentioned_in_count: int,
) -> int:
    cleaned_summary = " ".join(summary.split()).strip()
    score = 0
    summary_length = len(cleaned_summary)
    if summary_length >= 280:
        score += 4
    elif summary_length >= 160:
        score += 3
    elif summary_length >= 80:
        score += 2
    elif summary_length >= 40:
        score += 1

    if alias_count >= 4:
        score += 2
    elif alias_count >= 1:
        score += 1

    if relation_count >= 6:
        score += 3
    elif relation_count >= 3:
        score += 2
    elif relation_count >= 1:
        score += 1

    if mentioned_in_count >= 4:
        score += 2
    elif mentioned_in_count >= 2:
        score += 1

    return score


def _classify_entity_completeness(score: int) -> str:
    if score >= COMPLETE_ENTITY_SCORE_THRESHOLD:
        return "complete"
    if score >= SUBSTANTIAL_ENTITY_SCORE_THRESHOLD:
        return "substantial"
    return "sparse"


def _build_related_url_lookup_terms(url: str) -> list[str]:
    parsed = urlsplit(url)
    raw_segments = [unquote(segment).strip() for segment in parsed.path.split("/") if segment.strip()]
    if not raw_segments:
        return []

    candidates: list[str] = []
    last_segment = raw_segments[-1]
    if _is_entity_like_lookup_term(last_segment):
        candidates.append(last_segment)

    for segment in reversed(raw_segments[:-1]):
        if _is_entity_like_lookup_term(segment):
            candidates.append(segment)
        if len(candidates) >= RELATED_URL_LOOKUP_TERM_LIMIT:
            break

    cleaned_candidates: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        cleaned = re.sub(r"[_\-]+", " ", candidate).strip()
        normalized = _normalize_lookup_term(cleaned)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        cleaned_candidates.append(cleaned)
    return cleaned_candidates


def _is_entity_like_lookup_term(term: str) -> bool:
    normalized = _normalize_lookup_term(term)
    if not normalized or len(normalized) < 2:
        return False
    if normalized.isdigit():
        return False
    if normalized in RELATED_URL_GENERIC_SEGMENTS:
        return False
    return bool(re.search(r"[\u4e00-\u9fffA-Za-z]", normalized))


def _related_url_match_sort_key(match: dict[str, Any]) -> tuple[int, int, int, int]:
    return (
        _match_term_strength(match),
        int(match.get("completeness_score") or 0),
        int(match.get("relation_count") or 0),
        len(str(match.get("summary") or "")),
    )


def _match_term_strength(match: dict[str, Any]) -> int:
    matched_term = _normalize_lookup_term(str(match.get("matched_term") or ""))
    if not matched_term:
        return 0
    entity_name = _normalize_lookup_term(str(match.get("name") or ""))
    aliases = [_normalize_lookup_term(str(alias)) for alias in match.get("aliases", [])]
    if matched_term == entity_name or matched_term in aliases:
        return 3
    if matched_term in entity_name or any(matched_term in alias for alias in aliases):
        return 2
    if entity_name in matched_term or any(alias and alias in matched_term for alias in aliases):
        return 1
    return 0


def _build_job_node_payload(
    job: JobSummary,
    *,
    request: JobRequest | None = None,
) -> dict[str, Any]:
    graph_update = job.graph_update.model_dump(mode="json") if job.graph_update else None
    return {
        "job_id": job.job_id,
        "input_type": job.input_type.value,
        "seed": job.seed,
        "status": job.status.value,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "max_depth": job.max_depth,
        "max_pages": job.max_pages,
        "visited_count": job.visited_count,
        "queued_count": job.queued_count,
        "failed_count": job.failed_count,
        "last_error": job.last_error,
        "summary": _build_job_summary_text(job),
        "change_log": _build_job_change_log_text(job),
        "request_json": _to_json_string(request.model_dump(mode="json") if request else None),
        "graph_update_json": _to_json_string(graph_update),
        "created_entities": list(job.graph_update.created_entities) if job.graph_update else [],
        "updated_entities": list(job.graph_update.updated_entities) if job.graph_update else [],
        "created_sources": list(job.graph_update.created_sources) if job.graph_update else [],
        "created_relationships": job.graph_update.created_relationships if job.graph_update else 0,
        "deleted_relationships": job.graph_update.deleted_relationships if job.graph_update else 0,
    }


def _build_job_summary_text(job: JobSummary) -> str:
    parts = [
        f"任务状态：{job.status.value}",
        f"输入类型：{job.input_type.value}",
        f"种子：{job.seed}",
        f"访问页面：{job.visited_count}",
        f"队列长度：{job.queued_count}",
        f"失败数：{job.failed_count}",
        f"抓取限制：深度 {job.max_depth} / 页面 {job.max_pages}",
    ]
    if job.graph_update is not None:
        parts.append(_build_graph_update_summary(job.graph_update))
    if job.last_error:
        parts.append(f"最近错误：{job.last_error}")
    if job.completed_at:
        parts.append(f"完成时间：{job.completed_at.isoformat()}")
    return "；".join(parts)


def _build_job_change_log_text(job: JobSummary) -> str:
    lines = [
        "任务概览",
        f"- 状态：{job.status.value}",
        f"- 输入类型：{job.input_type.value}",
        f"- 种子：{job.seed}",
        f"- 创建时间：{job.created_at.isoformat()}",
        f"- 更新时间：{job.updated_at.isoformat()}",
        f"- 完成时间：{job.completed_at.isoformat() if job.completed_at else '未完成'}",
        f"- 抓取限制：最大深度 {job.max_depth}，最大页面数 {job.max_pages}",
        f"- 执行统计：访问页面 {job.visited_count}，队列剩余 {job.queued_count}，失败数 {job.failed_count}",
    ]
    if job.graph_update is not None:
        lines.extend(
            [
                "",
                "修改记录",
                f"- 新增来源（{len(job.graph_update.created_sources)}）：{_format_string_list(job.graph_update.created_sources)}",
                f"- 新增实体（{len(job.graph_update.created_entities)}）：{_format_string_list(job.graph_update.created_entities)}",
                f"- 更新实体（{len(job.graph_update.updated_entities)}）：{_format_string_list(job.graph_update.updated_entities)}",
                f"- 新增关系：{job.graph_update.created_relationships}",
                f"- 删除关系：{job.graph_update.deleted_relationships}",
            ]
        )
    if job.last_error:
        lines.extend(["", "错误信息", f"- {job.last_error}"])
    return "\n".join(lines)


def _build_graph_update_summary(update: GraphUpdateResult) -> str:
    return (
        "图谱变更："
        f"新增来源 {len(update.created_sources)} 个，"
        f"新增实体 {len(update.created_entities)} 个，"
        f"更新实体 {len(update.updated_entities)} 个，"
        f"新增关系 {update.created_relationships} 条，"
        f"删除关系 {update.deleted_relationships} 条"
    )


def _build_source_modification_summary(
    *,
    extraction: PageExtraction,
    source_created: bool,
    source_update: dict[str, Any],
) -> str:
    parts = [
        f"来源：{extraction.canonical_url}",
        "来源状态：新增来源" if source_created else "来源状态：更新已有来源",
        f"来源摘要长度：{len(extraction.summary)}",
        f"抽取实体：{len(extraction.extracted_entities)} 个",
        f"发现链接：{len(extraction.discovered_urls)} 个",
        f"新增实体：{len(source_update.get('created_entities', []))} 个",
        f"更新实体：{len(source_update.get('updated_entities', []))} 个",
        f"新增关系：{source_update.get('created_relationships', 0)} 条",
        f"删除关系：{source_update.get('deleted_relationships', 0)} 条",
    ]
    return "；".join(parts)


def _build_source_change_log(
    *,
    extraction: PageExtraction,
    source_created: bool,
    source_update: dict[str, Any],
) -> str:
    lines = [
        "来源修改详情",
        f"- 来源 URL：{extraction.canonical_url}",
        f"- 来源标题：{extraction.title or '无标题'}",
        f"- 来源状态：{'新增来源' if source_created else '更新已有来源'}",
        f"- 来源摘要：{extraction.summary or '无摘要'}",
        f"- 抽取实体数：{len(extraction.extracted_entities)}",
        f"- 发现链接数：{len(extraction.discovered_urls)}",
        f"- 新增实体（{len(source_update.get('created_entities', []))}）：{_format_string_list(source_update.get('created_entities', []))}",
        f"- 更新实体（{len(source_update.get('updated_entities', []))}）：{_format_string_list(source_update.get('updated_entities', []))}",
        f"- 新增来源引用（{len(source_update.get('created_sources', []))}）：{_format_string_list(source_update.get('created_sources', []))}",
        f"- 新增关系：{source_update.get('created_relationships', 0)}",
        f"- 删除关系：{source_update.get('deleted_relationships', 0)}",
    ]
    return "\n".join(lines)


def _format_string_list(values: list[str], limit: int = 20) -> str:
    cleaned = [value for value in values if isinstance(value, str) and value.strip()]
    if not cleaned:
        return "无"
    if len(cleaned) <= limit:
        return "、".join(cleaned)
    remaining = len(cleaned) - limit
    return f"{'、'.join(cleaned[:limit])} 等 {len(cleaned)} 项（其余 {remaining} 项省略）"


def _to_json_string(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _build_source_embedding_target_hash(*, summary: str, version: str) -> str:
    return compute_embedding_content_hash(
        version=version,
        text=build_source_embedding_text(summary),
    )


def _merge_entity_context_matches(
    keyword_matches: list[dict[str, Any]],
    vector_matches: list[dict[str, Any]],
    *,
    limit: int,
    vector_field: str = "vector_score",
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}

    for rank, match in enumerate(keyword_matches, start=1):
        entity_id = str(match.get("entity_id") or "")
        if not entity_id:
            continue
        current = merged.get(entity_id, {**match, "hybrid_score": 0.0})
        current["hybrid_score"] = float(current.get("hybrid_score") or 0.0) + (3.0 / rank)
        merged[entity_id] = {**current, **match}

    for rank, match in enumerate(vector_matches, start=1):
        entity_id = str(match.get("entity_id") or "")
        if not entity_id:
            continue
        current = merged.get(entity_id, {**match, "hybrid_score": 0.0})
        vector_score = float(match.get(vector_field) or 0.0)
        current["hybrid_score"] = float(current.get("hybrid_score") or 0.0) + vector_score + (1.0 / rank)
        current[vector_field] = vector_score
        merged[entity_id] = {**current, **match}

    return sorted(
        merged.values(),
        key=lambda item: (
            float(item.get("hybrid_score") or 0.0),
            int(item.get("completeness_score") or 0),
            int(item.get("relation_count") or 0),
            len(str(item.get("summary") or "")),
        ),
        reverse=True,
    )[:limit]


def _merge_index_query_results(
    fulltext_results: list[IndexQueryResult],
    vector_results: list[IndexQueryResult],
    *,
    limit: int,
) -> list[IndexQueryResult]:
    merged: dict[str, IndexQueryResult] = {}
    for rank, result in enumerate(fulltext_results, start=1):
        current = merged.get(result.source_key, result.model_copy(deep=True))
        current.hybrid_score = float(current.hybrid_score or 0.0) + float(result.fulltext_score or 0.0) + (
            1.5 / rank
        )
        current.score = float(current.hybrid_score or 0.0)
        merged[result.source_key] = current
    for rank, result in enumerate(vector_results, start=1):
        current = merged.get(result.source_key, result.model_copy(deep=True))
        current.vector_score = result.vector_score
        current.hybrid_score = float(current.hybrid_score or 0.0) + float(result.vector_score or 0.0) + (
            1.0 / rank
        )
        current.score = float(current.hybrid_score or 0.0)
        merged[result.source_key] = _merge_index_query_result_fields(current, result)
    return sorted(
        merged.values(),
        key=lambda item: (
            float(item.hybrid_score or 0.0),
            float(item.vector_score or 0.0),
            float(item.fulltext_score or 0.0),
            len(item.summary or item.aggregated_text or item.title or item.name or ""),
        ),
        reverse=True,
    )[:limit]


def _merge_index_query_result_fields(
    current: IndexQueryResult,
    incoming: IndexQueryResult,
) -> IndexQueryResult:
    payload = current.model_dump(mode="python")
    for field, value in incoming.model_dump(mode="python").items():
        if value in (None, [], ""):
            continue
        payload[field] = value
    return IndexQueryResult.model_validate(payload)


def _embedding_candidates_to_samples(candidates: list[EmbeddingCandidate]) -> list[IndexCandidateSample]:
    return [
        IndexCandidateSample(
            source_type=candidate.source_type,
            source_key=candidate.source_key,
            target_hash=candidate.target_hash,
        )
        for candidate in candidates
    ]


def _text_candidates_to_samples(candidates: list[TextIndexCandidate]) -> list[IndexCandidateSample]:
    return [
        IndexCandidateSample(
            source_type=candidate.source_type,
            source_key=candidate.source_key,
            title=candidate.title,
            name=candidate.name,
            summary=candidate.summary,
            aggregated_text=candidate.aggregated_text,
            left_entity_name=candidate.left_entity_name,
            right_entity_name=candidate.right_entity_name,
            target_hash=candidate.target_hash,
        )
        for candidate in candidates
    ]


def _embedding_record_is_stale(
    *,
    record: dict[str, Any],
    target_hash: str,
    embedding_version: str,
    embedding_model: str,
) -> bool:
    return (
        not str(record.get("embedding_content_hash") or "").strip()
        or str(record.get("embedding_content_hash") or "") != target_hash
        or str(record.get("embedding_version") or "") != embedding_version
        or str(record.get("embedding_model") or "") != embedding_model
        or bool(str(record.get("embedding_last_error") or "").strip())
    )


def _fulltext_record_is_stale(
    *,
    record: dict[str, Any],
    target_hash: str,
    version: str,
) -> bool:
    return (
        not str(record.get("fulltext_content_hash") or "").strip()
        or str(record.get("fulltext_content_hash") or "") != target_hash
        or str(record.get("fulltext_version") or "") != version
        or bool(str(record.get("fulltext_last_error") or "").strip())
    )


def _compute_fulltext_content_hash(*, version: str, text: str) -> str:
    return compute_embedding_content_hash(version=version, text=text)


def _build_entity_fulltext_text(*, name: str, aliases: list[str], summary: str) -> str:
    parts = [name.strip()]
    if aliases:
        parts.append(" ".join(alias.strip() for alias in aliases if str(alias).strip()))
    if summary.strip():
        parts.append(summary.strip())
    return "\n".join(part for part in parts if part)


def _build_source_fulltext_text(*, canonical_url: str, title: str, summary: str) -> str:
    parts = [title.strip(), summary.strip(), canonical_url.strip()]
    return "\n".join(part for part in parts if part)


def _build_relation_fulltext_text(
    *,
    left_entity_name: str,
    right_entity_name: str,
    aggregated_text: str,
) -> str:
    parts = [left_entity_name.strip(), right_entity_name.strip(), aggregated_text.strip()]
    return "\n".join(part for part in parts if part)


def _fulltext_rebuild_statements(scope: IndexScope) -> list[str]:
    statements: list[str] = []
    mapping = {
        IndexScope.entity: ENTITY_FULLTEXT_INDEX_NAME,
        IndexScope.source: SOURCE_FULLTEXT_INDEX_NAME,
        IndexScope.relation: RELATION_FULLTEXT_INDEX_NAME,
    }
    scopes = [IndexScope.entity, IndexScope.source, IndexScope.relation]
    for candidate_scope in scopes:
        if scope not in {IndexScope.all, candidate_scope}:
            continue
        statements.append(f"DROP INDEX {mapping[candidate_scope]} IF EXISTS")
    for candidate_scope in scopes:
        if scope not in {IndexScope.all, candidate_scope}:
            continue
        statements.append(_FULLTEXT_INDEX_CREATE_STATEMENTS[scopes.index(candidate_scope)])
    return statements


_ENTITY_CONTEXT_CYPHER = """
MATCH (e:Entity)
WHERE toLower(e.name) CONTAINS toLower($search_text)
   OR any(alias IN coalesce(e.aliases, []) WHERE toLower(alias) CONTAINS toLower($search_text))
WITH e,
     CASE
         WHEN toLower(trim(e.name)) = toLower(trim($search_text)) THEN 3
         WHEN any(alias IN coalesce(e.aliases, []) WHERE toLower(trim(alias)) = toLower(trim($search_text))) THEN 2
         ELSE 1
     END AS match_score
OPTIONAL MATCH (e)-[outgoing:RELATED_TO]->()
WITH e, match_score, count(DISTINCT outgoing) AS outgoing_relations
OPTIONAL MATCH ()-[incoming:RELATED_TO]->(e)
WITH e, match_score, outgoing_relations, count(DISTINCT incoming) AS incoming_relations
OPTIONAL MATCH (e)-[:MENTIONED_IN]->(source:Source)
WITH e,
     match_score,
     outgoing_relations,
     incoming_relations,
     count(DISTINCT source) AS mentioned_in_count
RETURN e.entity_id AS entity_id,
       e.name AS name,
       e.category AS category,
       e.summary AS summary,
       coalesce(e.aliases, []) AS aliases,
       outgoing_relations,
       incoming_relations,
       mentioned_in_count
ORDER BY match_score DESC,
         (outgoing_relations + incoming_relations) DESC,
         size(coalesce(e.summary, "")) DESC,
         size(coalesce(e.aliases, [])) DESC
LIMIT $limit
"""

_ENTITY_VECTOR_CONTEXT_CYPHER = """
CALL db.index.vector.queryNodes($index_name, $limit, $query_embedding)
YIELD node, score
WHERE node:Entity
WITH node AS entity, score
OPTIONAL MATCH (entity)-[outgoing:RELATED_TO]->()
WITH entity, score, count(DISTINCT outgoing) AS outgoing_relations
OPTIONAL MATCH ()-[incoming:RELATED_TO]->(entity)
WITH entity, score, outgoing_relations, count(DISTINCT incoming) AS incoming_relations
OPTIONAL MATCH (entity)-[:MENTIONED_IN]->(source:Source)
WITH entity, score, outgoing_relations, incoming_relations, count(DISTINCT source) AS mentioned_in_count
RETURN entity.entity_id AS entity_id,
       entity.name AS name,
       entity.category AS category,
       entity.summary AS summary,
       coalesce(entity.aliases, []) AS aliases,
       outgoing_relations,
       incoming_relations,
       mentioned_in_count,
       score AS vector_score
ORDER BY score DESC
LIMIT $limit
"""

_SOURCE_VECTOR_QUERY_CYPHER = """
CALL db.index.vector.queryNodes($index_name, $limit, $query_embedding)
YIELD node, score
WHERE node:Source
RETURN node.canonical_url AS source_key,
       node.title AS title,
       node.summary AS summary,
       score
ORDER BY score DESC
LIMIT $limit
"""

_RELATION_VECTOR_QUERY_CYPHER = """
CALL db.index.vector.queryNodes($index_name, $limit, $query_embedding)
YIELD node, score
WHERE node:RelationEmbedding
RETURN node.source_key AS source_key,
       node.left_entity_id AS left_entity_id,
       node.right_entity_id AS right_entity_id,
       node.aggregated_text AS aggregated_text,
       node.score AS stored_score,
       node.embedding_updated_at AS embedding_updated_at,
       node.content_hash AS content_hash,
       score,
       coalesce([(node)-[:EMBEDS {position: 'left'}]->(left:Entity) | left.name][0], node.left_entity_id) AS left_entity_name,
       coalesce([(node)-[:EMBEDS {position: 'right'}]->(right:Entity) | right.name][0], node.right_entity_id) AS right_entity_name
ORDER BY score DESC
LIMIT $limit
"""

_ENTITY_FULLTEXT_QUERY_CYPHER = """
CALL db.index.fulltext.queryNodes($index_name, $query, {limit: $limit})
YIELD node, score
WHERE node:Entity
OPTIONAL MATCH (node)-[outgoing:RELATED_TO]->()
WITH node, score, count(DISTINCT outgoing) AS outgoing_relations
OPTIONAL MATCH ()-[incoming:RELATED_TO]->(node)
WITH node, score, outgoing_relations, count(DISTINCT incoming) AS incoming_relations
OPTIONAL MATCH (node)-[:MENTIONED_IN]->(source:Source)
WITH node, score, outgoing_relations, incoming_relations, count(DISTINCT source) AS mentioned_in_count
RETURN node.entity_id AS entity_id,
       node.name AS name,
       node.category AS category,
       node.summary AS summary,
       coalesce(node.aliases, []) AS aliases,
       outgoing_relations,
       incoming_relations,
       mentioned_in_count,
       score AS fulltext_score
ORDER BY score DESC
LIMIT $limit
"""

_SOURCE_FULLTEXT_QUERY_CYPHER = """
CALL db.index.fulltext.queryNodes($index_name, $query, {limit: $limit})
YIELD node, score
WHERE node:Source
RETURN node.canonical_url AS source_key,
       node.title AS title,
       node.summary AS summary,
       score
ORDER BY score DESC
LIMIT $limit
"""

_RELATION_FULLTEXT_QUERY_CYPHER = """
CALL db.index.fulltext.queryNodes($index_name, $query, {limit: $limit})
YIELD node, score
WHERE node:RelationEmbedding
RETURN node.source_key AS source_key,
       node.left_entity_id AS left_entity_id,
       node.right_entity_id AS right_entity_id,
       node.left_entity_name AS left_entity_name,
       node.right_entity_name AS right_entity_name,
       node.aggregated_text AS aggregated_text,
       score
ORDER BY score DESC
LIMIT $limit
"""

_ENTITY_EMBEDDING_SOURCE_CYPHER = """
MATCH (entity:Entity {entity_id: $entity_id})
RETURN entity.entity_id AS entity_id,
       entity.name AS name,
       entity.category AS category,
       entity.summary AS summary,
       coalesce(entity.aliases, []) AS aliases,
       [(entity)-[rel:RELATED_TO]->(target:Entity) |
           {
               type: coalesce(rel.relation_type, "RELATED_TO"),
               target: target.name,
               evidence: rel.evidence
           }
       ] AS outgoing_relations,
       [(source:Entity)-[rel:RELATED_TO]->(entity) |
           {
               type: coalesce(rel.relation_type, "RELATED_TO"),
               source: source.name,
               evidence: rel.evidence
           }
       ] AS incoming_relations,
       [(entity)-[:MENTIONED_IN]->(source:Source) | source.canonical_url] AS mentioned_in_sources
"""

_ENTITY_EMBEDDING_CANDIDATES_CYPHER = """
MATCH (entity:Entity)
WHERE NOT entity.entity_id IN $exclude_keys
RETURN entity.entity_id AS entity_id,
       entity.name AS name,
       entity.category AS category,
       entity.summary AS summary,
       coalesce(entity.aliases, []) AS aliases,
       entity.embedding_target_hash AS embedding_target_hash,
       entity.embedding_last_error AS embedding_last_error,
       entity.embedding_content_hash AS embedding_content_hash,
       entity.embedding_version AS embedding_version,
       entity.embedding_model AS embedding_model,
       [(entity)-[rel:RELATED_TO]->(target:Entity) |
           {
               type: coalesce(rel.relation_type, "RELATED_TO"),
               target: target.name,
               evidence: rel.evidence
           }
       ] AS outgoing_relations,
       [(source:Entity)-[rel:RELATED_TO]->(entity) |
           {
               type: coalesce(rel.relation_type, "RELATED_TO"),
               source: source.name,
               evidence: rel.evidence
           }
       ] AS incoming_relations,
       [(entity)-[:MENTIONED_IN]->(source:Source) | source.canonical_url] AS mentioned_in_sources
ORDER BY entity.updated_at DESC, entity.name ASC
SKIP $skip
LIMIT $limit
"""

_SOURCE_EMBEDDING_CANDIDATES_CYPHER = """
MATCH (source:Source)
WHERE NOT source.canonical_url IN $exclude_keys
RETURN source.canonical_url AS canonical_url,
       source.summary AS summary,
       source.embedding_target_hash AS embedding_target_hash,
       source.embedding_last_error AS embedding_last_error,
       source.embedding_content_hash AS embedding_content_hash,
       source.embedding_version AS embedding_version,
       source.embedding_model AS embedding_model
ORDER BY source.fetched_at DESC, source.canonical_url ASC
SKIP $skip
LIMIT $limit
"""

_RELATION_EMBEDDING_CANDIDATES_CYPHER = """
MATCH (left:Entity)-[rel:RELATED_TO]-(right:Entity)
WHERE left.entity_id < right.entity_id
  AND NOT (left.entity_id + '::' + right.entity_id) IN $exclude_keys
WITH left, right, collect(
    {
        source_entity_id: startNode(rel).entity_id,
        source_name: startNode(rel).name,
        target_entity_id: endNode(rel).entity_id,
        target_name: endNode(rel).name,
        type: coalesce(rel.relation_type, "RELATED_TO"),
        evidence: rel.evidence
    }
) AS relations
OPTIONAL MATCH (embedding:RelationEmbedding {embedding_key: 'relation:' + left.entity_id + '::' + right.entity_id})
RETURN left.entity_id AS left_entity_id,
       left.name AS left_entity_name,
       right.entity_id AS right_entity_id,
       right.name AS right_entity_name,
       relations,
       embedding.content_hash AS embedding_content_hash,
       embedding.embedding_version AS embedding_version,
       embedding.embedding_model AS embedding_model,
       embedding.last_error AS embedding_last_error
ORDER BY left.updated_at DESC, right.updated_at DESC, left.entity_id ASC, right.entity_id ASC
SKIP $skip
LIMIT $limit
"""

_ENTITY_FULLTEXT_CANDIDATES_CYPHER = """
MATCH (entity:Entity)
WHERE NOT entity.entity_id IN $exclude_keys
RETURN entity.entity_id AS entity_id,
       entity.name AS name,
       entity.summary AS summary,
       coalesce(entity.aliases, []) AS aliases,
       entity.fulltext_content_hash AS fulltext_content_hash,
       entity.fulltext_version AS fulltext_version,
       entity.fulltext_last_error AS fulltext_last_error
ORDER BY entity.updated_at DESC, entity.name ASC
SKIP $skip
LIMIT $limit
"""

_SOURCE_FULLTEXT_CANDIDATES_CYPHER = """
MATCH (source:Source)
WHERE NOT source.canonical_url IN $exclude_keys
RETURN source.canonical_url AS canonical_url,
       source.title AS title,
       source.summary AS summary,
       source.fulltext_content_hash AS fulltext_content_hash,
       source.fulltext_version AS fulltext_version,
       source.fulltext_last_error AS fulltext_last_error
ORDER BY source.fetched_at DESC, source.canonical_url ASC
SKIP $skip
LIMIT $limit
"""

_RELATION_FULLTEXT_CANDIDATES_CYPHER = """
MATCH (left:Entity)-[rel:RELATED_TO]-(right:Entity)
WHERE left.entity_id < right.entity_id
  AND NOT (left.entity_id + '::' + right.entity_id) IN $exclude_keys
WITH left, right, collect(coalesce(rel.evidence, "")) AS evidences
OPTIONAL MATCH (embedding:RelationEmbedding {embedding_key: 'relation:' + left.entity_id + '::' + right.entity_id})
RETURN left.entity_id AS left_entity_id,
       left.name AS left_entity_name,
       right.entity_id AS right_entity_id,
       right.name AS right_entity_name,
       reduce(text = "", item IN evidences |
           CASE
               WHEN text = "" THEN item
               WHEN item = "" THEN text
               ELSE text + " | " + item
           END
       ) AS aggregated_text,
       embedding.fulltext_content_hash AS fulltext_content_hash,
       embedding.fulltext_version AS fulltext_version,
       embedding.fulltext_last_error AS fulltext_last_error
ORDER BY left.updated_at DESC, right.updated_at DESC, left.entity_id ASC, right.entity_id ASC
SKIP $skip
LIMIT $limit
"""

_ENTITY_NEIGHBORHOOD_CYPHER = """
UNWIND $entity_ids AS entity_id
MATCH (seed:Entity {entity_id: entity_id})
CALL {
    WITH seed
    MATCH path = (seed)-[rels:RELATED_TO*1..2]-(neighbor:Entity)
    WHERE seed <> neighbor AND length(path) <= $hops
    WITH neighbor,
         rels,
         length(path) AS hop_count,
         [rel IN rels | coalesce(rel.relation_type, "RELATED_TO")] AS relation_types,
         [rel IN rels | coalesce(rel.evidence, "")] AS evidences
    ORDER BY hop_count ASC, size(coalesce(neighbor.summary, "")) DESC, neighbor.name ASC
    LIMIT $limit_per_entity
    RETURN collect(
        {
            neighbor_entity_id: neighbor.entity_id,
            neighbor_name: neighbor.name,
            hop_count: hop_count,
            relation_types: relation_types,
            evidence: reduce(text = "", item IN evidences |
                CASE
                    WHEN text = "" THEN item
                    WHEN item = "" THEN text
                    ELSE text + " | " + item
                END
            )
        }
    ) AS neighbors
}
RETURN seed.entity_id AS seed_entity_id,
       seed.name AS seed_name,
       neighbors
"""

_SHOW_INDEXES_CYPHER = """
SHOW INDEXES YIELD name, state, populationPercent, failureMessage
WHERE name IN $index_names
RETURN name,
       state,
       populationPercent AS population_percent,
       failureMessage AS failure_message
"""

_FULLTEXT_INDEX_CREATE_STATEMENTS = [
    (
        "CREATE FULLTEXT INDEX "
        + ENTITY_FULLTEXT_INDEX_NAME
        + " IF NOT EXISTS FOR (entity:Entity) ON EACH [entity.fulltext_text]"
    ),
    (
        "CREATE FULLTEXT INDEX "
        + SOURCE_FULLTEXT_INDEX_NAME
        + " IF NOT EXISTS FOR (source:Source) ON EACH [source.fulltext_text]"
    ),
    (
        "CREATE FULLTEXT INDEX "
        + RELATION_FULLTEXT_INDEX_NAME
        + " IF NOT EXISTS FOR (embedding:RelationEmbedding) ON EACH [embedding.fulltext_text]"
    ),
]

COMPLETE_ENTITY_SCORE_THRESHOLD = 7
SUBSTANTIAL_ENTITY_SCORE_THRESHOLD = 4
RELATED_URL_LOOKUP_TERM_LIMIT = 3
RELATED_URL_GENERIC_SEGMENTS = {
    "wiki",
    "wikis",
    "index.php",
    "index",
    "entry",
    "entries",
    "page",
    "pages",
    "detail",
    "details",
    "view",
    "article",
    "articles",
    "news",
    "notice",
    "notices",
    "announcement",
    "announcements",
    "event",
    "events",
    "version",
    "guide",
    "guides",
    "story",
    "lore",
    "character",
    "characters",
    "resonator",
    "resonators",
    "weapon",
    "weapons",
    "echo",
    "echoes",
}
