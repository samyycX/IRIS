from __future__ import annotations

import asyncio
import json
import re
from time import monotonic
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit

from openai import AsyncOpenAI

from app.core.config import Settings
from app.core.logging import get_logger
from app.models import ExtractedEntity
from app.services.llm.prompts import (
    get_prompt_bundle,
)

logger = get_logger(__name__)


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._prompts = get_prompt_bundle(settings.prompt_profile)
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key or "missing-key",
            base_url=settings.openai_base_url,
        )
        self.enabled = bool(settings.openai_api_key)

    async def extract_knowledge(
        self,
        *,
        url: str,
        title: str | None,
        text: str,
        context: list[dict[str, Any]],
    ) -> tuple[str, list[ExtractedEntity]]:
        if not self.enabled:
            logger.info(
                "llm_extract_knowledge_fallback_disabled",
                url=url,
                title=title,
                text_length=len(text),
                context_count=len(context),
            )
            return self._fallback_extract(title=title, text=text)

        truncated_text = _truncate_for_llm(text, PAGE_EXTRACTION_TEXT_LIMIT)
        prompt = {
            "url": url,
            "title": title,
            "context": context,
            "text": truncated_text,
        }
        started_at = monotonic()
        logger.info(
            "llm_extract_request_start",
            url=url,
            title=title,
            model=self._settings.openai_model,
            base_url=self._settings.openai_base_url,
            text_length=len(text),
            truncated_text_length=len(truncated_text),
            context_count=len(context),
        )
        try:
            response = await self._client.chat.completions.create(
                model=self._settings.openai_model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": self._prompts.page_extraction.strip()},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
            )
            content = response.choices[0].message.content or "{}"
            payload = json.loads(content)
            logger.info(
                "llm_extract_request_complete",
                url=url,
                elapsed_ms=_elapsed_ms(started_at),
                response_length=len(content),
                entity_count=len(payload.get("extracted_entities", [])),
                has_summary=bool(payload.get("summary")),
            )
        except asyncio.CancelledError:
            logger.warning(
                "llm_extract_request_cancelled",
                url=url,
                elapsed_ms=_elapsed_ms(started_at),
                model=self._settings.openai_model,
            )
            raise
        except json.JSONDecodeError:
            logger.warning(
                "llm_invalid_json",
                url=url,
                elapsed_ms=_elapsed_ms(started_at),
                response_length=len(content),
                payload=content,
            )
            return self._fallback_extract(title=title, text=text)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "llm_request_failed",
                url=url,
                elapsed_ms=_elapsed_ms(started_at),
                model=self._settings.openai_model,
                error=str(exc),
            )
            return self._fallback_extract(title=title, text=text)
        entities = [
            ExtractedEntity.model_validate(entity)
            for entity in payload.get("extracted_entities", [])
        ]
        summary = payload.get("summary") or (title or text[:200])
        return summary, entities

    async def merge_entity(
        self,
        *,
        incoming_entity: ExtractedEntity,
        existing_entities: list[dict[str, Any]],
    ) -> ExtractedEntity:
        if not existing_entities:
            return incoming_entity
        if not self.enabled:
            return self._fallback_merge_entity(
                incoming_entity=incoming_entity,
                existing_entities=existing_entities,
            )

        prompt = {
            "incoming_entity": incoming_entity.model_dump(),
            "existing_entities": existing_entities,
        }
        try:
            response = await self._client.chat.completions.create(
                model=self._settings.openai_model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": self._prompts.entity_merge.strip()},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
            )
            content = response.choices[0].message.content or "{}"
            payload = json.loads(content)
            return ExtractedEntity.model_validate(payload)
        except json.JSONDecodeError:
            logger.warning("llm_merge_invalid_json", payload=content)
        except Exception as exc:  # noqa: BLE001
            logger.warning("llm_merge_failed", error=str(exc))
        return self._fallback_merge_entity(
            incoming_entity=incoming_entity,
            existing_entities=existing_entities,
        )

    async def filter_related_urls(
        self,
        *,
        source_url: str,
        title: str | None,
        text: str,
        context: list[dict[str, Any]],
        candidate_urls: list[str],
        candidate_url_entity_context: list[dict[str, Any]] | None = None,
    ) -> list[str]:
        normalized_candidates = _normalize_candidate_urls(candidate_urls)
        if not normalized_candidates:
            return []
        normalized_candidate_context = _normalize_candidate_url_entity_context(
            candidate_url_entity_context or []
        )
        if not self.enabled:
            logger.info(
                "llm_related_urls_fallback_disabled",
                source_url=source_url,
                candidate_url_count=len(normalized_candidates),
                context_count=len(context),
            )
            return self._fallback_filter_related_urls(
                source_url=source_url,
                title=title,
                text=text,
                context=context,
                candidate_urls=normalized_candidates,
                candidate_url_entity_context=normalized_candidate_context,
            )

        selected_urls: list[str] = []
        batches = _batched(normalized_candidates, size=RELATED_URL_BATCH_SIZE)
        logger.info(
            "llm_related_urls_start",
            source_url=source_url,
            title=title,
            model=self._settings.openai_model,
            base_url=self._settings.openai_base_url,
            candidate_url_count=len(normalized_candidates),
            batch_count=len(batches),
            context_count=len(context),
            candidate_url_entity_context_count=len(normalized_candidate_context),
        )
        for batch_index, batch in enumerate(batches, start=1):
            truncated_text = _truncate_for_llm(text, RELATED_URL_TEXT_LIMIT)
            prompt = {
                "source_url": source_url,
                "title": title,
                "context": context,
                "text_excerpt": truncated_text,
                "candidate_urls": batch,
                "candidate_url_entity_context": _compact_candidate_url_entity_context(
                    batch,
                    normalized_candidate_context,
                ),
            }
            started_at = monotonic()
            logger.info(
                "llm_related_urls_batch_start",
                source_url=source_url,
                batch_index=batch_index,
                batch_count=len(batches),
                batch_size=len(batch),
                truncated_text_length=len(truncated_text),
            )
            try:
                response = await self._client.chat.completions.create(
                    model=self._settings.openai_model,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": self._prompts.related_url_filter.strip()},
                        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                    ],
                )
                content = response.choices[0].message.content or "{}"
                payload = json.loads(content)
                batch_set = {item.casefold() for item in batch}
                batch_selected_urls = [
                    url.strip()
                    for url in payload.get("selected_urls", [])
                    if isinstance(url, str) and url.strip() and url.strip().casefold() in batch_set
                ]
                selected_urls.extend(batch_selected_urls)
                logger.info(
                    "llm_related_urls_batch_complete",
                    source_url=source_url,
                    batch_index=batch_index,
                    batch_count=len(batches),
                    elapsed_ms=_elapsed_ms(started_at),
                    response_length=len(content),
                    selected_url_count=len(batch_selected_urls),
                )
            except asyncio.CancelledError:
                logger.warning(
                    "llm_related_urls_batch_cancelled",
                    source_url=source_url,
                    batch_index=batch_index,
                    batch_count=len(batches),
                    elapsed_ms=_elapsed_ms(started_at),
                    batch_size=len(batch),
                )
                raise
            except json.JSONDecodeError:
                logger.warning(
                    "llm_related_urls_invalid_json",
                    source_url=source_url,
                    batch_index=batch_index,
                    batch_count=len(batches),
                    elapsed_ms=_elapsed_ms(started_at),
                    response_length=len(content),
                    payload=content,
                )
                selected_urls.extend(
                    self._fallback_filter_related_urls(
                        source_url=source_url,
                        title=title,
                        text=text,
                        context=context,
                        candidate_urls=batch,
                        candidate_url_entity_context=normalized_candidate_context,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "llm_related_urls_failed",
                    source_url=source_url,
                    batch_index=batch_index,
                    batch_count=len(batches),
                    elapsed_ms=_elapsed_ms(started_at),
                    batch_size=len(batch),
                    error=str(exc),
                )
                selected_urls.extend(
                    self._fallback_filter_related_urls(
                        source_url=source_url,
                        title=title,
                        text=text,
                        context=context,
                        candidate_urls=batch,
                        candidate_url_entity_context=normalized_candidate_context,
                    )
                )

        normalized_selected_urls = _normalize_candidate_urls(selected_urls)
        logger.info(
            "llm_related_urls_complete",
            source_url=source_url,
            candidate_url_count=len(normalized_candidates),
            selected_url_count=len(normalized_selected_urls),
        )
        return normalized_selected_urls

    def _fallback_extract(self, *, title: str | None, text: str) -> tuple[str, list[ExtractedEntity]]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        summary = "\n".join(lines[:3])[:400] if lines else (title or "未提取到正文内容")
        entities: list[ExtractedEntity] = []
        if title:
            entities.append(
                ExtractedEntity(
                    name=title,
                    category="page_subject",
                    summary=summary[:300],
                    aliases=[],
                    relations=[],
                )
            )
        return summary, entities

    def _fallback_filter_related_urls(
        self,
        *,
        source_url: str,
        title: str | None,
        text: str,
        context: list[dict[str, Any]],
        candidate_urls: list[str],
        candidate_url_entity_context: list[dict[str, Any]] | None = None,
    ) -> list[str]:
        ranking_keywords = _build_ranking_keywords(
            source_url=source_url,
            title=title,
            text=text,
            context=context,
        )
        candidate_entity_context_map = _build_candidate_entity_context_map(
            candidate_url_entity_context or []
        )
        source_host = urlsplit(source_url).netloc.casefold()
        scored_candidates: list[tuple[int, int, str]] = []

        for index, url in enumerate(candidate_urls):
            parsed = urlsplit(url)
            path = parsed.path.casefold()
            segments = [segment for segment in path.split("/") if segment]
            query = {
                key.casefold(): value.casefold()
                for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            }

            if any(path.endswith(ext) for ext in _STATIC_RESOURCE_EXTENSIONS):
                continue
            if query.get("action") in {"edit", "history", "submit"}:
                continue
            if any(segment in _LOW_VALUE_PATH_SEGMENTS for segment in segments):
                continue
            if any(segment.startswith(prefix) for prefix in _LOW_VALUE_SEGMENT_PREFIXES for segment in segments):
                continue

            entity_context = candidate_entity_context_map.get(url.casefold())
            if entity_context and _should_skip_candidate_due_to_existing_entity(url, entity_context):
                continue

            decoded_url = _decode_url_for_matching(url)
            score = 0
            if parsed.netloc.casefold() == source_host:
                score += 2
            if any(keyword in decoded_url for keyword in ranking_keywords):
                score += 4
            if any(hint in decoded_url for hint in _HIGH_VALUE_URL_HINTS):
                score += 1
            if entity_context:
                score -= _existing_entity_penalty(entity_context)
                if _looks_like_fresh_fact_url(url):
                    score += 2

            scored_candidates.append((score, index, url))

        scored_candidates.sort(key=lambda item: (-item[0], item[1]))
        return [url for _, _, url in scored_candidates]

    def _fallback_merge_entity(
        self,
        *,
        incoming_entity: ExtractedEntity,
        existing_entities: list[dict[str, Any]],
    ) -> ExtractedEntity:
        aliases: list[str] = []
        summaries = [incoming_entity.summary]
        categories = [incoming_entity.category]
        relations = incoming_entity.relations.copy()
        deleted_relations = incoming_entity.deleted_relations.copy()

        for entity in existing_entities:
            summaries.append(entity.get("summary", ""))
            categories.append(entity.get("category", "unknown"))
            aliases.extend(entity.get("aliases", []))
            existing_name = entity.get("name")
            if existing_name:
                aliases.append(existing_name)
            relations.extend(entity.get("outgoing_relations", []))

        merged_name = incoming_entity.name.strip() or next(
            (entity.get("name", "").strip() for entity in existing_entities if entity.get("name", "").strip()),
            incoming_entity.name,
        )
        merged_category = next(
            (
                category
                for category in categories
                if isinstance(category, str) and category.strip() and category.lower() != "unknown"
            ),
            "unknown",
        )
        merged_summary = max(
            (summary.strip() for summary in summaries if isinstance(summary, str) and summary.strip()),
            key=len,
            default=incoming_entity.summary,
        )
        merged_aliases = _dedupe_strings([*incoming_entity.aliases, *aliases], exclude=merged_name)
        merged_deleted_relations = _dedupe_deleted_relations(deleted_relations)
        merged_relations = _filter_deleted_relations(
            _dedupe_relations(relations),
            merged_deleted_relations,
        )

        return ExtractedEntity(
            name=merged_name,
            category=merged_category,
            summary=merged_summary,
            aliases=merged_aliases,
            relations=merged_relations,
            deleted_relations=merged_deleted_relations,
        )


def _dedupe_strings(values: list[str], *, exclude: str | None = None) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()
    excluded = exclude.strip().casefold() if exclude and exclude.strip() else None
    for value in values:
        if not isinstance(value, str):
            continue
        cleaned = " ".join(value.split()).strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key == excluded or key in seen:
            continue
        seen.add(key)
        results.append(cleaned)
    return results


def _dedupe_relations(relations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for relation in relations:
        relation_type = str(relation.get("type", "RELATED_TO")).strip() or "RELATED_TO"
        target = str(relation.get("target", "")).strip()
        if not target:
            continue
        evidence = str(relation.get("evidence", "")).strip()
        key = (relation_type.casefold(), target.casefold())
        current = merged.get(key)
        candidate = {
            "type": relation_type,
            "target": target,
            "evidence": evidence,
        }
        if current is None or len(candidate["evidence"]) > len(str(current.get("evidence", ""))):
            merged[key] = candidate
    return list(merged.values())


def _dedupe_deleted_relations(relations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for relation in relations:
        relation_type = str(relation.get("type", "RELATED_TO")).strip() or "RELATED_TO"
        target = str(relation.get("target", "")).strip()
        if not target:
            continue
        evidence = str(relation.get("evidence", "")).strip()
        reason = str(relation.get("reason", "")).strip()
        key = (relation_type.casefold(), target.casefold())
        candidate = {
            "type": relation_type,
            "target": target,
        }
        if evidence:
            candidate["evidence"] = evidence
        if reason:
            candidate["reason"] = reason
        current = merged.get(key)
        current_score = len(str(current.get("evidence", ""))) + len(str(current.get("reason", ""))) if current else -1
        candidate_score = len(evidence) + len(reason)
        if current is None or candidate_score > current_score:
            merged[key] = candidate
    return list(merged.values())


def _filter_deleted_relations(
    relations: list[dict[str, Any]],
    deleted_relations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    deleted_keys = {
        (
            str(relation.get("type", "RELATED_TO")).strip().casefold() or "related_to",
            str(relation.get("target", "")).strip().casefold(),
        )
        for relation in deleted_relations
        if str(relation.get("target", "")).strip()
    }
    return [
        relation
        for relation in relations
        if (
            str(relation.get("type", "RELATED_TO")).strip().casefold() or "related_to",
            str(relation.get("target", "")).strip().casefold(),
        )
        not in deleted_keys
    ]


_STATIC_RESOURCE_EXTENSIONS = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".css",
    ".js",
    ".json",
    ".xml",
    ".pdf",
    ".zip",
    ".rar",
    ".7z",
    ".ttf",
    ".otf",
    ".woff",
    ".woff2",
    ".mp3",
    ".wav",
    ".ogg",
    ".mp4",
    ".webm",
)

_LOW_VALUE_PATH_SEGMENTS = {
    "login",
    "logout",
    "signup",
    "register",
    "search",
    "comment",
    "comments",
    "user",
    "users",
    "profile",
    "profiles",
    "privacy",
    "terms",
    "tag",
    "tags",
    "category",
    "categories",
    "archive",
    "archives",
}

_LOW_VALUE_SEGMENT_PREFIXES = (
    "special:",
    "template:",
    "file:",
    "image:",
    "help:",
    "talk:",
    "user:",
    "category:",
)

_HIGH_VALUE_URL_HINTS = (
    "wiki",
    "character",
    "resonator",
    "weapon",
    "echo",
    "quest",
    "story",
    "guide",
    "tutorial",
    "version",
    "event",
    "news",
)


def _build_ranking_keywords(
    *,
    source_url: str,
    title: str | None,
    text: str,
    context: list[dict[str, Any]],
) -> list[str]:
    keywords: list[str] = []
    if title:
        keywords.append(title)

    source_path = unquote(urlsplit(source_url).path)
    keywords.extend(part for part in re.split(r"[/_\-\s]+", source_path) if part)

    for match in context:
        if not isinstance(match, dict):
            continue
        for key in ("name", "normalized_name", "category", "summary"):
            value = match.get(key)
            if isinstance(value, str) and value.strip():
                keywords.append(value)
        aliases = match.get("aliases", [])
        if isinstance(aliases, list):
            keywords.extend(alias for alias in aliases if isinstance(alias, str) and alias.strip())

    keywords.extend(re.findall(r"[A-Za-z0-9][A-Za-z0-9:_-]{2,}|[\u4e00-\u9fff]{2,8}", text[:500]))
    return _dedupe_rank_keywords(keywords)


def _dedupe_rank_keywords(values: list[str]) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        cleaned = " ".join(value.split()).strip()
        if len(cleaned) < 2:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        results.append(key)
    return results


def _decode_url_for_matching(url: str) -> str:
    parsed = urlsplit(url)
    parts = [parsed.netloc, unquote(parsed.path), unquote(parsed.query)]
    return " ".join(part.casefold() for part in parts if part)


def _normalize_candidate_url_entity_context(
    contexts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for context in contexts:
        if not isinstance(context, dict):
            continue
        url = str(context.get("url") or "").strip()
        if not url:
            continue
        url_key = url.casefold()
        if url_key in seen_urls:
            continue
        best_match = context.get("best_match")
        if not isinstance(best_match, dict):
            matches = context.get("matches", [])
            best_match = matches[0] if isinstance(matches, list) and matches else {}
        if not isinstance(best_match, dict) or not best_match:
            continue
        normalized.append(
            {
                "url": url,
                "lookup_terms": [
                    term
                    for term in context.get("lookup_terms", [])
                    if isinstance(term, str) and term.strip()
                ],
                "best_match": {
                    "name": str(best_match.get("name") or "").strip(),
                    "category": str(best_match.get("category") or "unknown").strip() or "unknown",
                    "summary": str(best_match.get("summary") or "").strip(),
                    "aliases": [
                        alias
                        for alias in best_match.get("aliases", [])
                        if isinstance(alias, str) and alias.strip()
                    ],
                    "relation_count": int(best_match.get("relation_count") or 0),
                    "mentioned_in_count": int(best_match.get("mentioned_in_count") or 0),
                    "completeness_score": int(best_match.get("completeness_score") or 0),
                    "completeness_level": str(best_match.get("completeness_level") or "sparse").strip()
                    or "sparse",
                    "matched_term": str(best_match.get("matched_term") or "").strip(),
                },
            }
        )
        seen_urls.add(url_key)
    return normalized


def _compact_candidate_url_entity_context(
    candidate_urls: list[str],
    contexts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidate_set = {url.casefold() for url in candidate_urls}
    compact: list[dict[str, Any]] = []
    for context in contexts:
        url = str(context.get("url") or "").strip()
        if not url or url.casefold() not in candidate_set:
            continue
        best_match = context.get("best_match", {})
        compact.append(
            {
                "url": url,
                "lookup_terms": context.get("lookup_terms", [])[:2],
                "best_match": {
                    "name": best_match.get("name"),
                    "category": best_match.get("category"),
                    "summary": _truncate_for_llm(
                        str(best_match.get("summary") or ""),
                        RELATED_URL_ENTITY_SUMMARY_LIMIT,
                    ),
                    "aliases": list(best_match.get("aliases", []))[:4],
                    "relation_count": int(best_match.get("relation_count") or 0),
                    "mentioned_in_count": int(best_match.get("mentioned_in_count") or 0),
                    "completeness_score": int(best_match.get("completeness_score") or 0),
                    "completeness_level": best_match.get("completeness_level", "sparse"),
                },
            }
        )
    return compact


def _build_candidate_entity_context_map(contexts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(context.get("url")).strip().casefold(): context
        for context in contexts
        if isinstance(context, dict) and str(context.get("url") or "").strip()
    }


def _existing_entity_penalty(context: dict[str, Any]) -> int:
    best_match = context.get("best_match", {})
    completeness_level = str(best_match.get("completeness_level") or "sparse").casefold()
    if completeness_level == "complete":
        return 6
    if completeness_level == "substantial":
        return 3
    return 1 if int(best_match.get("relation_count") or 0) >= 2 else 0


def _should_skip_candidate_due_to_existing_entity(url: str, context: dict[str, Any]) -> bool:
    best_match = context.get("best_match", {})
    completeness_level = str(best_match.get("completeness_level") or "sparse").casefold()
    if completeness_level != "complete":
        return False
    if _looks_like_fresh_fact_url(url):
        return False
    return _looks_like_entity_detail_url(url)


def _looks_like_entity_detail_url(url: str) -> bool:
    parsed = urlsplit(url)
    segments = [segment for segment in unquote(parsed.path).casefold().split("/") if segment]
    if not segments:
        return False
    last_segment = segments[-1]
    if any(last_segment.endswith(ext) for ext in _STATIC_RESOURCE_EXTENSIONS):
        return False
    if last_segment in _ENTITY_DETAIL_GENERIC_SEGMENTS or len(last_segment) < 2:
        return False
    if any(segment in _ENTITY_DETAIL_PATH_HINTS for segment in segments[:-1]):
        return True
    return len(segments) <= 2 and not _looks_like_fresh_fact_url(url)


def _looks_like_fresh_fact_url(url: str) -> bool:
    decoded = _decode_url_for_matching(url)
    return any(hint in decoded for hint in _FRESH_FACT_URL_HINTS)


def _normalize_candidate_urls(urls: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if not isinstance(url, str):
            continue
        cleaned = url.strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(cleaned)
    return normalized


def _batched(values: list[str], *, size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


PAGE_EXTRACTION_TEXT_LIMIT = 50000
RELATED_URL_TEXT_LIMIT = 4000
RELATED_URL_BATCH_SIZE = 80
RELATED_URL_ENTITY_SUMMARY_LIMIT = 240

_ENTITY_DETAIL_PATH_HINTS = {
    "wiki",
    "character",
    "characters",
    "resonator",
    "resonators",
    "weapon",
    "weapons",
    "echo",
    "echoes",
    "npc",
    "monster",
    "boss",
    "location",
    "locations",
    "area",
    "areas",
    "faction",
    "factions",
}

_ENTITY_DETAIL_GENERIC_SEGMENTS = {
    "wiki",
    "index",
    "index.php",
    "page",
    "entry",
    "detail",
    "details",
    "character",
    "characters",
    "resonator",
    "resonators",
    "weapon",
    "weapons",
    "echo",
    "echoes",
}

_FRESH_FACT_URL_HINTS = (
    "news",
    "notice",
    "announcement",
    "update",
    "patch",
    "version",
    "event",
    "activity",
    "preview",
    "release",
)


def _truncate_for_llm(text: str, limit: int) -> str:
    return text[:limit]


def _elapsed_ms(started_at: float) -> int:
    return int((monotonic() - started_at) * 1000)
