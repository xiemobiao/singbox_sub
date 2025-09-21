import os
import sqlite3
import time
import secrets
import uvicorn
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

# Pydantic模型
class ConvertRequest(BaseModel):
    subscription: str

# FastAPI app
app = FastAPI(title="Hysteria2 to Sing-box Converter")

# 速率限制
limiter = Limiter(key_func=get_remote_address, default_limits=["5/minute"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# CORS - 生产环境请配置具体域名
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发环境允许所有，生产环境请指定具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 可选API key中间件
API_KEY = os.getenv("API_KEY", "")
if API_KEY:
    @app.middleware("http")
    async def api_key_auth(request: Request, call_next):
        auth = request.headers.get("Authorization")
        if not auth or not auth.startswith("Bearer ") or auth[7:] != API_KEY:
            raise HTTPException(status_code=401, detail="无效的API密钥")
        return await call_next(request)

# SQLite 持久化存储：短链 -> base64 配置
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
    """保存配置并返回短ID（持久化）。"""
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
            # 短碰撞则重试
            continue
    raise HTTPException(status_code=500, detail="生成短链接失败")


def load_subscription(sid: str) -> str | None:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute("SELECT encoded FROM subscriptions WHERE sid = ?", (sid,))
        row = cur.fetchone()
        return row[0] if row else None


_ensure_db()

# 静态页面与资源
static_dir = os.path.join(os.path.dirname(__file__), 'static')
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def index_page():
    """提供简单的前端页面用于输入并转换订阅。"""
    index_path = os.path.join(static_dir, 'index.html')
    if os.path.isfile(index_path):
        return FileResponse(index_path, media_type="text/html; charset=utf-8")
    # 兜底：未找到静态文件时返回提示
    return PlainTextResponse("Frontend not found. Please ensure static/index.html exists.")

@app.post("/convert")
@limiter.limit("5/minute")
async def convert(body: ConvertRequest, request: Request):
    """
    转换Hysteria2订阅到Sing-box配置。
    返回base64编码的配置和HTTP订阅URL。
    """
    try:
        validate_subscription_format(body.subscription)
        nodes = parse_hysteria2_subscription(body.subscription)
        singbox_config = generate_singbox_url(nodes)

        # 生成HTTP订阅URL
        host = request.headers.get("x-forwarded-host") or request.headers.get("host", "localhost:8000")
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme or "http")
        subscription_url = f"{scheme}://{host}/subscription/{singbox_config}"

        # 生成短链并存储
        sid = save_subscription(singbox_config)  # 短且 URL 安全
        subscription_url_short = f"{scheme}://{host}/subscription/id/{sid}"

        log_info(f"成功转换 {len(nodes)} 个节点")
        return {
            "singbox_config": singbox_config,
            "subscription_url": subscription_url,
            "subscription_url_short": subscription_url_short,
            "subscription_url_short_json": subscription_url_short + "?format=json",
            "nodes_count": len(nodes)
        }
    except ValueError as e:
        log_error(f"转换错误: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log_error(f"内部错误: {e}")
        raise HTTPException(status_code=500, detail="内部服务器错误")

@app.get("/subscription/{config}")
async def get_subscription(config: str, request: Request):
    """
    返回Sing-box配置，用于HTTP订阅。
    """
    try:
        # 验证config是有效的base64
        import base64
        import json
        pad = (-len(config)) % 4
        if pad:
            base64.urlsafe_b64decode(config + ('=' * pad))
        else:
            base64.urlsafe_b64decode(config)
        # 根据格式返回
        fmt = (request.query_params.get("format") or "b64").lower()
        if fmt in ("json", "application/json"):
            raw = base64.urlsafe_b64decode(config + ('=' * pad) if pad else config)
            try:
                obj = json.loads(raw)
                return JSONResponse(content=obj, media_type="application/json")
            except json.JSONDecodeError:
                # 若不是 JSON，则回退为纯文本（兼容性）
                return PlainTextResponse(content=raw.decode('utf-8', errors='ignore'), media_type="text/plain; charset=utf-8")
        # 默认返回 base64 文本，便于客户端直接识别
        return PlainTextResponse(content=config, media_type="text/plain; charset=utf-8")
    except Exception:
        raise HTTPException(status_code=400, detail="无效的配置")

@app.get("/subscription/id/{sid}")
async def get_subscription_by_id(sid: str, request: Request):
    """
    通过短ID返回Sing-box配置，支持 format=json。
    """
    try:
        import base64, json
        encoded = load_subscription(sid)
        if not encoded:
            raise HTTPException(status_code=404, detail="未找到订阅")
        pad = (-len(encoded)) % 4
        # 验证 base64
        base64.urlsafe_b64decode(encoded + ('=' * pad) if pad else encoded)

        fmt = (request.query_params.get("format") or "b64").lower()
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
    # 初始化基础日志配置
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    uvicorn.run(app, host="0.0.0.0", port=port)
