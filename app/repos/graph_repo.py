from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any
from urllib.parse import unquote, urlsplit

from neo4j import AsyncGraphDatabase
from neo4j.exceptions import Neo4jError

from app.core.config import Settings
from app.core.logging import get_logger
from app.models import (
    ExtractedEntity,
    GraphUpdateResult,
    JobRequest,
    JobSummary,
    PageExtraction,
)

logger = get_logger(__name__)


class Neo4jGraphRepository:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._driver = None
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

    async def ensure_constraints(self) -> None:
        if not self.enabled:
            return
        await self.connect()
        statements = [
            (
                "CREATE CONSTRAINT page_canonical_url IF NOT EXISTS "
                "FOR (p:Page) REQUIRE p.canonical_url IS UNIQUE"
            ),
            (
                "CREATE CONSTRAINT crawl_job_id IF NOT EXISTS "
                "FOR (j:CrawlJob) REQUIRE j.job_id IS UNIQUE"
            ),
            (
                "CREATE CONSTRAINT entity_entity_id IF NOT EXISTS "
                "FOR (e:Entity) REQUIRE e.entity_id IS UNIQUE"
            ),
        ]
        async with self._driver.session() as session:
            for statement in statements:
                await session.run(statement)

    async def page_exists(self, canonical_url: str) -> bool:
        if not self.enabled:
            return False
        await self.connect()
        async with self._driver.session() as session:
            result = await session.run(
                "MATCH (p:Page {canonical_url: $canonical_url}) RETURN count(p) > 0 AS exists",
                canonical_url=canonical_url,
            )
            record = await result.single()
            return bool(record and record["exists"])

    async def page_fetched_since(self, canonical_url: str, cutoff: datetime) -> bool:
        if not self.enabled:
            return False
        await self.connect()
        async with self._driver.session() as session:
            result = await session.run(
                """
                MATCH (p:Page {canonical_url: $canonical_url})
                RETURN p.fetched_at IS NOT NULL
                   AND p.fetched_at >= datetime($cutoff) AS is_recent
                """,
                canonical_url=canonical_url,
                cutoff=cutoff.isoformat(),
            )
            record = await result.single()
            return bool(record and record["is_recent"])

    async def query_entity_context(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        if not self.enabled or not query.strip():
            return []
        await self.connect()
        async with self._driver.session() as session:
            result = await session.run(_ENTITY_CONTEXT_CYPHER, search_text=query, limit=limit)
            return [_enrich_entity_context_record(record.data()) async for record in result]

    async def query_related_url_entity_context(
        self,
        candidate_urls: list[str],
        *,
        limit_per_url: int = 2,
    ) -> list[dict[str, Any]]:
        if not self.enabled or not candidate_urls:
            return []
        await self.connect()
        contexts: list[dict[str, Any]] = []
        async with self._driver.session() as session:
            for candidate_url in candidate_urls:
                lookup_terms = _build_related_url_lookup_terms(candidate_url)
                if not lookup_terms:
                    continue
                matches_by_id: dict[str, dict[str, Any]] = {}
                for term in lookup_terms[:RELATED_URL_LOOKUP_TERM_LIMIT]:
                    result = await session.run(_ENTITY_CONTEXT_CYPHER, search_text=term, limit=limit_per_url)
                    async for record in result:
                        match = _enrich_entity_context_record(record.data())
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

    async def query_entity_merge_candidates(
        self,
        name: str,
        aliases: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if not self.enabled or not name.strip():
            return []
        await self.connect()
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
               [(e)-[:MENTIONED_IN]->(page:Page) | page.canonical_url] AS mentioned_in_pages
        """
        async with self._driver.session() as session:
            result = await session.run(cypher, search_terms=search_terms)
            return [record.data() async for record in result]

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

    async def upsert_page_and_entities(
        self,
        job_id: str,
        extraction: PageExtraction,
    ) -> GraphUpdateResult:
        update = GraphUpdateResult()
        if not self.enabled:
            update.created_pages.append(extraction.canonical_url)
            update.created_entities = [entity.name for entity in extraction.extracted_entities]
            return update

        await self.connect()
        page_was_present = await self.page_exists(extraction.canonical_url)

        try:
            async with self._driver.session() as session:
                await session.execute_write(
                    self._upsert_page_tx,
                    job_id,
                    extraction,
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
                await session.execute_write(
                    self._update_visited_relation_tx,
                    job_id=job_id,
                    extraction=extraction,
                    page_created=not page_was_present,
                    page_update=update.model_dump(mode="json"),
                )
        except Neo4jError as exc:
            logger.exception(
                "neo4j_write_failed",
                job_id=job_id,
                canonical_url=extraction.canonical_url,
                error=str(exc),
            )
            raise

        if not page_was_present:
            update.created_pages.append(extraction.canonical_url)
        return update

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
                job.created_pages = $created_pages,
                job.created_relationships = $created_relationships,
                job.deleted_relationships = $deleted_relationships
            """,
            **payload,
        )

    @staticmethod
    async def _upsert_page_tx(tx, job_id: str, extraction: PageExtraction) -> None:
        query = """
        MERGE (job:CrawlJob {job_id: $job_id})
        ON CREATE SET job.started_at = datetime(),
                      job.created_at = datetime()
        MERGE (page:Page {canonical_url: $canonical_url})
        SET page.title = $title,
            page.summary = $summary,
            page.content_hash = $content_hash,
            page.fetched_at = datetime(),
            page.raw_text_excerpt = $raw_text_excerpt
        MERGE (job)-[:VISITED]->(page)
        """
        await tx.run(
            query,
            job_id=job_id,
            canonical_url=extraction.canonical_url,
            title=extraction.title,
            summary=extraction.summary,
            content_hash=extraction.content_hash,
            raw_text_excerpt=extraction.raw_text_excerpt,
        )

        for discovered_url in extraction.discovered_urls:
            await tx.run(
                """
                MERGE (source:Page {canonical_url: $source_url})
                MERGE (target:Page {canonical_url: $target_url})
                MERGE (source)-[:LINKS_TO]->(target)
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
        page_created: bool,
        page_update: dict[str, Any],
    ) -> None:
        await tx.run(
            """
            MATCH (job:CrawlJob {job_id: $job_id})
            MATCH (page:Page {canonical_url: $canonical_url})
            MERGE (job)-[visited:VISITED]->(page)
            SET visited.page_created = $page_created,
                visited.page_title = $page_title,
                visited.page_summary = $page_summary,
                visited.content_hash = $content_hash,
                visited.extracted_entity_count = $extracted_entity_count,
                visited.discovered_url_count = $discovered_url_count,
                visited.created_entities = $created_entities,
                visited.updated_entities = $updated_entities,
                visited.created_pages = $created_pages,
                visited.created_relationships = $created_relationships,
                visited.deleted_relationships = $deleted_relationships,
                visited.modification_summary = $modification_summary,
                visited.change_log = $change_log,
                visited.page_update_json = $page_update_json,
                visited.updated_at = datetime()
            """,
            job_id=job_id,
            canonical_url=extraction.canonical_url,
            page_created=page_created,
            page_title=extraction.title,
            page_summary=extraction.summary,
            content_hash=extraction.content_hash,
            extracted_entity_count=len(extraction.extracted_entities),
            discovered_url_count=len(extraction.discovered_urls),
            created_entities=page_update.get("created_entities", []),
            updated_entities=page_update.get("updated_entities", []),
            created_pages=page_update.get("created_pages", []),
            created_relationships=page_update.get("created_relationships", 0),
            deleted_relationships=page_update.get("deleted_relationships", 0),
            modification_summary=_build_page_modification_summary(
                extraction=extraction,
                page_created=page_created,
                page_update=page_update,
            ),
            change_log=_build_page_change_log(
                extraction=extraction,
                page_created=page_created,
                page_update=page_update,
            ),
            page_update_json=_to_json_string(page_update),
        )

    @staticmethod
    async def _upsert_entity_tx(
        tx,
        canonical_url: str,
        entity: ExtractedEntity,
    ) -> dict[str, Any]:
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
        )

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
            "created_relationships": created_relationships,
            "deleted_relationships": deleted_relationships,
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
    ) -> None:
        await tx.run(
            """
            MATCH (page:Page {canonical_url: $canonical_url})
            MERGE (entity:Entity {entity_id: $entity_id})
            SET entity.name = $name,
                entity.normalized_name = $normalized_name,
                entity.category = $category,
                entity.summary = $summary,
                entity.aliases = $aliases
            MERGE (entity)-[:MENTIONED_IN]->(page)
            """,
            canonical_url=canonical_url,
            entity_id=entity_id,
            name=name,
            normalized_name=normalized_name,
            category=category,
            summary=summary,
            aliases=aliases,
        )

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
            MATCH (duplicate:Entity {entity_id: $duplicate_entity_id})-[:MENTIONED_IN]->(page:Page)
            MATCH (canonical:Entity {entity_id: $canonical_entity_id})
            MERGE (canonical)-[:MENTIONED_IN]->(page)
            """,
            canonical_entity_id=canonical_entity_id,
            duplicate_entity_id=duplicate_entity_id,
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
        return bool(record and record["deleted"])


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
        "created_pages": list(job.graph_update.created_pages) if job.graph_update else [],
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
                f"- 新增页面（{len(job.graph_update.created_pages)}）：{_format_string_list(job.graph_update.created_pages)}",
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
        f"新增页面 {len(update.created_pages)} 个，"
        f"新增实体 {len(update.created_entities)} 个，"
        f"更新实体 {len(update.updated_entities)} 个，"
        f"新增关系 {update.created_relationships} 条，"
        f"删除关系 {update.deleted_relationships} 条"
    )


def _build_page_modification_summary(
    *,
    extraction: PageExtraction,
    page_created: bool,
    page_update: dict[str, Any],
) -> str:
    parts = [
        f"页面：{extraction.canonical_url}",
        "页面状态：新增页面" if page_created else "页面状态：更新已有页面",
        f"页面摘要长度：{len(extraction.summary)}",
        f"抽取实体：{len(extraction.extracted_entities)} 个",
        f"发现链接：{len(extraction.discovered_urls)} 个",
        f"新增实体：{len(page_update.get('created_entities', []))} 个",
        f"更新实体：{len(page_update.get('updated_entities', []))} 个",
        f"新增关系：{page_update.get('created_relationships', 0)} 条",
        f"删除关系：{page_update.get('deleted_relationships', 0)} 条",
    ]
    return "；".join(parts)


def _build_page_change_log(
    *,
    extraction: PageExtraction,
    page_created: bool,
    page_update: dict[str, Any],
) -> str:
    lines = [
        "页面修改详情",
        f"- 页面 URL：{extraction.canonical_url}",
        f"- 页面标题：{extraction.title or '无标题'}",
        f"- 页面状态：{'新增页面' if page_created else '更新已有页面'}",
        f"- 页面摘要：{extraction.summary or '无摘要'}",
        f"- 抽取实体数：{len(extraction.extracted_entities)}",
        f"- 发现链接数：{len(extraction.discovered_urls)}",
        f"- 新增实体（{len(page_update.get('created_entities', []))}）：{_format_string_list(page_update.get('created_entities', []))}",
        f"- 更新实体（{len(page_update.get('updated_entities', []))}）：{_format_string_list(page_update.get('updated_entities', []))}",
        f"- 新增页面引用（{len(page_update.get('created_pages', []))}）：{_format_string_list(page_update.get('created_pages', []))}",
        f"- 新增关系：{page_update.get('created_relationships', 0)}",
        f"- 删除关系：{page_update.get('deleted_relationships', 0)}",
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
OPTIONAL MATCH (e)-[:MENTIONED_IN]->(page:Page)
WITH e,
     match_score,
     outgoing_relations,
     incoming_relations,
     count(DISTINCT page) AS mentioned_in_count
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
