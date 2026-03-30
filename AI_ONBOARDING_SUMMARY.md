# I.R.I.S. 项目总览

这份文档是给后续接手此项目的 AI 或开发者看的快速上手说明。目标不是替代源码，而是帮助你在最短时间内理解：

- 这个项目是干什么的
- 从哪里开始看
- 一次任务是怎么流转的
- 每个文件大致负责什么
- 如果要继续扩展，应该改哪里

---

## 1. 项目一句话说明

这是一个面向通用知识图谱构建的 Python 单体应用。它支持从 URL、文本指令或实体名发起任务，自动抓取网页、抽取正文、调用 OpenAI 兼容 LLM 生成结构化知识，并把页面、实体、关系写入 Neo4j，同时把任务状态、事件流、checkpoint 和图谱更新摘要持久化到 Neo4j `CrawlJob`。当前提示词已统一为单一版本，可通过 `KNOWLEDGE_THEME` 控制采集时只保留和指定主题相关的页面。

---

## 2. 当前技术栈

- Web 层：`FastAPI` + `React (Vite, Shadcn UI)` 纯静态前端
- 抓取层：`httpx` + `Playwright` + `BeautifulSoup` + `trafilatura`
- LLM 层：`openai` Python SDK，兼容 OpenAI 风格接口
- 图数据库：`Neo4j`
- 图迁移：启动时自动执行 `app/repos/migrations/*.cypher`
- 去重持久化：本地 JSON 文件 `VISITED_URLS_FILE`，记录访问时间并默认按最近 `10` 天窗口判重
- 后台任务：进程内异步任务
- 日志：`structlog`
- 前端实时刷新：`SSE`

---

## 3. 你应该先看哪些文件

如果你是第一次接手，推荐按这个顺序阅读：

1. `app/main.py`
2. `app/core/container.py`
3. `app/services/crawl/pipeline.py`
4. `app/services/jobs.py`
5. `app/repos/graph_repo.py`
6. `app/repos/neo4j_job_store.py`
7. `app/repos/graph_migrations.py`
8. `app/services/graphrag/workflow.py`
9. `app/services/graphrag/retriever.py` 和 `app/services/graphrag/retrievers.py`
10. `app/services/llm/client.py`
11. `app/web/routes.py` 和 `app/api/routes.py`
12. `app/models/jobs.py`
13. `AI_ONBOARDING_SUMMARY.md` 本文件作为导航

---

## 4. 系统主流程

### 4.1 URL 任务流

1. 用户在首页提交 URL。
2. `app/web/routes.py` 或 `app/api/routes.py` 接收请求，组装 `JobRequest`。
3. `app/services/jobs.py` 创建 `job_id`，把任务交给本地异步任务。
4. `app/services/crawl/pipeline.py` 开始执行：
   - 规范化 URL
   - 检查当前任务和全局是否已抓取
   - 调用 `fetch_url` 工具抓取页面
   - 抽取正文、标题、链接
   - 调用 LangChain GraphRAG workflow，先做图检索，再做邻域扩展、结构化抽取和候选链接评分
   - GraphRAG 检索会综合 `Entity` 向量/关键词召回、`Source` 向量召回、`RelationEmbedding` 召回和实体邻域扩展
   - 调用 `upsert_kg_entity` 写入 Neo4j
   - 持续递归抓取，直到达到深度或页面数量上限
5. `app/repos/neo4j_job_store.py` 持久化任务状态、事件、checkpoint 和恢复信息。
6. `app/api/routes.py` 的 SSE 接口把实时进度推给任务详情页。

### 4.2 手工输入任务流

1. 用户输入文本指令或实体名。
2. 不走网页抓取，直接进入 `LlmOrchestrator.analyze_manual_seed()`。
3. 生成 `PageExtraction` 风格的结构化结果。
4. 仍然复用图谱写入逻辑和日志链路。

---

## 5. 当前架构中的几个核心抽象

### 5.1 `ServiceContainer`

`app/core/container.py` 是全项目依赖装配中心。这里创建并连接：

- 配置对象
- Neo4j 仓库
- Neo4j 迁移管理器
- URL 历史文件仓库
- 抓取器、抽取器、链接发现器
- LLM 客户端、GraphRAG retriever 和 workflow
- Tool 注册中心和执行器
- 任务服务

以后如果新增组件，优先在这里接线。

### 5.2 `JobService`

`app/services/jobs.py` 只负责任务生命周期：

- 创建任务
- 调度本地异步执行
- 提供任务查询
- 提供手动 resume
- 提供 SSE 事件流

