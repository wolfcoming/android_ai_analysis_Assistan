"""SSE (Server-Sent Events) 模块 - 2秒推送实时指标"""
import asyncio
import json
import time
from typing import Optional

from fastapi import Request
from fastapi.responses import StreamingResponse

from agent.tools.adb_app import get_app_memory_raw, get_foreground_app
from agent.tools.adb_perf import get_cpu_info_raw, get_frame_info_raw
from server.history import get_trend_cache


_last_collection_time = 0
_collection_lock = asyncio.Lock()


async def collect_metrics(package_name: str) -> dict:
    """采集一次性能指标"""
    global _last_collection_time

    async with _collection_lock:
        now = time.time()
        # 防重叠：如果距上次采集不足 1.5 秒，跳过
        if now - _last_collection_time < 1.5:
            return None
        _last_collection_time = now

    loop = asyncio.get_event_loop()
    data = {"timestamp": now}

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

    try:
        cpu = await loop.run_in_executor(None, get_cpu_info_raw, package_name)
        data["cpu_percent"] = cpu.get("cpu_percent", 0)
    except Exception as e:
        data["cpu_error"] = str(e)

    try:
        frame = await loop.run_in_executor(None, get_frame_info_raw, package_name)
        data.update({
            "frame_count": frame.get("frame_count", 0),
            "janky_count": frame.get("janky_count", 0),
            "janky_percent": frame.get("janky_percent", 0),
            "estimated_fps": frame.get("estimated_fps", 0),
        })
    except Exception as e:
        data["frame_error"] = str(e)

    # 写入趋势缓存
    get_trend_cache().add(data)

    return data


async def sse_endpoint(request: Request, package_name: Optional[str] = None):
    """SSE 端点，每 2 秒推送实时指标数据"""

    async def event_generator():
        while True:
            if await request.is_disconnected():
                break

            pkg = package_name
            if not pkg:
                # 自动检测前台应用
                loop = asyncio.get_event_loop()
                pkg = await loop.run_in_executor(None, get_foreground_app)

            if pkg:
                data = await collect_metrics(pkg)
                if data:
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
            else:
                yield f"data: {json.dumps({'error': '未检测到前台应用，请在手机上打开目标应用'})}\n\n"

            await asyncio.sleep(2)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
