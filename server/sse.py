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
_last_frame_totals = {}  # {package_name: (last_frame_count, last_janky_count)}


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
        raw_frame_count = frame.get("frame_count", 0)
        raw_janky_count = frame.get("janky_count", 0)

        # 增量计算：对比上次采集，得出这 2 秒内的新帧
        prev = _last_frame_totals.get(package_name)
        if prev is None:
            # 首次读取：设为基线，不报告帧数据（避免历史累计数据被当作增量）
            _last_frame_totals[package_name] = (raw_frame_count, raw_janky_count)
            delta_frames = 0
            delta_janky = 0
            est_fps = 0
        else:
            delta_frames = max(0, raw_frame_count - prev[0])
            delta_janky = max(0, raw_janky_count - prev[1])
            _last_frame_totals[package_name] = (raw_frame_count, raw_janky_count)
            # 用增量计算实时 FPS（2 秒间隔）
            est_fps = round(delta_frames / 2.0, 1) if delta_frames > 0 else 0

        data.update({
            "frame_count": delta_frames if delta_frames >= 0 else 0,
            "janky_count": delta_janky if delta_janky >= 0 else 0,
            "janky_percent": round((delta_janky / delta_frames) * 100, 1) if delta_frames > 0 else 0,
            "estimated_fps": est_fps,
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
