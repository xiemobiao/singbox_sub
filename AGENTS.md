# Repository Guidelines

本指南帮助贡献者在 singbox_subcribe FastAPI 服务上高效协作。

## 项目结构与模块组织
- `main.py`：FastAPI 入口（路由：`/convert`、`/subscription/{config}`）。
- `hysteria2_parser.py`：解析 Hysteria2/Hy2 订阅为节点列表。
- `singbox_generator.py`：生成 Sing-box 配置并返回 URL-safe Base64。
- `utils.py`：校验与日志。
- `test_conversion.py`：解析/生成的冒烟测试。
- `verify_output.py`：解码并检查示例配置。
- `requirements.txt`、`Dockerfile`、`docker-compose.yml`：运行与容器化配置。

## 构建、测试与本地开发
- 创建环境并安装：`python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt`
- 启动开发服务：`uvicorn main:app --reload --host 0.0.0.0 --port 8000`
- Docker 运行：`docker compose up --build`
- 冒烟测试：`python test_conversion.py`
- 校验编码配置：`python verify_output.py`
- 快速接口验证：
  - `curl -X POST http://localhost:8000/convert -H 'Content-Type: application/json' -d '{"subscription":"<你的订阅>"}'`

## 代码风格与命名
- Python 3.12+，4 空格缩进，遵循 PEP 8。
- 命名：模块/函数/变量用 `snake_case`；Pydantic 模型用 `PascalCase`；常量 `UPPER_SNAKE_CASE`。
- 导入顺序：标准库 → 第三方 → 本地，分组空行。
- JSON：用于 base64 的输出应尽量紧凑、稳定键序。

## 测试指南
- 现有为脚本级测试；新增重要逻辑请按 `tests/test_<module>.py` 补充单测（建议 pytest）。
- 覆盖样例：原始 hy2/hysteria2 URI、多行输入、整段 base64、错误场景（缺少 password、非法 scheme 等）。

## 提交与 Pull Request
- 提交信息使用祈使句、简洁主题（≤72 字符），必要时补充动机与影响。
  - 例：`fix(parser): 处理无填充的 base64`
- PR 需包含：问题与方案概述、测试步骤（curl/脚本输出）、配置改动（`API_KEY`、CORS）及关联 issue。

## 安全与配置
- 认证：通过环境变量设置 `API_KEY`，客户端以 `Authorization: Bearer <token>` 访问。
- 限流：`slowapi` 默认 `5/minute`，慎重调整。
- CORS：生产环境请收紧 `allow_origins`。

## 存储与订阅短链
- 短链持久化：使用 SQLite，默认路径 `data/subscriptions.db`。
- 自定义路径：设置环境变量 `SUB_DB_PATH` 指定数据库文件位置。
- 订阅接口：
  - 原始：`GET /subscription/{base64}`（可加 `?format=json`）。
  - 短链：`GET /subscription/id/{sid}`（同样支持 `?format=json`）。

## 路由规则与可选开关
- 默认：私网直连；未命中规则走 `selector` 出站（tag: `proxy`）。
- 可选环境变量：
  - `ENABLE_CN_RULES=true`：`geoip:cn`/`geosite:cn` 直连。
  - `ENABLE_ADBLOCK=true`：`geosite:category-ads-all` 走 `block` 出站。
  - `ENABLE_DOH_DIRECT=true`：常见 DoH 域名直连（dns.google、cloudflare-dns.com 等）。
  - `BYPASS_DOMAINS=example.cn,*.local`：自定义直连域名（逗号分隔）。
  - `PROXY_DOMAINS=example.com`：自定义强制代理域名（逗号分隔）。
- 提示：`geosite`/`geoip` 规则需客户端侧提供数据库（多数 GUI 客户端内置）。若无，请在客户端配置或手动放置 `geosite.db` 与 `geoip.db`（可从 SagerNet 官方发布页下载）。

## 部署与更新建议
- Docker Compose（推荐）：
  - 首次启动：`docker compose up --build -d`
  - 查看日志：`docker compose logs -f`
  - 持久化：映射 `./data:/app/data` 保存订阅短链数据库。
- 快速更新：
  - 备份 + 拉取 + 重建：`make update`（或 `bash scripts/update.sh <branch>`，默认 `main`）。
  - 仅重建：`make restart`
  - 手动回滚：`git checkout <tag_or_commit> && docker compose up -d --build`
- 备份数据库：`make backup`（输出 `data/subscriptions.db.bak-<timestamp>`）
