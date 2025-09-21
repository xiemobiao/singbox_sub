# 仓库指南

基于 FastAPI 的服务，将 Hysteria2/Hy2 订阅转换为 Sing-box 配置，并持久化短链接。

## 项目结构与模块
- `main.py`：FastAPI 入口；路由 `/convert`、`/subscription/{config}`。
- `hysteria2_parser.py`：解析 Hysteria2/Hy2 订阅为节点列表。
- `singbox_generator.py`：构建 Sing-box 配置；返回 URL 安全的 Base64。
- `utils.py`：校验与日志辅助函数。
- `test_conversion.py`：解析/生成的冒烟测试。
- `verify_output.py`：解码并检查示例配置。
- `requirements.txt`、`Dockerfile`、`docker-compose.yml`。
- 存储：SQLite `data/subscriptions.db`（可通过环境变量 `SUB_DB_PATH` 覆盖）。

## 构建、测试与开发
- 初始化：`python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt`
- 运行开发服务器：`uvicorn main:app --reload --host 0.0.0.0 --port 8000`
- Docker：`docker compose up --build`
- 冒烟测试：`python test_conversion.py`
- 验证示例：`python verify_output.py`
- 快速 API 检查：`curl -X POST http://localhost:8000/convert -H 'Content-Type: application/json' -d '{"subscription":"<your subscription>"}'`

## 编码风格与命名
- Python 3.12+，4 空格缩进，遵循 PEP 8。
- 命名：`snake_case`（模块/函数/变量）、`PascalCase`（Pydantic 模型）、`UPPER_SNAKE_CASE`（常量）。
- 导入顺序：标准库 → 第三方 → 本地，并在分组之间留空行。
- Base64 输出中的 JSON 应当紧凑，且键顺序稳定。

## 测试指南
- 现有脚本作为冒烟测试使用；新增逻辑请在 `tests/test_<module>.py` 中添加 pytest 用例。
- 覆盖范围：原始 hy2/hysteria2 URI、多行输入、整段 Base64、以及错误情况（缺少密码、无效 scheme）。
- 运行：`pytest`（如已添加）或使用上述脚本。

## 提交与 Pull Request 指南
- 提交信息：使用祈使语气，主题简洁（≤72 字符）。必要时采用 Conventional Commits，例如 `fix(parser): handle base64 without padding`。
- PR 内容应包括：问题与解决方案摘要、测试步骤（curl/脚本输出）、配置变更（如 `API_KEY`、CORS），以及关联的 issue。

## 安全与配置建议
- 认证通过 `API_KEY`；客户端通过 `Authorization: Bearer <token>` 发送。
- 使用 `slowapi` 进行限流（默认每分钟 5 次）。
- 生产环境收紧 CORS 策略。
- 可选路由/规则开关：`ENABLE_CN_RULES`、`ENABLE_ADBLOCK`、`ENABLE_DOH_DIRECT`、`BYPASS_DOMAINS`、`PROXY_DOMAINS`（客户端需提供 `geosite.db`/`geoip.db`）。

## 路由与短链
- 订阅获取：`GET /subscription/{base64}` 与 `GET /subscription/id/{sid}`（支持 `?format=json`）。
- 短链持久化存储于 SQLite：`data/subscriptions.db`。
