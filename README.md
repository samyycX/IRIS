<div align="center">
<h1>I.R.I.S.</h1>
<small><b>Intelligent Retrieval & Indexing System</b></small>
</div>

一个易用的网络信息自动采集，索引和查询系统。

## 核心能力

- 输入 URL 或自然语言指令，创建后台采集任务。
- 递归发现站内新链接，自动做 URL 去重。
- 抽取页面正文并调用 OpenAI 兼容接口生成结构化知识。
- 将页面证据、实体语义与关系更新到 Neo4j。
- 在 Web 页面实时查看进度、事件日志与图谱更新摘要。
- Job 状态、事件、checkpoint 持久化到 Neo4j `CrawlJob`，支持服务重启后的手动续跑。

## 快速开始

1. 安装环境：
	```bash
	pip install -e .[dev]
	playwright install chromium
	```

2. 构建前端：
	```bash
	cd frontend
	npm install
	npm run build
	cd ..
	```

3. 配置环境变量 `IRIS_PASSWORD` 为面板的密码（建议使用强密码）。也可以在本地环境下使用 `IRIS_PASSWORD_BYPASS=1` 进行跳过。

5. 启动面板：
	```bash
	python -m app.main
	```