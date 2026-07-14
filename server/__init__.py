"""Server 模块 — Web 服务 + 数据持久化

内部模块:
    server.main        → FastAPI 应用入口
    server.db          → SQLite 会话/消息管理
    server.compressor  → 上下文压缩 (Token 计数 + LLM 摘要)
    server.history     → 趋势数据环形缓冲区
    server.sse         → 实时性能指标 SSE 推送
    server.logger      → Agent 运行日志 (ANSI 彩色输出)
    server.config      → 路径常量 + 运行参数
    server.routes      → API 路由 (chat / device / sessions)
"""

from server.config import (
    PROJECT_ROOT, WEB_DIR, DB_PATH,
    SCREENSHOT_DIR, DUMPS_DIR,
    COMPRESS_THRESHOLD, KEEP_RECENT_TURNS,
    TREND_BUFFER_SIZE,
    METRICS_INTERVAL, METRICS_MIN_INTERVAL,
)

__all__ = [
    "PROJECT_ROOT",
    "WEB_DIR",
    "DB_PATH",
    "SCREENSHOT_DIR",
    "DUMPS_DIR",
    "COMPRESS_THRESHOLD",
    "KEEP_RECENT_TURNS",
    "TREND_BUFFER_SIZE",
    "METRICS_INTERVAL",
    "METRICS_MIN_INTERVAL",
]
