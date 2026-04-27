from __future__ import annotations

from typing import Any

from app.core.i18n import get_current_ui_language
from app.models.config import UiLanguage
from app.models.jobs import GraphUpdateResult, JobInputType, JobStatus, JobSummary, PageExtraction


def build_job_summary_text(job: JobSummary) -> str:
    if _language() == UiLanguage.zh:
        parts = [
            f"任务状态：{_job_status_label(job.status)}",
            f"输入类型：{_job_input_type_label(job.input_type)}",
            f"种子：{job.seed}",
            f"访问页面：{job.visited_count}",
            f"队列长度：{job.queued_count}",
            f"失败数：{job.failed_count}",
            f"抓取限制：深度 {job.max_depth} / 页面 {job.max_pages}",
        ]
        if job.graph_update is not None:
            parts.append(build_graph_update_summary(job.graph_update))
        if job.last_error:
            parts.append(f"最近错误：{job.last_error}")
        if job.completed_at:
            parts.append(f"完成时间：{job.completed_at.isoformat()}")
        return "；".join(parts)

    parts = [
        f"Status: {_job_status_label(job.status)}",
        f"Input type: {_job_input_type_label(job.input_type)}",
        f"Seed: {job.seed}",
        f"Visited pages: {job.visited_count}",
        f"Queue length: {job.queued_count}",
        f"Failed count: {job.failed_count}",
        f"Crawl limits: depth {job.max_depth} / pages {job.max_pages}",
    ]
    if job.graph_update is not None:
        parts.append(build_graph_update_summary(job.graph_update))
    if job.last_error:
        parts.append(f"Latest error: {job.last_error}")
    if job.completed_at:
        parts.append(f"Completed at: {job.completed_at.isoformat()}")
    return "; ".join(parts)


def build_job_change_log_text(job: JobSummary) -> str:
    if _language() == UiLanguage.zh:
        lines = [
            "任务概览",
            f"- 状态：{_job_status_label(job.status)}",
            f"- 输入类型：{_job_input_type_label(job.input_type)}",
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
                    f"- 新增来源（{len(job.graph_update.created_sources)}）：{format_string_list(job.graph_update.created_sources)}",
                    f"- 新增实体（{len(job.graph_update.created_entities)}）：{format_string_list(job.graph_update.created_entities)}",
                    f"- 更新实体（{len(job.graph_update.updated_entities)}）：{format_string_list(job.graph_update.updated_entities)}",
                    f"- 新增关系：{job.graph_update.created_relationships}",
                    f"- 删除关系：{job.graph_update.deleted_relationships}",
                ]
            )
        if job.last_error:
            lines.extend(["", "错误信息", f"- {job.last_error}"])
        return "\n".join(lines)

    lines = [
        "Job Overview",
        f"- Status: {_job_status_label(job.status)}",
        f"- Input type: {_job_input_type_label(job.input_type)}",
        f"- Seed: {job.seed}",
        f"- Created at: {job.created_at.isoformat()}",
        f"- Updated at: {job.updated_at.isoformat()}",
        f"- Completed at: {job.completed_at.isoformat() if job.completed_at else 'Not completed'}",
        f"- Crawl limits: max depth {job.max_depth}, max pages {job.max_pages}",
        f"- Execution stats: visited {job.visited_count}, queued {job.queued_count}, failed {job.failed_count}",
    ]
    if job.graph_update is not None:
        lines.extend(
            [
                "",
                "Change Log",
                f"- Created sources ({len(job.graph_update.created_sources)}): {format_string_list(job.graph_update.created_sources)}",
                f"- Created entities ({len(job.graph_update.created_entities)}): {format_string_list(job.graph_update.created_entities)}",
                f"- Updated entities ({len(job.graph_update.updated_entities)}): {format_string_list(job.graph_update.updated_entities)}",
                f"- Created relationships: {job.graph_update.created_relationships}",
                f"- Deleted relationships: {job.graph_update.deleted_relationships}",
            ]
        )
    if job.last_error:
        lines.extend(["", "Error", f"- {job.last_error}"])
    return "\n".join(lines)


def build_graph_update_summary(update: GraphUpdateResult) -> str:
    if _language() == UiLanguage.zh:
        return (
            "图谱变更："
            f"新增来源 {len(update.created_sources)} 个，"
            f"新增实体 {len(update.created_entities)} 个，"
            f"更新实体 {len(update.updated_entities)} 个，"
            f"新增关系 {update.created_relationships} 条，"
            f"删除关系 {update.deleted_relationships} 条"
        )
    return (
        "Graph update: "
        f"created sources {len(update.created_sources)}, "
        f"created entities {len(update.created_entities)}, "
        f"updated entities {len(update.updated_entities)}, "
        f"created relationships {update.created_relationships}, "
        f"deleted relationships {update.deleted_relationships}"
    )


