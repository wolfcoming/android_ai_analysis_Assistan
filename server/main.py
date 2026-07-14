"""FastAPI 应用入口 — 安卓开发助手 API Server

启动流程:
    1. 设置 Python 搜索路径
    2. 创建 FastAPI 应用
    3. 注册 CORS 中间件
    4. 注册 API 路由
    5. 挂载前端静态文件
    6. 初始化数据库
"""

import sys
import os

# 确保项目根目录在 Python path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from server.routes.chat import router as chat_router
from server.routes.device import router as device_router
from server.routes.sessions import router as sessions_router
from server.sse import sse_endpoint
from server.db import init_db
from server.config import WEB_DIR, ensure_directories

# ============================================================
# 创建 FastAPI 应用
# ============================================================
app = FastAPI(
    title="安卓开发助手 API",
    version="0.3.0",
    description="基于 LangChain + ADB 的智能安卓性能诊断助手",
)


# ============================================================
# 生命周期事件
# ============================================================
@app.on_event("startup")
async def startup():
    """服务启动时的初始化操作"""
    print("\n" + "=" * 60)
    print("  🚀 安卓开发助手正在启动...")
    print("=" * 60)

    # 1. 初始化数据目录
    ensure_directories()
    print(f"  📁 截图目录: {WEB_DIR}/screenshots/")
    print(f"  📁 Dump 目录: {WEB_DIR}/dumps/")

    # 2. 初始化数据库
    init_db()

    print("=" * 60)
    print("  ✅ 服务启动完成，等待连接...")
    print("=" * 60 + "\n")


# ============================================================
# 中间件
# ============================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# API 路由注册
# ============================================================
app.include_router(chat_router, tags=["对话"])
app.include_router(device_router, tags=["设备"])
app.include_router(sessions_router, tags=["会话"])

# SSE 实时指标端点
app.add_api_route("/api/stream", sse_endpoint, methods=["GET"], tags=["实时"])

# 健康检查
@app.get("/api/health", tags=["系统"])
async def health():
    return {"status": "ok", "service": "安卓开发助手 API v0.3"}

# ============================================================
# 静态文件挂载（必须在所有 API 路由之后）
# ============================================================
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="static")

print("  🌐 API 路由已注册: /api/chat, /api/sessions, /api/device/*, /api/stream, /api/health")
print("  📄 前端入口: http://localhost:8783/")
