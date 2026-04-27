from __future__ import annotations

import asyncio
import inspect
import json
from time import monotonic
from typing import Any

from openai import AsyncOpenAI

from app.core.config import Settings
from app.core.logging import get_logger
from app.models import ExtractedEntity
from app.services.llm.prompts import (
    DEFAULT_PROMPT_BUNDLE,
    build_entity_merge_prompt,
)

logger = get_logger(__name__)


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.enabled = bool(settings.openai_api_key)
        self._client = (
            AsyncOpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
            )
            if self.enabled
            else None
        )
        self._merge_chain = self._build_merge_chain() if self.enabled else None

    async def extract_knowledge(
        self,
        *,
        url: str,
        title: str | None,
        text: str,
        context: list[dict[str, Any]],
        knowledge_theme: str | None = None,
    ) -> tuple[str, list[ExtractedEntity]]:
        client = self._require_client()
        truncated_text = _truncate_for_llm(text, PAGE_EXTRACTION_TEXT_LIMIT)
        prompt = {
            "knowledge_theme": (knowledge_theme or "").strip(),
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
            response = await client.chat.completions.create(
                model=self._settings.openai_model,
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": DEFAULT_PROMPT_BUNDLE.page_extraction.strip(),
                    },
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
        except json.JSONDecodeError as exc:
            logger.warning(
                "llm_invalid_json",
                url=url,
                elapsed_ms=_elapsed_ms(started_at),
                response_length=len(content),
                payload=content,
            )
            raise ValueError("LLM returned invalid JSON for extract_knowledge") from exc
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "llm_request_failed",
                url=url,
                elapsed_ms=_elapsed_ms(started_at),
                model=self._settings.openai_model,
                error=str(exc),
            )
            raise
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

        prompt = {
            "incoming_entity": incoming_entity.model_dump(),
            "existing_entities": existing_entities,
        }
        try:
            result = await self._require_merge_chain().ainvoke(
                {"payload": json.dumps(prompt, ensure_ascii=False)}
            )
            return ExtractedEntity.model_validate(result)
        except ValueError as exc:
            logger.warning("llm_merge_invalid_output", error=str(exc))
            raise ValueError("LLM returned invalid structured output for merge_entity") from exc
        except Exception as exc:  # noqa: BLE001
            logger.warning("llm_merge_failed", error=str(exc))
            raise

    async def filter_related_urls(
        self,
        *,
        source_url: str,
        title: str | None,
        text: str,
        context: list[dict[str, Any]],
        candidate_urls: list[str],
        candidate_url_entity_context: list[dict[str, Any]] | None = None,
        knowledge_theme: str | None = None,
    ) -> list[str]:
        normalized_candidates = _normalize_candidate_urls(candidate_urls)
        if not normalized_candidates:
            return []
        client = self._require_client()
        normalized_candidate_context = _normalize_candidate_url_entity_context(
            candidate_url_entity_context or []
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
                "knowledge_theme": (knowledge_theme or "").strip(),
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
                response = await client.chat.completions.create(
                    model=self._settings.openai_model,
                    response_format={"type": "json_object"},
                    messages=[
                        {
                            "role": "system",
                            "content": DEFAULT_PROMPT_BUNDLE.related_url_filter.strip(),
                        },
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
            except json.JSONDecodeError as exc:
                logger.warning(
                    "llm_related_urls_invalid_json",
                    source_url=source_url,
                    batch_index=batch_index,
                    batch_count=len(batches),
                    elapsed_ms=_elapsed_ms(started_at),
                    response_length=len(content),
                    payload=content,
                )
                raise ValueError("LLM returned invalid JSON for filter_related_urls") from exc
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
                raise

        normalized_selected_urls = _normalize_candidate_urls(selected_urls)
        logger.info(
            "llm_related_urls_complete",
            source_url=source_url,
            candidate_url_count=len(normalized_candidates),
            selected_url_count=len(normalized_selected_urls),
        )
        return normalized_selected_urls

    async def check_health(self) -> tuple[bool, str | None]:
        if not self.enabled:
            return False, None
        client = self._require_client()
        try:
            await client.models.list()
            return True, None
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

    async def close(self) -> None:
        client = self._client
        self._client = None
        self._merge_chain = None
        if client is not None:
            await _close_async_resource(client)

    def _require_client(self) -> AsyncOpenAI:
        if self._client is None:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        return self._client

    def _build_merge_chain(self):
        from langchain_openai import ChatOpenAI

        prompt = build_entity_merge_prompt()
        llm = ChatOpenAI(
            model=self._settings.openai_model,
            api_key=self._settings.openai_api_key,
            base_url=self._settings.openai_base_url,
            temperature=0,
        )
        return prompt | llm.with_structured_output(ExtractedEntity, method="json_mode")

    def _require_merge_chain(self):
        if self._merge_chain is None:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        return self._merge_chain


async def _close_async_resource(resource: Any) -> None:
    for method_name in ("close", "aclose"):
        method = getattr(resource, method_name, None)
        if not callable(method):
            continue
        result = method()
        if inspect.isawaitable(result):
            await result
        return

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


def _truncate_for_llm(text: str, limit: int) -> str:
    return text[:limit]


def _elapsed_ms(started_at: float) -> int:
    return int((monotonic() - started_at) * 1000)