它不做抓取和抽取细节，这些都在 `CrawlPipeline`。

### 5.3 `CrawlPipeline`

`app/services/crawl/pipeline.py` 是核心业务流程。它把抓取、抽取、LLM、图谱更新串起来，是未来最可能继续演化的文件之一。

### 5.4 `Tool` 体系

`app/services/tools/` 提供了工具抽象：

- `BaseTool`：工具协议
- `ToolRegistry`：注册工具
- `ToolExecutor`：统一调用入口
- `builtins.py`：当前内置工具集合

现在 Tool 体系主要保留给抓取和写图库；GraphRAG 主链路已经不再依赖自定义图查询 Tool。

### 5.5 `GraphRAG` 体系

`app/services/graphrag/` 是当前图检索和 LangChain 编排核心：

- `retrievers.py`：LangChain 自定义 retriever，分别封装实体、来源和关系查询
- `retriever.py`：聚合多个 retriever，并补齐邻域扩展和候选 URL 实体信号
- `context_builder.py`：把图上下文压缩为适合 prompt 的文档块
- `workflow.py`：用 LangGraph 串起 `retrieve -> extract -> rank links`

---

## 6. 按目录逐文件总结

下面按目录列出当前所有重要文件的职责。对于纯包标记文件会简写说明。

### 6.1 根目录

#### `pyproject.toml`

- Python 项目的依赖和开发工具配置。
- 定义了运行依赖：FastAPI、Neo4j、OpenAI、Trafilatura 等。
- 定义了测试和 Ruff 配置。

#### `.env.example`

- 示例配置文件。
- 包含 OpenAI 接口地址、API Key、Neo4j 连接、已访问 URL 文件路径、URL 历史 TTL、爬取深度、最大页面数等。
- 可通过 `SKIP_HISTORY_SEEN_URLS` 控制是否跳过跨任务历史已处理 URL。
- 可通过 `AUTO_BACKFILL_INDEXES_AFTER_CRAWL` 控制 URL 采集任务在写入实体/关系后是否自动触发索引补全任务。
- 新环境部署时首先复制为 `.env`。

#### `.gitignore`

- 忽略 `.env`、缓存目录、字节码文件。

#### `README.md`

- 给人类开发者看的简要项目说明和启动方法。

#### `AI_ONBOARDING_SUMMARY.md`

- 当前这份 AI 接手总览文档。

---

### 6.2 `app/`

#### `app/__init__.py`

- 包标记文件，无业务逻辑。

#### `app/main.py`

- 应用入口。
- 在 `lifespan` 中读取配置、初始化日志、创建 `ServiceContainer`、在应用关闭时释放资源。
- 挂载静态文件和 API/Web 路由。
- 提供 `/healthz` 健康检查。

---

### 6.3 `app/core/`

#### `app/core/__init__.py`

- 包标记文件。

#### `app/core/config.py`

- 统一配置模型 `Settings`。
- 负责把环境变量解析成强类型对象。
- 包含 `APP_NAME`、`KNOWLEDGE_THEME` 等运行时配置入口。
- 包含 `AUTO_BACKFILL_INDEXES_AFTER_CRAWL`，用于控制 URL 采集任务完成后是否自动发起索引补全。
- `allowed_domains` 支持逗号分隔字符串自动拆分。
- `get_settings()` 用 `lru_cache` 做单例缓存。

#### `app/core/logging.py`

- 初始化结构化日志。
- 用 `structlog` 输出 JSON 风格日志。
- 把默认 `event` 字段改名为 `message`，便于日志系统消费。

#### `app/core/container.py`

- 服务装配中心，负责创建项目所有核心组件。
- 应用启动时会：
  - 初始化图仓库
  - 执行 Neo4j `.cypher` 迁移
  - 初始化 URL 历史文件仓库
  - 注册 Tool
  - 确保 Neo4j 约束存在
  - 将上次异常中断但仍显示 `queued/running` 的任务转为 `interrupted`
- 如果以后要换 URL 历史存储、换图数据库、加入新工具，这里是最关键的接入点。

---

### 6.4 `app/models/`

#### `app/models/__init__.py`

- 聚合导出模型，方便其他模块统一导入。

#### `app/models/jobs.py`

- 项目主要数据模型集中定义处。
- 关键模型包括：
  - `JobRequest`：任务创建输入
  - `JobSummary`：任务整体状态
  - `JobEvent`：事件流单条记录
  - `JobQueueItem` / `JobCheckpoint`：URL 任务恢复所需的 checkpoint 结构
  - `CrawlPageResult`：网页抓取和正文抽取结果
  - `ExtractedEntity`：LLM 输出的实体对象
  - `PageExtraction`：页面级结构化抽取结果
  - `GraphUpdateResult`：写图谱后的变更摘要
