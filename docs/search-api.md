# Search API

本文件描述对外开放的搜索 API 契约。该接口独立于 dashboard Cookie 门禁，使用单独的搜索 API 配置与权限源校验。

## 设计目标

- 对外开放精确 Entity / Source 查询接口。
- 提供统一搜索入口，支持 `fulltext`、`vector`、`hybrid`。
- API Key 与 IP 白名单统一视为同一种权限源。
- 每个权限源都可以单独控制是否允许调用服务端内置 Embedding。

## 总体规则

- 路由前缀：`/api/search/v1`
- 除 `capabilities` 外，所有查询接口统一使用 `POST`
- 认证方式：
  - `X-API-Key: <secret>`
  - 或 `Authorization: Bearer <secret>`
  - 或命中 IP 白名单
- IP 判断只使用直连客户端 IP，不信任 `X-Forwarded-For` / `X-Real-IP`
- 当 `search_api.enabled=false` 时，所有接口返回 `409 Conflict`
- 当 `search_api.validation_enabled=false` 时，所有请求直接放行，并默认允许内置 Embedding

## 能力模型

每次请求都会落在一个权限源上下文中：

- `api_key`
- `ip`

权限源核心字段：

- `id`: 权限源标识
- `kind`: `api_key` 或 `ip`
- `enabled`: 是否启用
- `allow_builtin_embedding`: 是否允许服务端为文本查询自动生成向量

当 `allow_builtin_embedding=false` 时：

- `fulltext` 查询仍可直接使用 `query_text`
- `vector` 查询必须传 `query_vector`
- `hybrid` 查询必须同时传 `query_text` 与 `query_vector`

Entity 查询支持两个额外限额：

- `source_limit`: 控制 `mentioned_in_sources` 返回条数
- `relation_limit`: 分别控制 `outgoing_relations` 和 `incoming_relations` 的最大返回条数

## 错误语义

- `400 Bad Request`
  - 查询参数不完整
  - `query_vector` 为空或维度错误
- `401 Unauthorized`
  - 提供了 API Key 但校验失败
- `403 Forbidden`
  - IP 未命中白名单
  - 当前权限源不允许调用内置 Embedding
- `404 Not Found`
  - 精确查询未命中 Entity 或 Source
- `409 Conflict`
  - 搜索 API 功能被关闭
- `503 Service Unavailable`
  - Neo4j 不可用
  - 验证已启用但没有任何有效权限源

## 1. 获取调用能力

`GET /api/search/v1/capabilities`

响应示例：

```json
{
  "enabled": true,
  "validation_enabled": true,
  "authenticated": true,
  "matched_permission_source_id": "partner-alpha",
  "matched_permission_source_kind": "api_key",
  "allow_builtin_embedding": false,
  "embedding_dimensions": 1536,
  "supported_modes": ["fulltext", "vector", "hybrid"],
  "query_vector_required_for_semantic_search": true
}
```

## 2. 精确查询 Entity

统一使用同一个接口：`POST /api/search/v1/entities/query`

请求体至少提供一个字段：`entity_id`、`name`、`alias`。

按 `entity_id` 查询示例：

```json
{
  "entity_id": "role-alpha",
  "source_limit": 5,
  "relation_limit": 5
}
```

按精确名称查询示例：

```json
{
  "name": "角色甲",
  "limit": 10,
  "source_limit": 3,
  "relation_limit": 2
}
```

按别名查询示例：

```json
{
  "alias": "Role Alpha",
  "limit": 10,
  "source_limit": 3,
  "relation_limit": 2
}
```

响应示例：

```json
{
  "items": [
    {
      "entity_id": "role-alpha",
      "name": "角色甲",
      "normalized_name": "角色甲",
      "category": "character",
      "summary": "角色甲摘要",
      "aliases": ["Role Alpha"],
      "mentioned_in_sources": [
        {
          "id": "https://example.com/role-alpha",
          "title": "角色甲词条",
          "summary": "来源摘要",
          "relevance": 0.98
        }
      ],
      "outgoing_relations": [],
      "incoming_relations": []
    }
  ]
}
```

说明：

- 当提供 `entity_id` 时，结果最多返回 1 条。
- 当提供 `name` 或 `alias` 时，结果遵循 `limit`。

## 3. 精确查询 Source

仅保留 `source_key` 查询接口。

`POST /api/search/v1/sources/query`

请求体：

```json
{
  "source_key": "https://example.com/role-alpha"
}
```

当前 `source_key` 与 `canonical_url` 等价，都是 `Source.canonical_url`。

响应示例：

```json
{
  "source": {
    "source_key": "https://example.com/role-alpha",
    "canonical_url": "https://example.com/role-alpha",
    "title": "角色甲词条",
    "summary": "来源摘要",
    "fetched_at": null,
    "content_hash": "hash-1",
    "mentioned_entities": [
      {
        "entity_id": "role-alpha",
        "name": "角色甲"
      }
    ]
  }
}
```

## 4. 统一搜索接口

`POST /api/search/v1/search`

请求体：

```json
{
  "query_text": "角色甲",
  "mode": "hybrid",
  "entity_limit": 5,
  "source_limit": 5,
  "relation_limit": 5
}
```

支持字段：

- `query_text`: 文本查询，可为空；`fulltext` 与 `hybrid` 必须提供
- `query_vector`: 手工传入查询向量
- `mode`: `fulltext` / `vector` / `hybrid`
- `entity_limit`: Entity 结果条数
- `source_limit`: Source 结果条数
- `relation_limit`: Relation 结果条数

### 向量搜索示例

当权限源不允许内置 Embedding 时：

```json
{
  "mode": "vector",
  "query_vector": [0.12, 0.34, 0.56]
}
```

### 混合搜索示例

当权限源不允许内置 Embedding 时：

```json
{
  "query_text": "角色甲",
  "query_vector": [0.12, 0.34, 0.56],
  "mode": "hybrid"
}
```

响应示例：

```json
{
  "query_text": "角色甲",
  "mode": "hybrid",
  "query_vector_provided": false,
  "capabilities": {
    "enabled": true,
    "validation_enabled": true,
    "authenticated": true,
    "matched_permission_source_id": "partner-alpha",
    "matched_permission_source_kind": "api_key",
    "allow_builtin_embedding": true,
    "embedding_dimensions": 1536,
    "supported_modes": ["fulltext", "vector", "hybrid"],
    "query_vector_required_for_semantic_search": false
  },
  "entities": [],
  "sources": [
    {
      "source_key": "https://example.com/role-alpha",
      "title": "角色甲词条",
      "summary": "来源摘要",
      "fulltext_score": 0.82,
      "vector_score": 0.79,
      "hybrid_score": 0.0323
    }
  ],
  "relations": [],
  "neighborhoods": []
}
```

## 配置入口

管理端使用以下受 dashboard Cookie 保护的接口：

- `PUT /api/config/search-api/settings`
- `POST /api/config/search-api/permissions`
- `PUT /api/config/search-api/permissions/{source_id}`
- `DELETE /api/config/search-api/permissions/{source_id}`

详细配置结构见 [docs/config-api.md](docs/config-api.md)。