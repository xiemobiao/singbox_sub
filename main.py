import os
import sqlite3
import time
import secrets
import uvicorn
from typing import Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from hysteria2_parser import parse_hysteria2_subscription
from singbox_generator import generate_singbox_url
from utils import validate_subscription_format, log_error, log_info


# Pydantic 模型
class ConvertRequest(BaseModel):
    subscription: str
    # 可选：规则预设；前端勾选“国内直连（国外代理）”时传入 'cn_direct'
    rules_preset: Optional[str] = None
    enable_adblock: Optional[bool] = None
    enable_doh_direct: Optional[bool] = None
    strict_global_proxy: Optional[bool] = None
    bypass_domains: Optional[str] = None
    proxy_domains: Optional[str] = None
    use_rule_set: Optional[bool] = None
    # 可选：规则集基础地址（覆盖服务端 RULE_SET_BASE）
    rule_set_base: Optional[str] = None
    # 默认为空；当节点未提供 alpn 时可用逗号分隔覆盖，如 "h2,h3"
    default_alpn: Optional[str] = None

# FastAPI app
app = FastAPI(title="Hysteria2 to Sing-box Converter")


# 限流中间件
limiter = Limiter(key_func=get_remote_address, default_limits=["5/minute"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


# CORS 配置（生产建议收紧）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 可选 API Key 校验
API_KEY = os.getenv("API_KEY", "")
if API_KEY:
    # 放行无需鉴权的路径：前端首页/静态资源/文档与 OpenAPI，以及订阅获取接口
    SAFE_PATHS = {"/", "/docs", "/openapi.json", "/redoc", "/favicon.ico"}

    @app.middleware("http")
    async def api_key_auth(request: Request, call_next):
        path = (request.url.path or "/").rstrip("/") or "/"

        # 放行无需鉴权路径与 CORS 预检
        if (
            path in SAFE_PATHS
            or path.startswith("/static")
            or path.startswith("/subscription")
            or request.method == "OPTIONS"
        ):
            return await call_next(request)

        # 其余请求需要 Bearer Token
        auth = request.headers.get("Authorization")
        if not auth or not auth.startswith("Bearer ") or auth[7:] != API_KEY:
            raise HTTPException(status_code=401, detail="无效的 API 密钥")
        return await call_next(request)


# SQLite 持久化存储：sid -> base64 配置
DB_PATH = os.getenv("SUB_DB_PATH", os.path.join("data", "subscriptions.db"))


def _ensure_db():
    dirpath = os.path.dirname(DB_PATH)
    if dirpath:
        os.makedirs(dirpath, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
                sid TEXT PRIMARY KEY,
                encoded TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )
        conn.commit()


def save_subscription(encoded: str) -> str:
    """保存配置并返回短 ID，带冲突重试"""
    for _ in range(5):
        sid = secrets.token_urlsafe(6).rstrip('=')
        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute(
                    "INSERT INTO subscriptions (sid, encoded, created_at) VALUES (?, ?, ?)",
                    (sid, encoded, int(time.time())),
                )
                conn.commit()
            return sid
        except sqlite3.IntegrityError:
            continue
    raise HTTPException(status_code=500, detail="生成短链接失败")


def load_subscription(sid: str) -> str | None:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute("SELECT encoded FROM subscriptions WHERE sid = ?", (sid,))
        row = cur.fetchone()
        return row[0] if row else None


_ensure_db()


# 静态页面与前端资源
static_dir = os.path.join(os.path.dirname(__file__), 'static')
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def index_page():
    """返回前端首页 static/index.html，若缺失则提示"""
    index_path = os.path.join(static_dir, 'index.html')
    if os.path.isfile(index_path):
        return FileResponse(index_path, media_type="text/html; charset=utf-8")
    return PlainTextResponse("Frontend not found. Please ensure static/index.html exists.")


@app.post("/convert")
@limiter.limit("5/minute")
async def convert(body: ConvertRequest, request: Request):
    """
    将 Hysteria2 订阅转换为 Sing-box 配置（URL 安全 Base64），并返回订阅 URL 与短链。
    """
    try:
        validate_subscription_format(body.subscription)
        nodes = parse_hysteria2_subscription(body.subscription)
        options = {
            "rules_preset": body.rules_preset,
            "enable_adblock": body.enable_adblock,
            "enable_doh_direct": body.enable_doh_direct,
            "strict_global_proxy": body.strict_global_proxy,
            "bypass_domains": body.bypass_domains,
            "proxy_domains": body.proxy_domains,
            "use_rule_set": body.use_rule_set,
            "rule_set_base": body.rule_set_base,
            "default_alpn": body.default_alpn,
        }
        options = {k: v for k, v in options.items() if v is not None}
        singbox_config = generate_singbox_url(nodes, options if options else None)

        # 生成 HTTP 订阅 URL（考虑反代头）
        host = request.headers.get("x-forwarded-host") or request.headers.get("host", "localhost:8000")
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme or "http")
        subscription_url = f"{scheme}://{host}/subscription/{singbox_config}"

        # 生成短链并存储
        sid = save_subscription(singbox_config)
        subscription_url_short = f"{scheme}://{host}/subscription/id/{sid}"

        log_info(f"成功转换 {len(nodes)} 个节点")
        return {
            "singbox_config": singbox_config,
            "subscription_url": subscription_url,
            "subscription_url_short": subscription_url_short,
            "subscription_url_short_json": subscription_url_short + "?format=json",
            "nodes_count": len(nodes),
        }
    except ValueError as e:
        log_error(f"转换错误: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log_error(f"内部错误: {e}")
        raise HTTPException(status_code=500, detail="内部服务器错误")


@app.get("/subscription/{config}")
async def get_subscription(config: str, request: Request):
    """返回 Sing-box 配置；支持 ?format=json 直接返回 JSON"""
    try:
        # 验证 base64 是否可解码
        import base64
        import json
        pad = (-len(config)) % 4
        if pad:
            base64.urlsafe_b64decode(config + ('=' * pad))
        else:
            base64.urlsafe_b64decode(config)

        # 格式处理：若无 format 参数，根据 Accept/UA 选择默认
        fmt_qs = request.query_params.get("format")
        if fmt_qs:
            fmt = fmt_qs.lower()
        else:
            accept = (request.headers.get("accept") or "").lower()
            ua = (request.headers.get("user-agent") or "").lower()
            fmt = "json" if ("application/json" in accept or "sing-box" in ua) else "b64"
        if fmt in ("json", "application/json"):
            raw = base64.urlsafe_b64decode(config + ('=' * pad) if pad else config)
            try:
                obj = json.loads(raw)
                return JSONResponse(content=obj, media_type="application/json")
            except json.JSONDecodeError:
                return PlainTextResponse(content=raw.decode('utf-8', errors='ignore'), media_type="text/plain; charset=utf-8")
        return PlainTextResponse(content=config, media_type="text/plain; charset=utf-8")
    except Exception:
        raise HTTPException(status_code=400, detail="无效的订阅配置")


@app.get("/subscription/id/{sid}")
async def get_subscription_by_id(sid: str, request: Request):
    """通过短 ID 返回配置；支持 ?format=json"""
    try:
        import base64, json
        encoded = load_subscription(sid)
        if not encoded:
            raise HTTPException(status_code=404, detail="未找到订阅")
        pad = (-len(encoded)) % 4
        # 验证 base64
        base64.urlsafe_b64decode(encoded + ('=' * pad) if pad else encoded)

        # 默认根据 Accept/UA 选择 json，除非 URL 明确指定 format
        fmt_qs = request.query_params.get("format")
        if fmt_qs:
            fmt = fmt_qs.lower()
        else:
            accept = (request.headers.get("accept") or "").lower()
            ua = (request.headers.get("user-agent") or "").lower()
            fmt = "json" if ("application/json" in accept or "sing-box" in ua) else "b64"
        if fmt in ("json", "application/json"):
            raw = base64.urlsafe_b64decode(encoded + ('=' * pad) if pad else encoded)
            try:
                obj = json.loads(raw)
                return JSONResponse(content=obj, media_type="application/json")
            except json.JSONDecodeError:
                return PlainTextResponse(content=raw.decode('utf-8', errors='ignore'), media_type="text/plain; charset=utf-8")
        return PlainTextResponse(content=encoded, media_type="text/plain; charset=utf-8")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="内部服务器错误")


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    # 启动本地开发服务器（日志简化）
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    uvicorn.run(app, host="0.0.0.0", port=port)
