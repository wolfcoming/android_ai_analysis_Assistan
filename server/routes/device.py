"""设备信息 API 路由"""
from fastapi import APIRouter

from agent.tools.adb_device import get_device_info_raw
from agent.tools.adb_app import get_app_memory_raw, get_foreground_app, get_app_info
from agent.tools.adb_perf import get_cpu_info_raw, get_frame_info_raw
from server.history import get_trend_cache

router = APIRouter()


@router.get("/api/device/info")
async def device_info():
    """获取当前连接设备的基本信息"""
    return get_device_info_raw()


@router.get("/api/device/app")
async def device_app(package_name: str = ""):
    """获取目标应用信息"""
    if not package_name:
        package_name = get_foreground_app()
    if not package_name:
        return {"error": "请指定应用包名，或确保手机上有前台应用"}

    result = {"package_name": package_name}
    app_info_str = get_app_info.invoke({"package_name": package_name})
    result["app_info"] = app_info_str
    return result


@router.get("/api/device/realtime")
async def realtime_metrics(package_name: str = ""):
    """获取目标应用的实时性能指标（单次）"""
    if not package_name:
        package_name = get_foreground_app()
    if not package_name:
        return {"error": "未检测到前台应用"}

    mem = get_app_memory_raw(package_name)
    cpu = get_cpu_info_raw(package_name)
    frame = get_frame_info_raw(package_name)

    return {
        "package_name": package_name,
        "memory": mem,
        "cpu": cpu,
        "frame": frame,
    }


@router.get("/api/device/trends")
async def trend_data(seconds: int = 300):
    """获取最近 N 秒的趋势数据"""
    cache = get_trend_cache()
    data = cache.get_recent(seconds)
    return {"count": len(data), "data": data}