- 其中 `ExtractedEntity` 已支持通过 `deleted_relations` 表达需要删除的旧关系。

如果以后要丰富关系结构、增加置信度、记录更多证据字段，这里通常要先改。

---

### 6.5 `app/api/`

#### `app/api/__init__.py`

- 包标记文件。

#### `app/api/routes.py`

- 对外 API。
- 当前提供：
  - `POST /api/jobs`：创建任务
  - `GET /api/jobs`：列出任务
  - `GET /api/jobs/{job_id}`：获取任务状态
  - `POST /api/jobs/{job_id}/resume`：手动继续中断任务
  - `GET /api/jobs/{job_id}/events`：获取完整事件列表
  - `GET /api/jobs/{job_id}/stream`：SSE 实时事件流

这是后续做前后端分离、CLI 调用、自动化接入时的主要接口层。

---

### 6.6 `frontend/`

- 前端 React 单页应用。
- 使用 Vite 构建，Shadcn UI 和 Tailwind CSS 驱动界面。
- 启动 `npm run build` 后，产物放在 `frontend/dist` 供 FastAPI 托管。
- 提供首页和任务实时日志详情页，支持国际化（i18n）与深色主题。

---

### 6.7 `app/repos/`

#### `app/repos/__init__.py`

- 聚合导出仓库层对象。

#### `app/repos/event_store.py`

- 当前任务状态与事件流的抽象接口 `JobStore`，以及测试用内存实现 `InMemoryEventStore`。
- 维护：
  - 任务摘要
  - 原始请求
  - 事件列表
  - 每个任务访问过的 URL
  - 全局访问过的 URL
- 主要用于测试和接口抽象，不再是生产环境的事实来源。

#### `app/repos/neo4j_job_store.py`

- 当前生产环境使用的任务状态仓库。
- 以 Neo4j `CrawlJob` 为事实来源，负责：
  - 创建和列出任务
  - 更新 `status / visited_count / queued_count / failed_count / last_error`
  - 持久化 `request_json / events_json / checkpoint_json / visited_urls_json`
  - 标记 `resume_available`
  - 读取 checkpoint 并支持手动续跑
- 旧版 `CrawlJob` 节点缺字段时，这里也会做兼容兜底读取，避免接口直接 500。

#### `app/repos/graph_migrations.py`

- Neo4j 图数据迁移管理器。
- 启动时扫描 `app/repos/migrations/` 下的 `.cypher` 文件并按版本执行。
- 迁移文件命名格式：`V<number>__name.cypher`
- 迁移状态和历史记录写入 Neo4j：
  - `MigrationState`
  - `MigrationRecord`
- 这套机制不只服务于 `CrawlJob`，所有节点、关系、索引或补数据脚本都应该优先走这里。

#### `app/repos/url_history.py`

- URL 历史判重仓库。
- 优先查本地 JSON 文件中的最近访问记录。
- 文件中不存在或已过期时，再回退到 Neo4j 中页面的 `fetched_at` 判断是否在 TTL 窗口内访问过。
- 当前默认只跳过最近 `10` 天内访问过的页面。

#### `app/repos/graph_repo.py`

- Neo4j 访问层，是图谱持久化核心。
- 负责：
  - 建立唯一约束
  - 查询已有实体上下文
  - 判断页面是否已存在
  - 写入 `Source`、`CrawlJob`、`Entity`
  - 为 `CrawlJob` 持久化任务 summary、请求快照、图谱变更摘要和详细修改记录
  - 维护 `VISITED`、`LINKS_TO`、`MENTIONED_IN`、`RELATED_TO` 关系

这个文件代表当前图谱模型的落地实现。如果未来引入更复杂的实体对齐、版本化节点、置信度边权，基本都会从这里演进。

---

### 6.8 `app/services/crawl/`

#### `app/services/crawl/__init__.py`

- 聚合导出抓取相关服务。

#### `app/services/crawl/canonicalizer.py`

- URL 规范化工具。
- 负责：
  - 解析相对链接
  - 统一大小写
  - 去掉 fragment
  - 去掉常见跟踪参数，比如 `utm_`、`fbclid`

去重链路的第一步就是它。

#### `app/services/crawl/fetcher.py`

- 默认基于 `httpx.AsyncClient` 抓取页面。
- 当 `ENABLE_PLAYWRIGHT=true` 时，会改为使用 Playwright + Chromium 进行浏览器级渲染抓取。
- 支持设置 UA、超时、locale、滚动次数与页面额外等待时间，以便更拟真地抓取动态页面。

