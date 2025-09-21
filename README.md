# singbox_subcribe

Hysteria2/Hy2 订阅转换为 Sing-box 配置的 FastAPI 服务，支持：
- 解析原始 hy2/hysteria2 URI、多行输入、整段 base64、远端 URL 订阅
- 生成 URL-safe Base64 的 sing-box 配置
- 提供可直接导入的 HTTP 订阅链接与短链持久化
- 基础认证（Bearer Token）、限流（slowapi）、可选路由规则开关

提示：需要 Python 3.12+。

## 项目结构与模块组织
- `main.py`：FastAPI 入口（路由：`/convert`、`/subscription/{config}`、`/subscription/id/{sid}`）。
- `hysteria2_parser.py`：解析 Hysteria2/Hy2 订阅为节点列表。
- `singbox_generator.py`：生成 Sing-box 配置并返回 URL-safe Base64。
- `utils.py`：校验与日志。
- `tests/`：pytest 测试（`tests/test_app.py`）。
- `test_conversion.py`：脚本级冒烟测试示例。
- `verify_output.py`：解码并检查示例配置。
- `requirements.txt`、`Dockerfile`、`docker-compose.yml`：运行与容器化配置。

## 构建、测试与本地开发
- 创建环境并安装依赖：
  - `python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt`
- 启动开发服务：
  - `uvicorn main:app --reload --host 0.0.0.0 --port 8000`
  - 前端页面：启动后访问 `http://localhost:8000/`，可在页面中输入订阅并一键转换、复制结果。
- Docker 运行：
  - `docker compose up --build`
- 冒烟测试（脚本）：
  - `python test_conversion.py`
- Pytest：
  - `pytest -q`
- 校验编码配置：
  - `python verify_output.py`
- 快速接口验证：
  - `curl -X POST http://localhost:8000/convert -H 'Content-Type: application/json' -d '{"subscription":"<你的订阅>"}'`

## 代码风格与命名
- Python 3.12+，4 空格缩进，遵循 PEP 8。
- 命名：模块/函数/变量用 `snake_case`；Pydantic 模型用 `PascalCase`；常量 `UPPER_SNAKE_CASE`。
- 导入顺序：标准库 → 第三方 → 本地，分组空行。
- JSON：用于 base64 的输出采用紧凑、稳定键序（`separators=(',', ':')` + `sort_keys=True`）。

## 测试指南
- 现有包含 `tests/test_app.py`，基于 FastAPI TestClient。
- 重要逻辑建议补充至 `tests/test_<module>.py`（pytest）。
- 覆盖样例：
  - 原始 hy2/hysteria2 URI、多行输入、整段 base64、错误场景（缺少 password、非法 scheme 等）。
  - 解析增强：支持 `#名称` 片段（作为节点名/tag）、更宽松的 SNI 与证书验证参数别名。

## 安全与配置
- 认证：通过环境变量 `API_KEY` 设置，客户端以 `Authorization: Bearer <token>` 访问。
- 限流：`slowapi` 默认 `5/minute`，慎重调整。
- CORS：开发环境 `*`，生产环境请收紧 `allow_origins`。

## 存储与订阅短链
- 短链持久化：使用 SQLite，默认路径 `data/subscriptions.db`。
- 自定义路径：设置 `SUB_DB_PATH` 指定数据库文件位置。
- 订阅接口：
  - 原始：`GET /subscription/{base64}`（可加 `?format=json`）。
  - 短链：`GET /subscription/id/{sid}`（同样支持 `?format=json`）。

## 路由规则与可选开关
- 默认：私网直连；未命中规则走 `selector` 出站（tag: `proxy`）。
- 可选环境变量：
  - `ENABLE_CN_RULES=true`：`geoip:cn`/`geosite:cn` 直连。
  - `ENABLE_ADBLOCK=true`：`geosite:category-ads-all` 走 `block` 出站（自动添加 `block` 出站）。
  - `ENABLE_DOH_DIRECT=true`：常见 DoH 域名直连（dns.google、cloudflare-dns.com 等）。
  - `BYPASS_DOMAINS=example.cn,*.local`：自定义直连域名（逗号分隔）。
  - `PROXY_DOMAINS=example.com`：自定义强制代理域名（逗号分隔）。
  - `DEFAULT_ALPN=h3`：无订阅显式 `alpn` 时默认写入到 TLS（逗号分隔可多值；设为空禁用默认）。
- 提示：`geosite`/`geoip` 规则需客户端侧提供数据库（多数 GUI 客户端内置）。若无，请在客户端配置或手动放置 `geosite.db` 与 `geoip.db`（可从 SagerNet 官方发布页下载）。

## 部署与更新
- Docker Compose（推荐）：
  - 首次启动：`docker compose up --build -d`
  - 查看日志：`docker compose logs -f`
  - 持久化：映射 `./data:/app/data` 保存订阅短链数据库。
- 快速更新：
  - 备份 + 拉取 + 重建：`make update`（或 `bash scripts/update.sh <branch>`，默认 `main`）。
  - 仅重建：`make restart`
  - 手动回滚：`git checkout <tag_or_commit> && docker compose up -d --build`
- 备份数据库：`make backup`（输出 `data/subscriptions.db.bak-<timestamp>`）

## 接口说明
- `POST /convert`
  - Body: `{ "subscription": "<原始/多行/base64/URL 订阅>" }`
  - 返回：`singbox_config`（base64）、`subscription_url`、`subscription_url_short`、`subscription_url_short_json`、`nodes_count`
- `GET /subscription/{base64}`
  - `?format=json|b64`；默认返回 base64 文本，`json` 返回解析后的 JSON。
- `GET /subscription/id/{sid}`
  - 同上，基于短链存取。

## 前端页面
- `GET /`：提供简易页面，输入 Hy2/Hysteria2 节点或订阅并转换。
- 可选填写 API Key（若后端启用认证）。
- 转换后展示：Base64 配置、原始订阅 URL、短链与 JSON 短链，并支持一键复制与 JSON 预览。

## 许可证
本仓库未声明许可证；如需分发或开源，请先补充 LICENSE 并遵循相应条款。
## 规则预设与请求参数

- 预设（可通过环境变量或请求参数启用）：`RULES_PRESET` 支持：`cn_direct`（国内直连、国外代理）、`global_direct`、`global_proxy`、`proxy_domains_only`、`direct_domains_only`。
- 环境变量：`RULES_PRESET`、`ENABLE_CN_RULES`、`ENABLE_ADBLOCK`、`ENABLE_DOH_DIRECT`、`STRICT_GLOBAL_PROXY`、`BYPASS_DOMAINS`、`PROXY_DOMAINS`。
- 请求参数（优先级高于环境变量）：`rules_preset`、`enable_adblock`、`enable_doh_direct`、`strict_global_proxy`、`bypass_domains`、`proxy_domains`。
- 客户端需提供 `geosite.db`/`geoip.db` 才能识别 geosite/geoip 规则。

- 额外参数：default_alpn 用于在节点未指定 alpn 时覆盖默认 ALPN（例如 h3 或 h2,h3）；若未提供，则回退到环境变量 DEFAULT_ALPN（默认为 h3）。
### 示例

- API：`curl -X POST http://<host>:<port>/convert -H 'Content-Type: application/json' -d '{"subscription":"<你的订阅>","rules_preset":"cn_direct","enable_doh_direct":true}'`
- Compose：在 `docker-compose.yml` 中设置：`RULES_PRESET=cn_direct`（已默认）