def build_source_modification_summary(
    *,
    extraction: PageExtraction,
    source_created: bool,
    source_update: dict[str, Any],
) -> str:
    if _language() == UiLanguage.zh:
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

    parts = [
        f"Source: {extraction.canonical_url}",
        "Source state: created" if source_created else "Source state: updated",
        f"Source summary length: {len(extraction.summary)}",
        f"Extracted entities: {len(extraction.extracted_entities)}",
        f"Discovered links: {len(extraction.discovered_urls)}",
        f"Created entities: {len(source_update.get('created_entities', []))}",
        f"Updated entities: {len(source_update.get('updated_entities', []))}",
        f"Created relationships: {source_update.get('created_relationships', 0)}",
        f"Deleted relationships: {source_update.get('deleted_relationships', 0)}",
    ]
    return "; ".join(parts)


def build_source_change_log(
    *,
    extraction: PageExtraction,
    source_created: bool,
    source_update: dict[str, Any],
) -> str:
    if _language() == UiLanguage.zh:
        lines = [
            "来源修改详情",
            f"- 来源 URL：{extraction.canonical_url}",
            f"- 来源标题：{extraction.title or '无标题'}",
            f"- 来源状态：{'新增来源' if source_created else '更新已有来源'}",
            f"- 来源摘要：{extraction.summary or '无摘要'}",
            f"- 抽取实体数：{len(extraction.extracted_entities)}",
            f"- 发现链接数：{len(extraction.discovered_urls)}",
            f"- 新增实体（{len(source_update.get('created_entities', []))}）：{format_string_list(source_update.get('created_entities', []))}",
            f"- 更新实体（{len(source_update.get('updated_entities', []))}）：{format_string_list(source_update.get('updated_entities', []))}",
            f"- 新增来源引用（{len(source_update.get('created_sources', []))}）：{format_string_list(source_update.get('created_sources', []))}",
            f"- 新增关系：{source_update.get('created_relationships', 0)}",
            f"- 删除关系：{source_update.get('deleted_relationships', 0)}",
        ]
        return "\n".join(lines)

    lines = [
        "Source Modification Details",
        f"- Source URL: {extraction.canonical_url}",
        f"- Source title: {extraction.title or 'Untitled'}",
        f"- Source state: {'Created' if source_created else 'Updated'}",
        f"- Source summary: {extraction.summary or 'No summary'}",
        f"- Extracted entities: {len(extraction.extracted_entities)}",
        f"- Discovered links: {len(extraction.discovered_urls)}",
        f"- Created entities ({len(source_update.get('created_entities', []))}): {format_string_list(source_update.get('created_entities', []))}",
        f"- Updated entities ({len(source_update.get('updated_entities', []))}): {format_string_list(source_update.get('updated_entities', []))}",
        f"- Created source refs ({len(source_update.get('created_sources', []))}): {format_string_list(source_update.get('created_sources', []))}",
        f"- Created relationships: {source_update.get('created_relationships', 0)}",
        f"- Deleted relationships: {source_update.get('deleted_relationships', 0)}",
    ]
    return "\n".join(lines)


def format_string_list(values: list[str], limit: int = 20) -> str:
    cleaned = [value for value in values if isinstance(value, str) and value.strip()]
    if not cleaned:
        return "无" if _language() == UiLanguage.zh else "None"
    separator = "、" if _language() == UiLanguage.zh else ", "
    if len(cleaned) <= limit:
        return separator.join(cleaned)
    remaining = len(cleaned) - limit
    head = separator.join(cleaned[:limit])
    if _language() == UiLanguage.zh:
        return f"{head} 等 {len(cleaned)} 项（其余 {remaining} 项省略）"
    return f"{head}, and {remaining} more ({len(cleaned)} total)"


def _language() -> UiLanguage:
    return get_current_ui_language()


def _job_status_label(status: JobStatus) -> str:
    labels = {
        UiLanguage.zh: {
            JobStatus.queued: "等待中",
            JobStatus.running: "运行中",
            JobStatus.paused: "已暂停",
            JobStatus.completed: "已完成",
            JobStatus.failed: "失败",
            JobStatus.cancelled: "已取消",
            JobStatus.interrupted: "已中断",
        },
        UiLanguage.en: {
            JobStatus.queued: "Queued",
            JobStatus.running: "Running",
            JobStatus.paused: "Paused",
            JobStatus.completed: "Completed",
            JobStatus.failed: "Failed",
            JobStatus.cancelled: "Cancelled",
            JobStatus.interrupted: "Interrupted",
        },
    }
    return labels[_language()][status]


def _job_input_type_label(input_type: JobInputType) -> str:
    labels = {
        UiLanguage.zh: {
            JobInputType.url: "URL",
            JobInputType.instruction: "自由文本指令",
            JobInputType.entity: "实体名称",
        },
        UiLanguage.en: {
            JobInputType.url: "URL",
            JobInputType.instruction: "Instruction",
            JobInputType.entity: "Entity",
        },
    }
    return labels[_language()][input_type]