"""SSE 实时指标 — 每 2 秒采集并推送性能数据

架构:
    MetricsCollector  — 数据采集器（ADB 命令 → 结构化数据）
    sse_endpoint      — SSE 端点（定时推送 → 前端 EventSource）

数据流:
    前端 EventSource → GET /api/stream
      → while True (每 2 秒):
          → collect_metrics(package_name)
          → 内存 + CPU + 帧率
          → 写入趋势缓存
          → yield SSE event
"""

import asyncio
import json
import time
from typing import Optional

from fastapi import Request
from fastapi.responses import StreamingResponse

from agent.tools.adb_app import get_app_memory_raw, get_foreground_app
from agent.tools.adb_perf import get_cpu_info_raw, get_frame_info_raw
from server.history import get_trend_cache
from server.config import METRICS_INTERVAL, METRICS_MIN_INTERVAL


class MetricsCollector:
    """
    性能指标采集器。

    负责:
        1. 调用 ADB 命令采集内存/CPU/帧率数据
        2. 防重叠保护（两次采集间隔 >= 1.5 秒）
        3. 帧率增量计算（对比前后两次采集的差值）
        4. 写入趋势缓存
    """

    def __init__(self):
        self._last_time: float = 0
        self._lock = asyncio.Lock()
        self._frame_totals: dict = {}  # {package_name: (total_frames, janky_frames)}

    async def collect(self, package_name: str) -> Optional[dict]:
        """采集一次完整的性能指标

        Args:
            package_name: 目标应用包名

        Returns:
            指标字典，若防重叠跳过则返回 None
        """
        # ===== 防重叠保护 =====
        async with self._lock:
            now = time.time()
            if now - self._last_time < METRICS_MIN_INTERVAL:
                return None
            self._last_time = now

        loop = asyncio.get_event_loop()
        data = {"timestamp": now}

        # 内存采集
        try:
            mem = await loop.run_in_executor(None, get_app_memory_raw, package_name)
            data.update({
                "pss_total": mem.get("pss_total", 0),
                "rss_total": mem.get("rss_total", 0),
                "java_heap": mem.get("java_heap", 0),
                "native_heap": mem.get("native_heap", 0),
                "code": mem.get("code", 0),
                "stack": mem.get("stack", 0),
                "graphics": mem.get("graphics", 0),
            })
        except Exception as e:
            data["mem_error"] = str(e)

        # CPU 采集
        try:
            cpu = await loop.run_in_executor(None, get_cpu_info_raw, package_name)
            data["cpu_percent"] = cpu.get("cpu_percent", 0)
        except Exception as e:
            data["cpu_error"] = str(e)

        # 帧率采集（增量计算）
        try:
            frame = await loop.run_in_executor(None, get_frame_info_raw, package_name)
            raw_frames = frame.get("frame_count", 0)
            raw_janky = frame.get("janky_count", 0)

            prev = self._frame_totals.get(package_name)
            if prev is None:
                # 首次采集 → 记录基线，不报告帧数据
                self._frame_totals[package_name] = (raw_frames, raw_janky)
                delta_frames, delta_janky, est_fps = 0, 0, 0.0
            else:
                delta_frames = max(0, raw_frames - prev[0])
                delta_janky = max(0, raw_janky - prev[1])
                self._frame_totals[package_name] = (raw_frames, raw_janky)
                est_fps = round(delta_frames / 2.0, 1) if delta_frames > 0 else 0.0

            data.update({
                "frame_count": delta_frames,
                "janky_count": delta_janky,
                "janky_percent": round((delta_janky / delta_frames) * 100, 1) if delta_frames > 0 else 0,
                "estimated_fps": est_fps,
            })
        except Exception as e:
            data["frame_error"] = str(e)

        # 写入趋势缓存
        get_trend_cache().add(data)

        return data


# 全局采集器实例
_collector = MetricsCollector()


async def sse_endpoint(request: Request, package_name: Optional[str] = None):
    """
    SSE 实时性能指标端点。

    每 2 秒自动采集目标应用的内存、CPU、帧率数据，
    以 SSE 格式推送给前端。

    支持自动检测前台应用（package_name 为空时）。
    """
    print(f"  📡 [SSE] 新客户端连接, package_name={package_name or '自动检测'}")

    async def event_generator():
        while True:
            # 客户端断开连接 → 结束
            if await request.is_disconnected():
                print(f"  📡 [SSE] 客户端断开连接")
                break

            # 确定目标应用
            pkg = package_name
            if not pkg:
                loop = asyncio.get_event_loop()
                pkg = await loop.run_in_executor(None, get_foreground_app)

            if pkg:
                data = await _collector.collect(pkg)
                if data:
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
            else:
                yield f"data: {json.dumps({'error': '未检测到前台应用，请在手机上打开目标应用'}, ensure_ascii=False)}\n\n"

            await asyncio.sleep(METRICS_INTERVAL)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
