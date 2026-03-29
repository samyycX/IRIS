# I.R.I.S.

一个面向通用知识图谱采集、总结与更新的 Python 单体应用。

## 核心能力

- 输入 URL 或自然语言指令，创建后台采集任务。
- 递归发现站内新链接，自动做 URL 去重。
- 抽取页面正文并调用 OpenAI 兼容接口生成结构化知识。
- 将页面证据、实体语义与关系更新到 Neo4j。
- 在 Web 页面实时查看进度、事件日志与图谱更新摘要。

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

如果希望即使 URL 已在历史记录或 Neo4j 中出现过也重新抓取，可在 `.env` 中设置：

```bash
SKIP_HISTORY_SEEN_URLS=false
```

## Prompt 配置

LLM prompt 现在可以通过 `.env` 中的 `PROMPT_PROFILE` 切换。

- 默认值 `wuwa` 会继续使用当前仓库中的原始鸣潮版 prompt，以保持现有行为不变。
- 如果需要更中性的抽取提示，可改为：

```bash
PROMPT_PROFILE=generic
```

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
