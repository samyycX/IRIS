# I.R.I.S. 项目总览

这份文档是给后续接手此项目的 AI 或开发者看的快速上手说明。目标不是替代源码，而是帮助你在最短时间内理解：

- 这个项目是干什么的
- 从哪里开始看
- 一次任务是怎么流转的
- 每个文件大致负责什么
- 如果要继续扩展，应该改哪里

---

## 1. 项目一句话说明

这是一个面向通用知识图谱构建的 Python 单体应用。它支持从 URL、文本指令或实体名发起任务，自动抓取网页、抽取正文、调用 OpenAI 兼容 LLM 生成结构化知识，并把页面、实体、关系写入 Neo4j，同时记录任务日志、事件流、URL 去重状态和实时进度。当前默认 `PROMPT_PROFILE=wuwa`，因此默认提示词行为仍保持与历史项目一致。

---

## 2. 当前技术栈

- Web 层：`FastAPI` + `React (Vite, Shadcn UI)` 纯静态前端
- 抓取层：`httpx` + `Playwright` + `BeautifulSoup` + `trafilatura`
- LLM 层：`openai` Python SDK，兼容 OpenAI 风格接口
- 图数据库：`Neo4j`
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
6. `app/services/llm/client.py`
7. `app/services/tools/builtins.py`
8. `app/web/routes.py` 和 `app/api/routes.py`
9. `app/models/jobs.py`
10. `AI_ONBOARDING_SUMMARY.md` 本文件作为导航

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
   - 查询现有图谱上下文，并调用 LLM 生成摘要、实体关系
  - 让 LLM 结合页面内容、图谱上下文，以及候选链接在图谱中的实体完备度筛选关联链接，并按重要度排序后继续加入队列
   - 调用 `upsert_kg_entity` 写入 Neo4j
   - 持续递归抓取，直到达到深度或页面数量上限
5. `app/repos/event_store.py` 记录阶段事件和任务状态。
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
- URL 历史文件仓库
- 抓取器、抽取器、链接发现器
- LLM 客户端和编排器
- Tool 注册中心和执行器
- 任务服务

以后如果新增组件，优先在这里接线。

### 5.2 `JobService`

`app/services/jobs.py` 只负责任务生命周期：

- 创建任务
- 调度本地异步执行
- 提供任务查询
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

以后要新增“站点适配器工具”、“浏览器渲染工具”、“向量检索工具”、“图谱清洗工具”，都应该沿这个体系扩展。

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
- 包含 `APP_NAME`、`PROMPT_PROFILE` 等运行时配置入口。
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
  - 初始化 URL 历史文件仓库
  - 注册 Tool
  - 确保 Neo4j 约束存在
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

- 当前任务状态与事件流的内存实现。
- 维护：
  - 任务摘要
  - 原始请求
  - 事件列表
  - 每个任务访问过的 URL
  - 全局访问过的 URL
- 这是当前“进度页可见状态”的事实来源。
- Neo4j 里的 `CrawlJob` 现在会在任务开始和任务结束时同步一次最终结果快照，用于持久化任务 summary、统计信息和详细修改记录；运行中的实时状态仍以这里为准。

注意：它目前是内存实现，服务重启后会丢失。未来如果要持久化任务日志，应先替换这里。

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
  - 写入 `Page`、`CrawlJob`、`Entity`
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
  - 调用 Tool 抓取网页
  - 调用 LLM 做总结、抽取与关联链接排序
  - 按排序结果入队新发现链接
  - 调用图谱写入
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

- 当前页面结构化抽取的系统提示词与 prompt preset 定义。
- 默认 `wuwa` preset 会保留历史鸣潮版 prompt 文本，`generic` preset 提供更中性的提示词。
- 约束 LLM 输出 JSON，包含页面摘要与实体关系。

#### `app/services/llm/client.py`

- OpenAI 兼容客户端封装。
- 负责：
  - 发起聊天补全请求
  - 要求返回 JSON
  - 把结果解析为 `ExtractedEntity`
  - 当没有配置 API Key 或模型返回异常时，自动走 fallback 抽取

当前 fallback 很简单，只会拿页面标题和前几行文本做保底摘要，适合开发阶段，但不适合生产质量。

#### `app/services/llm/orchestrator.py`

- LLM 编排层。
- 先调用 `query_neo4j_context` 取现有图谱上下文，并为候选链接补充“对应实体是否已在图谱中较完整”的检索结果，再调用 `LLMClient`。
- 把 LLM 结果重新包装为 `PageExtraction`。

这层是以后做“多轮工具调用”和“更智能上下文拼接”的最佳位置。

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
  - `query_neo4j_context`
  - `upsert_kg_entity`
- 其中 `upsert_kg_entity` 现在既能新增关系，也能按实体描述删除指定 `RELATED_TO` 关系。

这是当前“可扩展能力”的主要锚点。新增 Tool 就按这里的模式继续写。

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
- 文件型 URL 历史判重
- 任务事件流与 SSE 进度展示

### 仍然偏 MVP 的部分

- `event_store` 还是内存实现，重启会丢任务历史
- `LLMClient` fallback 很简单
- 已支持通过 `ENABLE_PLAYWRIGHT=true` 启用浏览器级动态页面抓取
- 没有更强的实体对齐策略
- 没有显式置信度评分
- 没有任务取消、恢复、暂停
- 没有更细的站点适配器

---

## 8. 后续 AI 最常见的改动入口

### 如果要新增一个 LLM Tool

1. 在 `app/services/tools/builtins.py` 新增 Tool 类，或拆到新文件。
2. 继承 `BaseTool`。
3. 定义 `name`、`description`、`schema`、`execute()`。
4. 在 `app/core/container.py` 的 `_register_tools()` 里注册。
5. 在 `app/services/llm/orchestrator.py` 或 `app/services/crawl/pipeline.py` 中接入调用。

### 如果要改图谱结构

1. 先改 `app/models/jobs.py` 中相关数据模型。
2. 再改 `app/repos/graph_repo.py` 的写入 Cypher。
3. 如果需要新业务规则，再改 `app/services/kg/service.py`。

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

这个项目目前最适合沿着“保留单体结构，但把业务规则继续往服务层和 Tool 层拆”这个方向演进。不要急着引入复杂框架，先把：

- 任务事件持久化
- 更强的实体对齐
- 更可靠的站点适配
- 更完整的测试

这四件事补齐，整体质量会提升最快。
