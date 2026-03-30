from __future__ import annotations

from typing import Any

from app.services.graphrag.models import GraphRAGContext, GraphRAGContextDocument


def build_context_documents(context: GraphRAGContext) -> list[GraphRAGContextDocument]:
    documents: list[GraphRAGContextDocument] = []

    for entity in context.entities:
        title = str(entity.get("name") or entity.get("entity_id") or "Entity")
        summary = str(entity.get("summary") or "").strip()
        aliases = "；".join(entity.get("aliases", [])) or "无"
        documents.append(
            GraphRAGContextDocument(
                kind="entity",
                title=title,
                content="\n".join(
                    [
                        f"实体：{title}",
                        f"类别：{entity.get('category') or 'unknown'}",
                        f"摘要：{summary or '无'}",
                        f"别名：{aliases}",
                        f"关系数量：{entity.get('relation_count') or 0}",
                        f"来源数量：{entity.get('mentioned_in_count') or 0}",
                    ]
                ),
                metadata={
                    "entity_id": entity.get("entity_id"),
                    "vector_score": entity.get("vector_score"),
                    "completeness_level": entity.get("completeness_level"),
                },
            )
        )

    for source in context.sources:
        title = str(source.get("title") or source.get("source_key") or "Source")
        documents.append(
            GraphRAGContextDocument(
                kind="source",
                title=title,
                content="\n".join(
                    [
                        f"来源：{title}",
                        f"URL：{source.get('source_key') or ''}",
                        f"摘要：{str(source.get('summary') or '').strip() or '无'}",
                    ]
                ),
                metadata={"score": source.get("score")},
            )
        )

    for relation in context.relations:
        left_name = str(relation.get("left_entity_name") or relation.get("left_entity_id") or "")
        right_name = str(relation.get("right_entity_name") or relation.get("right_entity_id") or "")
        documents.append(
            GraphRAGContextDocument(
                kind="relation",
                title=f"{left_name} <-> {right_name}",
                content=str(relation.get("aggregated_text") or "").strip() or "无关系文本",
                metadata={
                    "source_key": relation.get("source_key"),
                    "score": relation.get("score"),
                },
            )
        )

    for neighborhood in context.neighborhoods:
        seed_name = str(neighborhood.get("seed_name") or neighborhood.get("seed_entity_id") or "Entity")
        neighbor_lines = []
        for neighbor in neighborhood.get("neighbors", []):
            neighbor_name = str(neighbor.get("neighbor_name") or neighbor.get("neighbor_entity_id") or "")
            relation_path = " -> ".join(neighbor.get("relation_types", [])) or "RELATED_TO"
            evidence = str(neighbor.get("evidence") or "").strip()
            line = f"{neighbor_name} | 路径：{relation_path} | hop={neighbor.get('hop_count') or 1}"
            if evidence:
                line += f" | 证据：{evidence}"
            neighbor_lines.append(line)
        documents.append(
            GraphRAGContextDocument(
                kind="neighborhood",
                title=f"{seed_name} 邻域",
                content="\n".join(neighbor_lines) if neighbor_lines else "无扩展邻域",
                metadata={"seed_entity_id": neighborhood.get("seed_entity_id")},
            )
        )

    return documents


def build_prompt_context(context: GraphRAGContext) -> str:
    sections: list[str] = []

    for document in context.documents:
        sections.append(f"[{document.kind}] {document.title}\n{document.content}")

    if context.candidate_url_entity_context:
        lines = []
        for item in context.candidate_url_entity_context:
            best_match = item.get("best_match", {})
            lines.append(
                f"URL: {item.get('url')}\n"
                f"匹配实体: {best_match.get('name') or '无'}\n"
                f"完整度: {best_match.get('completeness_level') or 'unknown'}\n"
                f"摘要: {best_match.get('summary') or '无'}"
            )
        sections.append("[candidate_url_entity_context]\n" + "\n\n".join(lines))

    return "\n\n".join(sections).strip()


def build_preview_payload(context: GraphRAGContext) -> dict[str, Any]:
    return {
        "query": context.query,
        "entities": context.entities,
        "sources": context.sources,
        "relations": context.relations,
        "neighborhoods": context.neighborhoods,
        "documents": [document.model_dump(mode="json") for document in context.documents],
    }
