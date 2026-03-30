# I.R.I.S.

一个面向通用知识图谱采集、总结与更新的 Python 单体应用。

## 核心能力

- 输入 URL 或自然语言指令，创建后台采集任务。
- 递归发现站内新链接，自动做 URL 去重。
- 抽取页面正文并调用 OpenAI 兼容接口生成结构化知识。
- 将页面证据、实体语义与关系更新到 Neo4j。
- 在 Web 页面实时查看进度、事件日志与图谱更新摘要。
- Job 状态、事件、checkpoint 持久化到 Neo4j `CrawlJob`，支持服务重启后的手动续跑。

## 快速开始

1. 复制 `.env.example` 为 `.env` 并填入配置。
2. 安装依赖：

```bash
pip install -e .[dev]
playwright install chromium
```

3. 构建前端：

```bash
cd frontend
npm install
npm run build
cd ..
```

4. 启动 Web 服务：

```bash
python -m app.main
```

默认情况下，应用使用进程内后台任务执行器，已访问 URL 会以 JSON 结构持久化到 `VISITED_URLS_FILE` 指定的位置，并记录最近访问时间，无需 Redis。历史 URL 默认只会在 `10` 天内跳过；超过这个时间会允许重新抓取。这个窗口可通过 `.env` 中的 `VISITED_URL_TTL_DAYS` 调整。

启动时应用还会自动执行 Neo4j 图数据迁移。迁移文件位于 `app/repos/migrations/`，命名格式为 `V<number>__name.cypher`。系统会按版本顺序执行，并把执行记录写入 Neo4j 的 `MigrationState` / `MigrationRecord` 节点。

如果希望即使 URL 已在历史记录或 Neo4j 中出现过也重新抓取，可在 `.env` 中设置：

```bash
SKIP_HISTORY_SEEN_URLS=false
```

如果希望 URL 采集任务在本次任务确实写入了实体或关系后，自动创建全文和向量索引的 `backfill` 任务，可在 `.env` 中开启：

```bash
AUTO_BACKFILL_INDEXES_AFTER_CRAWL=true
```

开启后，采集任务完成时会根据本次累计图谱变更自动触发索引补全，只处理缺失或过期的索引数据；若当前没有实际图谱更新，则不会额外创建索引任务。

## Job 持久化与续跑

前端首页和任务详情页显示的 job 列表，现在以 Neo4j 中的 `CrawlJob` 为事实来源，而不是进程内临时状态。

- `running`、`completed`、`failed`、`interrupted` 等状态都会持久化到 `CrawlJob`
- URL 任务的待处理队列、已访问 URL、事件流和 checkpoint 会持续写回 Neo4j
- 服务重启后，未完成任务会被标记为 `interrupted`
- 用户可以通过前端按钮或 `POST /api/jobs/{job_id}/resume` 手动继续任务

这意味着只要 Neo4j 数据还在，任务历史和可恢复上下文就不会因为服务重启而丢失。

## Neo4j Migration

所有 Neo4j 结构升级都走文件迁移，不再把某个节点类型的修复逻辑硬编码在 Python 里。

- 迁移目录：`app/repos/migrations/`
- 文件命名：`V<number>__name.cypher`
- 执行时机：应用启动时自动检查并执行未应用版本
- 版本记录：Neo4j 中的 `MigrationState` / `MigrationRecord`

新增迁移时，直接放一个新的 `.cypher` 文件即可。不要修改已经执行过的旧迁移文件；如果要修正历史结构，应新增更高版本的迁移。

## 主题过滤配置

LLM 现在统一使用一套 prompt，不再通过 `PROMPT_PROFILE` 切换。

如果希望采集器只保留某个主题下的页面，可以在 `.env` 中配置：

```bash
KNOWLEDGE_THEME=鸣潮角色、剧情、组织与世界观
```

当 `KNOWLEDGE_THEME` 非空时，采集器会先判断页面是否与该主题相关；不相关的页面不会写入数据库，也不会抽取任何实体或关系。

## 动态页面抓取

当目标站点依赖前端渲染时，可在 `.env` 中开启：

```bash
ENABLE_PLAYWRIGHT=true
```

开启后，抓取器会直接使用 Playwright 启动 Chromium 访问页面，并在 DOM 初始加载后额外等待、自动滚动，以尽可能拿到懒加载和脚本注入后的内容。

对于 `Fandom` 这类经常出现 cookie / consent 弹层的站点，浏览器抓取默认会自动尝试点击常见的同意按钮。这个行为可通过 `.env` 控制：

```bash
BROWSER_AUTO_ACCEPT_CONSENT=true
```

如果你想排查站点原始拦截页面，也可以临时关闭：

```bash
BROWSER_AUTO_ACCEPT_CONSENT=false
```

在 Windows 上如果启用了 `ENABLE_PLAYWRIGHT=true`，请优先使用 `python -m app.main` 启动。这个入口会使用自定义的 Uvicorn Server，并在服务启动前切换到 `WindowsProactorEventLoopPolicy`，避免 Playwright 因子进程创建失败而报 `NotImplementedError`。
