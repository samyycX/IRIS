from __future__ import annotations

import hashlib
from collections.abc import Iterable

from app.models.indexing import EmbeddingSourceType


def build_embedding_key(source_type: EmbeddingSourceType, source_key: str) -> str:
    return f"{source_type.value}:{source_key.strip()}"


def build_relation_pair_key(left_entity_id: str, right_entity_id: str) -> str:
    left = _clean_text(left_entity_id)
    right = _clean_text(right_entity_id)
    ordered = sorted([left, right])
    return f"{ordered[0]}::{ordered[1]}"


def parse_relation_pair_key(pair_key: str) -> tuple[str, str]:
    left, right = pair_key.split("::", maxsplit=1)
    return left, right


def build_source_embedding_text(summary: str | None) -> str:
    return _clean_text(summary or "")


def build_entity_embedding_text(
    *,
    name: str,
    category: str | None,
    summary: str | None,
    aliases: Iterable[str],
    outgoing_relations: Iterable[dict[str, str | None]],
    incoming_relations: Iterable[dict[str, str | None]],
    mentioned_in_sources: Iterable[str],
    text_max_chars: int,
) -> str:
    alias_text = _join_items(aliases)
    outgoing_text = _join_relation_lines(outgoing_relations, direction="outgoing")
    incoming_text = _join_relation_lines(incoming_relations, direction="incoming")
    source_text = _join_items(mentioned_in_sources)
    parts = [
        f"名称：{_clean_text(name)}",
        f"类别：{_clean_text(category or 'unknown')}",
        f"摘要：{_clean_text(summary or '')}",
        f"别名：{alias_text}",
        f"出边关系：{outgoing_text}",
        f"入边关系：{incoming_text}",
        f"提及来源：{source_text}",
    ]
    return _truncate_text("\n".join(parts), max_chars=text_max_chars)


def compute_embedding_content_hash(*, version: str, text: str) -> str:
    payload = f"{version}\n{text}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_relation_embedding_text(
    *,
    left_entity_id: str,
    left_entity_name: str,
    right_entity_id: str,
    right_entity_name: str,
    relations: Iterable[dict[str, str | None]],
    text_max_chars: int,
) -> str:
    lines = [
        f"实体A：{_clean_text(left_entity_name)}（{_clean_text(left_entity_id)}）",
        f"实体B：{_clean_text(right_entity_name)}（{_clean_text(right_entity_id)}）",
        f"关系汇总：{_join_relation_bundle(relations)}",
    ]
    return _truncate_text("\n".join(lines), max_chars=text_max_chars)


def _join_items(values: Iterable[str]) -> str:
    cleaned = [_clean_text(value) for value in values if _clean_text(value)]
    return "；".join(cleaned) if cleaned else "无"


def _join_relation_lines(
    relations: Iterable[dict[str, str | None]],
    *,
    direction: str,
) -> str:
    lines: list[str] = []
    for relation in relations:
        relation_type = _clean_text(str(relation.get("type") or "RELATED_TO"))
        counterpart = _clean_text(
            str(relation.get("target") or relation.get("source") or relation.get("name") or "")
        )
        evidence = _clean_text(str(relation.get("evidence") or ""))
        if not counterpart:
            continue
        prefix = "指向" if direction == "outgoing" else "来自"
        line = f"{prefix}{counterpart}（{relation_type}）"
        if evidence:
            line += f" 证据：{evidence}"
        lines.append(line)
    return "；".join(lines) if lines else "无"


def _join_relation_bundle(relations: Iterable[dict[str, str | None]]) -> str:
    lines: list[str] = []
    for relation in relations:
        source = _clean_text(str(relation.get("source_name") or relation.get("source") or ""))
        target = _clean_text(str(relation.get("target_name") or relation.get("target") or ""))
        relation_type = _clean_text(str(relation.get("type") or "RELATED_TO"))
        evidence = _clean_text(str(relation.get("evidence") or ""))
        if not source or not target:
            continue
        line = f"{source} -> {target}（{relation_type}）"
        if evidence:
            line += f" 证据：{evidence}"
        lines.append(line)
    return "；".join(lines) if lines else "无"


def _truncate_text(text: str, *, max_chars: int) -> str:
    cleaned = _clean_text(text)
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[:max_chars]


def _clean_text(value: str) -> str:
    return " ".join(value.split()).strip()
