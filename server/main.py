"""FastAPI 应用入口"""
import sys
import os

# 确保项目根目录在 Python path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from server.routes.chat import router as chat_router
from server.routes.device import router as device_router
from server.sse import sse_endpoint

app = FastAPI(title="安卓开发助手 API", version="0.1.0")

# CORS 允许前端跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(chat_router)
app.include_router(device_router)

# SSE 端点
app.add_api_route("/api/stream", sse_endpoint, methods=["GET"])

@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "安卓开发助手"}

# 静态文件（前端）— 必须在所有 API 路由之后挂载
web_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
app.mount("/", StaticFiles(directory=web_dir, html=True), name="static")