#### `app/services/crawl/extractor.py`

- 从 HTML 中提取标题和正文。
- 优先用 `trafilatura` 取主内容，失败时回退到 `BeautifulSoup.get_text()`。
- 对正文计算 `content_hash`，用于内容级去重或变更检测。

#### `app/services/crawl/discovery.py`

- 从 HTML 中发现链接。
- 结合 `URLCanonicalizer` 做规范化。
- 只保留允许域名内链接。
- 自动去重。

#### `app/services/crawl/pipeline.py`

- 当前整个业务流的中枢。
- 对 URL 任务来说，这个文件负责：
  - 从种子 URL 开始 BFS 式递归抓取
  - 深度限制和页面数量限制
  - 本任务去重和历史去重
  - 发出阶段事件
  - 持续把队列、处理中 URL、visited 集合和总图谱变更写回 checkpoint
  - 调用 Tool 抓取网页
  - 调用 LLM 做总结、抽取与关联链接排序
  - 按排序结果入队新发现链接
  - 调用图谱写入
- 当 `AUTO_BACKFILL_INDEXES_AFTER_CRAWL=true` 且本次任务确实更新了实体/关系时，任务结束后自动发起全文和向量索引的 `backfill` 任务，只补全缺失或过期的数据
  - 合并多页图谱更新结果

如果后续要加入：

- 限速器
- robots 规则
- 重试策略
- 域名优先级
- JS 页面自动回退 BrowserFetcher
- 多站点爬取策略

优先改这个文件或把它拆层。

---

### 6.9 `app/services/llm/`

#### `app/services/llm/__init__.py`

- 聚合导出 LLM 相关服务。

#### `app/services/llm/prompts.py`

- 当前 GraphRAG 结构化抽取和链接评分的统一系统提示词定义。
- 支持通过 `KNOWLEDGE_THEME` 做页面级主题过滤；当页面与主题无关时，会直接跳过入库和信息抽取。
- 约束 LangChain structured output 的语义结构，包含页面相关性、页面摘要、实体关系和候选链接排序结果。

#### `app/services/llm/client.py`

- OpenAI 兼容客户端封装。
- 负责：
  - 发起聊天补全请求
  - 要求返回 JSON
  - 把结果解析为 `ExtractedEntity`
  - 当没有配置 API Key 或模型返回异常时，自动走 fallback 抽取

当前 fallback 很简单，只会拿页面标题和前几行文本做保底摘要，适合开发阶段，但不适合生产质量。

#### `app/services/llm/orchestrator.py`

- LLM 入口适配层。
- 现在主要负责把 `CrawlPipeline` 的调用转发到 `GraphRAGWorkflow`，并把输出统一包装回 `PageExtraction`。

真正的图检索和 LangChain 编排已经下沉到 `app/services/graphrag/`。

---

### 6.10 `app/services/kg/`

#### `app/services/kg/__init__.py`

- 聚合导出知识图谱服务。

#### `app/services/kg/service.py`

- 知识图谱服务层。
- 目前逻辑比较薄：
  - 调 `graph_repo` 写入图谱
  - 调 `url_history` 记住已处理 URL

以后如果加入实体对齐、冲突解决、版本快照、审核流，这里会逐渐变重。

---

### 6.11 `app/services/tools/`

#### `app/services/tools/__init__.py`

- 聚合导出工具层对象。

#### `app/services/tools/base.py`

- `BaseTool` 抽象定义。
- 约定每个工具都需要：
  - `name`
  - `description`
  - `schema`
  - `execute()`

#### `app/services/tools/registry.py`

- 保存已注册工具。
- 提供 `list_schemas()`，方便未来把工具 schema 提供给更完整的 LLM Agent。

#### `app/services/tools/executor.py`

- 统一工具执行入口。
- 在执行前后打日志。

#### `app/services/tools/builtins.py`

- 当前内置工具集合：
  - `fetch_url`
  - `extract_main_content`
  - `discover_links`
  - `upsert_kg_entity`
- 其中 `upsert_kg_entity` 现在既能新增关系，也能按实体描述删除指定 `RELATED_TO` 关系。

这些 Tool 现在主要服务于抓取和写图；图检索不再通过 `query_neo4j_context` 这类自定义 Tool 驱动主链路。

---

### 6.12 `app/services/`

#### `app/services/__init__.py`

- 包标记文件。

#### `app/services/jobs.py`

