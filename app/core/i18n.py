from __future__ import annotations

from collections.abc import Mapping
from threading import Lock
from typing import Any

from app.models.config import UiLanguage

_current_ui_language = UiLanguage.zh
_language_lock = Lock()

_MESSAGE_CATALOG: dict[str, dict[UiLanguage, str]] = {
    "embedding_client_not_configured": {
        UiLanguage.zh: "Embedding 客户端未配置。",
        UiLanguage.en: "Embedding client is not configured.",
    },
    "embedding_request_start": {
        UiLanguage.zh: "开始发起 Embedding 请求",
        UiLanguage.en: "Embedding request started",
    },
    "embedding_request_complete": {
        UiLanguage.zh: "Embedding 请求完成",
        UiLanguage.en: "Embedding request completed",
    },
    "llm_extract_request_start": {
        UiLanguage.zh: "开始执行页面知识抽取",
        UiLanguage.en: "Page extraction request started",
    },
    "llm_extract_request_complete": {
        UiLanguage.zh: "页面知识抽取完成",
        UiLanguage.en: "Page extraction request completed",
    },
    "llm_extract_request_cancelled": {
        UiLanguage.zh: "页面知识抽取已取消",
        UiLanguage.en: "Page extraction request cancelled",
    },
    "llm_invalid_json": {
        UiLanguage.zh: "LLM 返回了无效 JSON",
        UiLanguage.en: "LLM returned invalid JSON",
    },
    "llm_request_failed": {
        UiLanguage.zh: "LLM 请求失败",
        UiLanguage.en: "LLM request failed",
    },
    "llm_merge_invalid_output": {
        UiLanguage.zh: "LLM 实体合并输出无效",
        UiLanguage.en: "LLM merge returned invalid structured output",
    },
    "llm_merge_failed": {
        UiLanguage.zh: "LLM 实体合并失败",
        UiLanguage.en: "LLM merge failed",
    },
    "llm_related_urls_start": {
        UiLanguage.zh: "开始筛选相关链接",
        UiLanguage.en: "Related URL filtering started",
    },
    "llm_related_urls_batch_start": {
        UiLanguage.zh: "开始处理一批相关链接",
        UiLanguage.en: "Related URL batch started",
    },
    "llm_related_urls_batch_complete": {
        UiLanguage.zh: "相关链接批处理完成",
        UiLanguage.en: "Related URL batch completed",
    },
    "llm_related_urls_batch_cancelled": {
        UiLanguage.zh: "相关链接批处理已取消",
        UiLanguage.en: "Related URL batch cancelled",
    },
    "llm_related_urls_invalid_json": {
        UiLanguage.zh: "相关链接筛选返回了无效 JSON",
        UiLanguage.en: "Related URL filtering returned invalid JSON",
    },
    "llm_related_urls_failed": {
        UiLanguage.zh: "相关链接筛选失败",
        UiLanguage.en: "Related URL filtering failed",
    },
    "llm_related_urls_complete": {
        UiLanguage.zh: "相关链接筛选完成",
        UiLanguage.en: "Related URL filtering completed",
    },
    "llm_analyze_page_start": {
        UiLanguage.zh: "开始分析页面内容",
        UiLanguage.en: "Page analysis started",
    },
    "llm_analyze_page_complete": {
        UiLanguage.zh: "页面内容分析完成",
        UiLanguage.en: "Page analysis completed",
    },
    "llm_analyze_manual_seed_start": {
        UiLanguage.zh: "开始分析手动种子内容",
        UiLanguage.en: "Manual seed analysis started",
    },
    "llm_analyze_manual_seed_complete": {
        UiLanguage.zh: "手动种子内容分析完成",
        UiLanguage.en: "Manual seed analysis completed",
    },
    "tool_execute_start": {
        UiLanguage.zh: "开始执行工具：{tool_name}",
        UiLanguage.en: "Tool execution started: {tool_name}",
    },
    "tool_execute_complete": {
        UiLanguage.zh: "工具执行完成：{tool_name}",
        UiLanguage.en: "Tool execution completed: {tool_name}",
    },
    "entity_vector_query_failed": {
        UiLanguage.zh: "实体向量查询失败",
        UiLanguage.en: "Entity vector query failed",
    },
    "query_preview_embedding_failed": {
        UiLanguage.zh: "查询预览向量化失败",
        UiLanguage.en: "Query preview embedding failed",
    },
    "source_vector_query_failed": {
        UiLanguage.zh: "来源向量查询失败",
        UiLanguage.en: "Source vector query failed",
    },
    "relation_vector_query_failed": {
        UiLanguage.zh: "关系向量查询失败",
        UiLanguage.en: "Relation vector query failed",
    },
    "entity_fulltext_query_failed": {
        UiLanguage.zh: "实体全文查询失败",
        UiLanguage.en: "Entity fulltext query failed",
    },
    "source_fulltext_query_failed": {
        UiLanguage.zh: "来源全文查询失败",
        UiLanguage.en: "Source fulltext query failed",
    },
    "relation_fulltext_query_failed": {
        UiLanguage.zh: "关系全文查询失败",
        UiLanguage.en: "Relation fulltext query failed",
    },
    "neo4j_sync_job_failed": {
        UiLanguage.zh: "同步采集任务到 Neo4j 失败",
        UiLanguage.en: "Failed to sync crawl job to Neo4j",
    },
    "neo4j_write_failed": {
        UiLanguage.zh: "写入采集结果到 Neo4j 失败",
        UiLanguage.en: "Failed to write crawl result to Neo4j",
    },
    "neo4j_migration_start": {
        UiLanguage.zh: "开始执行 Neo4j 迁移",
        UiLanguage.en: "Neo4j migration started",
    },
    "neo4j_migration_empty": {
        UiLanguage.zh: "Neo4j 迁移文件为空，已跳过",
        UiLanguage.en: "Neo4j migration file is empty and was skipped",
    },
    "neo4j_migration_failed": {
        UiLanguage.zh: "Neo4j 迁移失败",
        UiLanguage.en: "Neo4j migration failed",
    },
    "neo4j_migration_complete": {
        UiLanguage.zh: "Neo4j 迁移完成",
        UiLanguage.en: "Neo4j migration completed",
    },
    "neo4j_startup_unavailable": {
        UiLanguage.zh: "Neo4j 启动不可用，应用已降级运行",
        UiLanguage.en: "Neo4j unavailable during startup; application is running in degraded mode",
    },
    "neo4j_job_store_write_failed": {
        UiLanguage.zh: "写入 Neo4j 任务快照失败",
        UiLanguage.en: "Failed to persist crawl job snapshot to Neo4j",
    },
    "job_request_missing": {
        UiLanguage.zh: "未找到任务请求",
        UiLanguage.en: "Job request is missing",
    },
    "job_execution_failed": {
        UiLanguage.zh: "任务执行失败",
        UiLanguage.en: "Job execution failed",
    },
    "index_job_failed": {
        UiLanguage.zh: "索引任务执行失败",
        UiLanguage.en: "Index job failed",
    },
    "crawl_page_failed": {
        UiLanguage.zh: "页面处理失败",
        UiLanguage.en: "Page processing failed",
    },
    "auto_index_backfill_skipped_missing_service": {
        UiLanguage.zh: "自动索引补全已跳过：索引服务不可用",
        UiLanguage.en: "Auto index backfill skipped because indexing service is unavailable",
    },
    "auto_index_backfill_trigger_failed": {
        UiLanguage.zh: "自动索引补全触发失败",
        UiLanguage.en: "Auto index backfill trigger failed",
    },
    "pipeline_stage_timeout": {
        UiLanguage.zh: "流水线阶段执行超时",
        UiLanguage.en: "Pipeline stage timed out",
    },
    "job.created_queued": {
        UiLanguage.zh: "任务已创建，等待调度",
        UiLanguage.en: "Job created and queued",
    },
    "job.cancelled": {
        UiLanguage.zh: "任务已取消",
        UiLanguage.en: "Job cancelled",
    },
    "job.paused": {
        UiLanguage.zh: "任务已暂停",
        UiLanguage.en: "Job paused",
    },
    "job.execution_failed": {
        UiLanguage.zh: "任务执行失败",
        UiLanguage.en: "Job execution failed",
    },
    "job.resumed_queued": {
        UiLanguage.zh: "任务已恢复，等待调度",
        UiLanguage.en: "Job resumed and queued",
    },
    "job.run_started": {
        UiLanguage.zh: "任务已开始执行",
        UiLanguage.en: "Job execution started",
    },
    "job.run_resumed": {
        UiLanguage.zh: "任务继续执行",
        UiLanguage.en: "Job execution resumed",
    },
    "job.manual_input_processing_started": {
        UiLanguage.zh: "开始处理手工输入内容",
        UiLanguage.en: "Manual input processing started",
    },
    "job.manual_input_processed": {
        UiLanguage.zh: "手工输入内容已完成摘要与实体抽取",
        UiLanguage.en: "Manual input summarization and entity extraction completed",
    },
    "job.graph_update_started": {
        UiLanguage.zh: "开始写入知识图谱",
        UiLanguage.en: "Knowledge graph update started",
    },
    "job.manual_graph_updated": {
        UiLanguage.zh: "手工输入已完成知识图谱更新",
        UiLanguage.en: "Manual input knowledge graph update completed",
    },
    "job.url_queue_restored": {
        UiLanguage.zh: "已恢复 URL 抓取队列",
        UiLanguage.en: "URL crawl queue restored",
    },
    "job.url_queue_initialized": {
        UiLanguage.zh: "已初始化 URL 抓取队列",
        UiLanguage.en: "URL crawl queue initialized",
    },
    "job.max_pages_reached": {
        UiLanguage.zh: "达到页面数量上限，停止继续抓取",
        UiLanguage.en: "Maximum page limit reached; crawl stopped",
    },
    "job.completed": {
        UiLanguage.zh: "任务执行完成",
        UiLanguage.en: "Job execution completed",
    },
    "job.url_dequeued": {
        UiLanguage.zh: "从队列中取出一个页面准备处理",
        UiLanguage.en: "Dequeued a page for processing",
    },
    "job.skip_depth_limit": {
        UiLanguage.zh: "跳过超过最大深度的 URL",
        UiLanguage.en: "Skipped URL beyond max depth",
    },
    "job.skip_job_seen_url": {
        UiLanguage.zh: "跳过当前任务内已访问的 URL",
        UiLanguage.en: "Skipped URL already visited in this job",
    },
    "job.seed_url_history_bypass": {
        UiLanguage.zh: "当前种子 URL 为用户主动输入，绕过历史访问判重",
        UiLanguage.en: "Seed URL was user provided and bypassed history deduplication",
    },
    "job.skip_history_seen_url": {
        UiLanguage.zh: "跳过历史已处理的 URL",
        UiLanguage.en: "Skipped URL already processed in history",
    },
    "job.fetch_started": {
        UiLanguage.zh: "开始抓取页面",
        UiLanguage.en: "Page fetch started",
    },
    "job.skip_canonical_seen_url": {
        UiLanguage.zh: "跳过当前任务内已访问的规范化 URL",
        UiLanguage.en: "Skipped canonical URL already visited in this job",
    },
    "job.fetch_completed_extracting": {
        UiLanguage.zh: "页面抓取成功，开始正文抽取",
        UiLanguage.en: "Page fetched successfully; content extraction started",
    },
    "job.llm_context_started": {
        UiLanguage.zh: "开始查询图谱上下文并调用 LLM",
        UiLanguage.en: "Graph context lookup and LLM analysis started",
    },
    "job.llm_completed_filtered": {
        UiLanguage.zh: "LLM 已完成页面摘要、实体抽取与关联链接排序",
        UiLanguage.en: "LLM completed summarization, entity extraction, and related URL ranking",
    },
    "job.llm_completed_unfiltered": {
        UiLanguage.zh: "LLM 已完成页面摘要与实体抽取，待选 URL 未筛选",
        UiLanguage.en: "LLM completed summarization and entity extraction; candidate URLs were not filtered",
    },
    "job.irrelevant_skipped": {
        UiLanguage.zh: "页面与当前主题无关，跳过入库和后续扩展",
        UiLanguage.en: "Page is irrelevant to the current theme and was skipped",
    },
    "job.graph_update_completed": {
        UiLanguage.zh: "知识图谱更新完成",
        UiLanguage.en: "Knowledge graph update completed",
    },
    "job.queue_updated_filtered": {
        UiLanguage.zh: "已根据 LLM 排序后的关联链接更新抓取队列",
        UiLanguage.en: "Crawl queue updated with LLM-ranked related URLs",
    },
    "job.queue_updated_unfiltered": {
        UiLanguage.zh: "已根据未筛选的候选链接更新抓取队列",
        UiLanguage.en: "Crawl queue updated with unfiltered candidate URLs",
    },
    "job.page_failed": {
        UiLanguage.zh: "页面处理失败",
        UiLanguage.en: "Page processing failed",
    },
    "job.auto_index_backfill_detected": {
        UiLanguage.zh: "检测到图谱变更，开始自动触发索引补全任务",
        UiLanguage.en: "Graph changes detected; auto index backfill started",
    },
    "job.auto_index_backfill_failed": {
        UiLanguage.zh: "自动触发索引补全失败，已跳过",
        UiLanguage.en: "Auto index backfill trigger failed and was skipped",
    },
    "job.auto_index_backfill_processed": {
        UiLanguage.zh: "自动索引补全任务已处理",
        UiLanguage.en: "Auto index backfill jobs processed",
    },
    "job.timeout.manual_seed_analysis": {
        UiLanguage.zh: "手工输入摘要与实体抽取超时（>{timeout_seconds} 秒）",
        UiLanguage.en: "Manual input summarization and entity extraction timed out (>{timeout_seconds} seconds)",
    },
    "job.timeout.page_analysis": {
        UiLanguage.zh: "查询图谱上下文并调用 LLM 超时（>{timeout_seconds} 秒）",
        UiLanguage.en: "Graph context lookup and LLM analysis timed out (>{timeout_seconds} seconds)",
    },
    "indexing.job_created_queued": {
        UiLanguage.zh: "{index_type_label}索引任务已创建，等待执行",
        UiLanguage.en: "{index_type_label} index job created and queued",
    },
    "indexing.scan_started": {
        UiLanguage.zh: "开始扫描待同步索引对象",
        UiLanguage.en: "Scanning pending index candidates started",
    },
    "indexing.batch_started": {
        UiLanguage.zh: "开始处理一批索引对象",
        UiLanguage.en: "Index candidate batch started",
    },
    "indexing.job_completed": {
        UiLanguage.zh: "{index_type_label}索引任务执行完成",
        UiLanguage.en: "{index_type_label} index job completed",
    },
    "indexing.job_failed": {
        UiLanguage.zh: "{index_type_label}索引任务执行失败",
        UiLanguage.en: "{index_type_label} index job failed",
    },
    "indexing.active_job_conflict": {
        UiLanguage.zh: "已有运行中的 {index_type_label} 索引任务：{job_id}",
        UiLanguage.en: "An active {index_type_label} index job already exists: {job_id}",
    },
    "fetcher.playwright_not_installed": {
        UiLanguage.zh: "未安装 Playwright。请先执行 `pip install playwright` 并运行 `playwright install chromium`。",
        UiLanguage.en: "Playwright is not installed. Run `pip install playwright` and then `playwright install chromium`.",
    },
    "fetcher.no_response": {
        UiLanguage.zh: "浏览器抓取失败：未收到页面响应。",
        UiLanguage.en: "Browser fetch failed: no page response was received.",
    },
    "tool.fetch_url.description": {
        UiLanguage.zh: "抓取 URL 并返回 HTML、正文与状态信息。",
        UiLanguage.en: "Fetch a URL and return HTML, extracted text, and status metadata.",
    },
    "tool.extract_main_content.description": {
        UiLanguage.zh: "从 HTML 中抽取正文、标题和摘要输入。",
        UiLanguage.en: "Extract the main text, title, and summary input from HTML.",
    },
    "tool.discover_links.description": {
        UiLanguage.zh: "从 HTML 中发现允许域名内的未规范化链接。",
        UiLanguage.en: "Discover non-normalized links within allowed domains from HTML.",
    },
    "tool.query_neo4j_context.description": {
        UiLanguage.zh: "查询现有知识图谱中与关键词相关的实体上下文。",
        UiLanguage.en: "Query entity context related to keywords from the existing knowledge graph.",
    },
    "tool.upsert_kg_entity.description": {
        UiLanguage.zh: "将页面抽取结果写入知识图谱，支持关系新增与删除。",
        UiLanguage.en: "Write page extraction results into the knowledge graph, including relation inserts and deletes.",
    },
    "enum.index_type.vector": {
        UiLanguage.zh: "向量",
        UiLanguage.en: "Vector",
    },
    "enum.index_type.fulltext": {
        UiLanguage.zh: "全文",
        UiLanguage.en: "Fulltext",
    },
    "enum.index_scope.entity": {
        UiLanguage.zh: "实体",
        UiLanguage.en: "Entity",
    },
    "enum.index_scope.source": {
        UiLanguage.zh: "来源",
        UiLanguage.en: "Source",
    },
    "enum.index_scope.relation": {
        UiLanguage.zh: "关系",
        UiLanguage.en: "Relation",
    },
    "enum.index_scope.all": {
        UiLanguage.zh: "全部",
        UiLanguage.en: "All",
    },
    "enum.job_input_type.url": {
        UiLanguage.zh: "URL",
        UiLanguage.en: "URL",
    },
    "enum.job_input_type.instruction": {
        UiLanguage.zh: "自由文本指令",
        UiLanguage.en: "Instruction",
    },
    "enum.job_input_type.entity": {
        UiLanguage.zh: "实体名称",
        UiLanguage.en: "Entity",
    },
    "enum.job_status.queued": {
        UiLanguage.zh: "等待中",
        UiLanguage.en: "Queued",
    },
    "enum.job_status.running": {
        UiLanguage.zh: "运行中",
        UiLanguage.en: "Running",
    },
    "enum.job_status.paused": {
        UiLanguage.zh: "已暂停",
        UiLanguage.en: "Paused",
    },
    "enum.job_status.completed": {
        UiLanguage.zh: "已完成",
        UiLanguage.en: "Completed",
    },
    "enum.job_status.failed": {
        UiLanguage.zh: "失败",
        UiLanguage.en: "Failed",
    },
    "enum.job_status.cancelled": {
        UiLanguage.zh: "已取消",
        UiLanguage.en: "Cancelled",
    },
    "enum.job_status.interrupted": {
        UiLanguage.zh: "已中断",
        UiLanguage.en: "Interrupted",
    },
    "enum.completion_reason.cancelled": {
        UiLanguage.zh: "已取消",
        UiLanguage.en: "Cancelled",
    },
    "enum.completion_reason.paused": {
        UiLanguage.zh: "已暂停",
        UiLanguage.en: "Paused",
    },
    "enum.completion_reason.interrupted": {
        UiLanguage.zh: "已中断",
        UiLanguage.en: "Interrupted",
    },
    "enum.completion_reason.queue_exhausted": {
        UiLanguage.zh: "队列耗尽",
        UiLanguage.en: "Queue exhausted",
    },
    "enum.completion_reason.max_pages_reached": {
        UiLanguage.zh: "达到页面上限",
        UiLanguage.en: "Maximum pages reached",
    },
}

