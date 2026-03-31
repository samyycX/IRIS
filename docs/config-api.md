# Config API

本文件描述 `FEATURE 2` 当前后端已提供的配置接口，供后续前端配置页直接对接。

## 设计约定

- 配置文件是唯一运行配置来源，默认保存在数据目录下的 `config/app_config.json`。
- 数据目录规则：
  - 本地运行：`./data`
  - Docker 环境：`/data`
  - 如需覆盖，可设置 `IRIS_DATA_ROOT`
- 启动时如果配置文件不存在，会自动生成一个“空配置文件”。
- 空配置文件不会启用 Neo4j、LLM、Embedding，也不会运行 Neo4j migration。
- 通过接口更新配置后，后端会立即 reload 运行时依赖。
- 如果更新后的激活 Neo4j 配置完整，reload 过程中会执行 Neo4j migration。
- 每次 reload 完成后，后端会立即重测 Neo4j、LLM、Embedding 的运行状态，并刷新状态快照。
- 后端不会后台轮询这些依赖；状态只会在初始化、调用 `/api/status`、以及配置 reload 时更新。
- Prompt 使用后端内置默认值，当前不提供自定义接口。
- 当前前端最核心需要配置的文本项是 `runtime.knowledge_theme`。
- Playwright 和无头浏览器默认开启，不再作为可配置项暴露。

## 配置结构

`GET /api/config` 返回完整配置对象：

```json
{
  "schema_version": 1,
  "neo4j_profiles": [
    {
      "id": "local-neo4j",
      "uri": "neo4j://127.0.0.1:7687",
      "username": "neo4j",
      "password": "secret"
    }
  ],
  "active_neo4j_profile_id": "local-neo4j",
  "llm_profiles": [
    {
      "id": "gemini-main",
      "base_url": "https://example.com/v1",
      "api_key": "secret",
      "model": "gemini-3-pro"
    }
  ],
  "active_llm_profile_id": "gemini-main",
  "embedding_profiles": [
    {
      "id": "embedding-main",
      "base_url": "https://example.com/v1",
      "api_key": "secret",
      "model": "text-embedding-3-small"
    }
  ],
  "active_embedding_profile_id": "embedding-main",
  "runtime": {
    "knowledge_theme": "",
    "embedding_dimensions": 1536,
    "embedding_batch_size": 16,
    "embedding_text_max_chars": 4000,
    "embedding_version": "v1",
    "visited_url_ttl_days": 10,
    "allowed_domains_enabled": false,
    "allowed_domains": [],
    "max_crawl_depth": 2,
    "max_pages_per_job": 20,
    "crawl_concurrency": 1,
    "request_timeout_seconds": 20,
    "llm_timeout_seconds": 90,
    "user_agent": "IRISKGCrawler/0.1",
    "skip_history_seen_urls": true,
    "auto_backfill_indexes_after_crawl": false,
    "browser_navigation_timeout_ms": 30000,
    "browser_post_load_wait_ms": 1500,
    "browser_scroll_pause_ms": 400,
    "browser_scroll_rounds": 6,
    "browser_locale": "zh-CN",
    "browser_auto_accept_consent": true
  }
}
```

## 接口列表

### 1. 读取完整配置

- 方法：`GET /api/config`
- 用途：前端初始化配置页时拉取完整配置。

### 2. 覆盖保存完整配置

- 方法：`PUT /api/config`
- 用途：整体保存配置。
- 行为：保存成功后立即 reload；如果激活的 Neo4j 配置完整，会在 reload 时运行 migration。

### 3. 读取配置摘要

- 方法：`GET /api/config/summary`
- 用途：轻量展示当前状态。

响应示例：

```json
{
  "schema_version": 1,
  "data_root": "E:/programming/IRIS/data",
  "active_profiles": {
    "neo4j": "local-neo4j",
    "llm": "gemini-main",
    "embedding": "embedding-main"
  },
  "knowledge_theme": "",
  "allowed_domains": []
}
```

### 4. 手动 reload 配置

- 方法：`POST /api/config/reload`
- 用途：当外部直接改了配置文件，或前端希望显式触发一次重载时调用。
- 行为：会重新构建运行时依赖；若 Neo4j 配置完整，则同时执行 migration。

### 5. 列出所有数据源配置