- 任务生命周期服务。
- 负责：
  - 创建任务
  - 写入初始事件
  - 调度本地异步任务
  - 提供任务查询
  - 提供 `resume_job()`
  - 通过 `stream_events()` 提供 SSE 数据源

如果未来要加取消任务、重试任务、任务优先级，这里是第一修改点。

---

### 6.13 `app/workers/`

#### `app/workers/__init__.py`

- 当前仅保留包标记文件。
- 这个目录预留给未来可能的独立后台执行器；当前默认实现不依赖独立 worker。

---


### 6.14 `tests/`

#### `tests/test_canonicalizer.py`

- 测试 URL 规范化是否能去掉跟踪参数和 fragment。

#### `tests/test_discovery.py`

- 测试链接发现是否会过滤外链、自动去重，并保留锚文本。

#### `tests/test_pipeline_utils.py`

- 测试多页面图谱更新结果合并逻辑。

#### `tests/test_url_history.py`

- 测试已访问 URL 是否会带时间戳写入本地文件、在重启后重新加载，并在超过 TTL 后失效。

当前测试还比较少，只覆盖了基础工具函数级别，后续建议继续补：

- `JobService` 创建任务测试
- `CrawlPipeline` 递归流程测试
- `LLMClient` fallback 测试
- `graph_repo` 的 Neo4j 集成测试

---

## 7. 当前项目的真实状态

### 已经完成的部分

- 基础 Python 工程骨架
- 配置系统
- Web 页面和 API
- 本地任务执行
- URL 抓取、正文抽取、链接发现
- LLM 结构化抽取
- Neo4j 基本写入
- Neo4j 持久化任务状态、事件与 checkpoint
- 手动断点续跑
- Neo4j 文件迁移系统
- 文件型 URL 历史判重
- 任务事件流与 SSE 进度展示

### 仍然偏 MVP 的部分

- `LLMClient` fallback 很简单
- 已支持通过 `ENABLE_PLAYWRIGHT=true` 启用浏览器级动态页面抓取
- 没有更强的实体对齐策略
- 没有显式置信度评分
- 没有任务取消、暂停
- 没有更细的站点适配器

---

## 8. 后续 AI 最常见的改动入口

### 如果要新增一个 LLM Tool

1. 在 `app/services/tools/builtins.py` 新增 Tool 类，或拆到新文件。
2. 继承 `BaseTool`。
3. 定义 `name`、`description`、`schema`、`execute()`。
4. 在 `app/core/container.py` 的 `_register_tools()` 里注册。
5. 如果是抓取/写图能力，可在 `app/services/crawl/pipeline.py` 中接入；如果是图检索或抽取链路，优先进入 `app/services/graphrag/`，而不是回退到旧式 LLM Tool 编排。

### 如果要改图谱结构

1. 先改 `app/models/jobs.py` 中相关数据模型。
2. 如果需要改已有图数据，新增 `app/repos/migrations/V<number>__name.cypher`。
3. 再改 `app/repos/graph_repo.py` 的写入 Cypher。
4. 如果需要新业务规则，再改 `app/services/kg/service.py`。

### 如果要增强爬虫

1. `app/services/crawl/fetcher.py`
2. `app/services/crawl/discovery.py`
3. `app/services/crawl/pipeline.py`
4. 如果需要新工具，再进 `app/services/tools/builtins.py`

### 如果要增强前端页面

1. `frontend/src/pages/`
2. `frontend/src/components/ui/`
3. `frontend/src/i18n.ts`
4. 运行 `npm run build` 重新打包静态资源

### 如果要新增 Neo4j migration

1. 在 `app/repos/migrations/` 新增版本更高的 `.cypher` 文件。
2. 文件名必须符合 `V<number>__name.cypher`。
3. 不要修改已执行过的历史 migration。
4. 通过 `python -m app.main` 启动时自动执行，并检查 `MigrationRecord` 是否写入。

---

## 9. 启动方式

### Web 服务

```bash
python -m app.main
```

如果在 Windows 上启用了 Playwright 动态抓取，优先使用这个入口启动。`app/main.py` 内置了自定义 Uvicorn Server，会在服务启动前切换到 `WindowsProactorEventLoopPolicy`，以支持 Playwright 所需的子进程创建。

### 依赖安装

```bash
pip install -e .[dev]
```

---

## 10. 给后续 AI 的一句建议

这个项目目前最适合沿着“保留单体结构，但把抓取、GraphRAG 检索、图谱写入继续分层”这个方向演进。优先保持：

- 更强的实体对齐
- 更可靠的站点适配
- 更完整的测试

这四件事补齐，整体质量会提升最快。