_PARAM_ENUM_KEY_PREFIXES: dict[str, str] = {
    "index_type": "enum.index_type",
    "scope": "enum.index_scope",
    "input_type": "enum.job_input_type",
    "job_status": "enum.job_status",
    "completion_reason": "enum.completion_reason",
}


class _SafeFormatDict(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _enrich_params(params: Mapping[str, Any], language: UiLanguage) -> dict[str, Any]:
    enriched = dict(params)
    for param_name, prefix in _PARAM_ENUM_KEY_PREFIXES.items():
        value = enriched.get(param_name)
        label_name = f"{param_name}_label"
        if label_name in enriched or not isinstance(value, str) or not value:
            continue
        enum_key = f"{prefix}.{value}"
        translations = _MESSAGE_CATALOG.get(enum_key)
        if translations is None:
            continue
        enriched[label_name] = translations.get(language) or translations.get(UiLanguage.en) or value
    return enriched


def normalize_ui_language(language: UiLanguage | str | None) -> UiLanguage:
    if isinstance(language, UiLanguage):
        return language
    if str(language or "").lower().startswith("zh"):
        return UiLanguage.zh
    return UiLanguage.en


def set_current_ui_language(language: UiLanguage | str | None) -> UiLanguage:
    normalized = normalize_ui_language(language)
    with _language_lock:
        global _current_ui_language
        _current_ui_language = normalized
    return normalized


def get_current_ui_language() -> UiLanguage:
    with _language_lock:
        return _current_ui_language


def render_text(
    key: str,
    *,
    params: Mapping[str, Any] | None = None,
    language: UiLanguage | str | None = None,
    default: str | None = None,
) -> str:
    translations = _MESSAGE_CATALOG.get(key)
    resolved_language = normalize_ui_language(language or get_current_ui_language())
    template = None
    if translations is not None:
        template = translations.get(resolved_language) or translations.get(UiLanguage.en)
    if template is None:
        return default if default is not None else key
    enriched_params = _enrich_params(params or {}, resolved_language)
    return template.format_map(_SafeFormatDict(**enriched_params))