- 方法：`GET /api/config/data-sources`

响应示例：

```json
{
  "active_neo4j_profile_id": "local-neo4j",
  "active_llm_profile_id": "gemini-main",
  "active_embedding_profile_id": "embedding-main",
  "neo4j_profiles": [],
  "llm_profiles": [],
  "embedding_profiles": []
}
```

### 6. 新增数据源配置

- 方法：`POST /api/config/data-sources/{kind}`
- `kind` 可选值：
  - `neo4j`
  - `llm`
  - `embedding`
- 行为：如果当前类型还没有 active profile，新建后会自动设为 active，然后自动 reload。

### 7. 更新数据源配置

- 方法：`PUT /api/config/data-sources/{kind}/{profile_id}`
- 用途：更新指定 profile。
- 行为：保存后自动 reload。

### 8. 删除数据源配置

- 方法：`DELETE /api/config/data-sources/{kind}/{profile_id}`
- 限制：不能删除当前 active profile。
- 行为：删除后自动 reload；如果该类型删空，active 会变成 `null`。

### 9. 设置 active 数据源

- 方法：`PUT /api/config/data-sources/{kind}/active/{profile_id}`
- 用途：切换当前生效的数据源。
- 行为：切换后自动 reload。

### 10. 清空 active 数据源

- 方法：`DELETE /api/config/data-sources/{kind}/active`
- 用途：显式停用某类数据源。
- 行为：清空后自动 reload。

### 11. 读取运行时状态

- 方法：`GET /api/status`
- 用途：返回当前 Neo4j、LLM、Embedding 的健康状态，以及当前图谱中的 Entity、Source、RELATED_TO 计数。
- 行为：每次请求都会即时刷新一次状态快照；当 Neo4j 当前不可用但此前拿到过统计时，会保留最近一次成功统计并标记 `graph.stale=true`。

响应示例：

```json
{
  "status": "healthy",
  "checked_at": "2026-03-31T10:20:30.000000Z",
  "neo4j": {
    "state": "healthy",
    "configured": true,
    "available": true,
    "last_checked_at": "2026-03-31T10:20:30.000000Z",
    "last_error": null,
    "details": {
      "uri": "neo4j://127.0.0.1:7687"
    }
  },
  "llm": {
    "state": "healthy",
    "configured": true,
    "available": true,
    "last_checked_at": "2026-03-31T10:20:30.000000Z",
    "last_error": null,
    "details": {
      "base_url": "https://example.com/v1",
      "model": "gpt-4.1-mini"
    }
  },
  "embedding": {
    "state": "healthy",
    "configured": true,
    "available": true,
    "last_checked_at": "2026-03-31T10:20:30.000000Z",
    "last_error": null,
    "details": {
      "base_url": "https://example.com/v1",
      "model": "text-embedding-3-small"
    }
  },
  "graph": {
    "entity_count": 128,
    "source_count": 52,
    "relation_count": 476,
    "stale": false,
    "last_updated_at": "2026-03-31T10:20:30.000000Z"
  }
}
```

## 空配置建议

前端首次进入时可以接受以下空态：

```json
{
  "schema_version": 1,
  "neo4j_profiles": [],
  "active_neo4j_profile_id": null,
  "llm_profiles": [],
  "active_llm_profile_id": null,
  "embedding_profiles": [],
  "active_embedding_profile_id": null,
  "runtime": { "...": "使用后端默认值" }
}
```

建议前端按以下顺序引导用户：

1. 创建 Neo4j / LLM / Embedding 数据源。
2. 选择 active profile。
3. 至少设置 `runtime.knowledge_theme`。
4. 按需调整其他 runtime 参数。
5. 保存后调用摘要接口确认当前生效状态。

## 错误语义

- `400 Bad Request`
  - Profile 重名
  - Profile 数据结构不合法
- `404 Not Found`
  - 要更新或激活的 profile 不存在
- `409 Conflict`
  - 尝试删除当前 active profile
- `503 Service Unavailable`
  - Neo4j 当前不可用时，索引预扫描、建索引和搜索预览接口会返回 503，而不是 500

## 前端实现建议

- 配置页建议分组：
  - Neo4j
  - LLM
  - Embedding
  - Runtime
- 数据源列表页建议支持“新增、编辑、删除、设为当前生效”四个动作。
