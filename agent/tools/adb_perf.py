"""性能相关工具 - adb perf"""
import time
from langchain_core.tools import tool
from agent.tools.adb_device import _run_adb


@tool
def get_frame_info(package_name: str) -> str:
    """
    获取指定应用的帧渲染数据（gfxinfo），用于分析卡顿和帧率。
    返回总帧数、Janky frames（掉帧）数量及占比、各渲染阶段的耗时分布。
    参数: package_name - 应用包名

    注意：需要先在手机上操作应用（滑动/点击），gfxinfo 才会累积帧数据。
    如果返回数据为空，请提示用户先在手机上操作一下应用。
    """
    if not package_name:
        return "错误：请提供应用包名"

    # 先重置再获取（确保拿到最新数据）
    _run_adb(f"shell dumpsys gfxinfo {package_name} reset", timeout=5)
    time.sleep(0.5)
    raw = _run_adb(f"shell dumpsys gfxinfo {package_name}", timeout=15)

    if "No process found" in raw:
        return f"错误：未找到应用 '{package_name}' 的进程。"

    # 解析帧数据
    result_lines = [f"=== {package_name} 帧渲染分析 ==="]
    in_profile = False
    frame_count = 0
    janky_count = 0
    total_render = 0.0
    total_draw = 0.0

    # 优先用新版格式: "Stats since:" → "Total frames rendered:" / "Janky frames:"
    for line in raw.split("\n"):
        line = line.strip()
        if "Total frames rendered:" in line:
            try:
                frame_count = int(line.split(":")[1].strip())
            except ValueError:
                pass
        elif "Janky frames:" in line:
            try:
                janky_count = int(line.split(":")[1].strip().split()[0])
            except ValueError:
                pass

    # 如果新版格式没数据，回退到旧版 PROFILEDATA 格式
    if frame_count == 0:
        for line in raw.split("\n"):
            line = line.strip()
            if "---PROFILEDATA---" in line:
                in_profile = True
                continue
            if not in_profile:
                continue
            if line.startswith("---") or not line:
                break
            parts = line.split(",")
            if len(parts) >= 3:
                try:
                    flags = int(parts[0])
                    intended_vsync = float(parts[1])
                    frame_completed = float(parts[2])
                    if intended_vsync > 0 and frame_completed > 0:
                        frame_ms = (frame_completed - intended_vsync) / 1000000.0
                        frame_count += 1
                        if frame_ms > 16.67:  # 超过 60fps 阈值
                            janky_count += 1
                        total_render += frame_ms
                except (ValueError, IndexError):
                    continue

    if frame_count == 0:
        result_lines.append("  ⚠️ 帧数据为空，请先在手机上操作一下应用（滑动/点击），再重新查询。")
        return "\n".join(result_lines)

    janky_pct = (janky_count / frame_count) * 100
    avg_fps = 1000.0 / (total_render / frame_count) if total_render > 0 else 0

    result_lines.append(f"  统计帧数: {frame_count}")
    result_lines.append(f"  Janky frames: {janky_count} ({janky_pct:.1f}%)")
    result_lines.append(f"  平均帧耗时: {total_render / frame_count:.2f} ms")
    result_lines.append(f"  估算 FPS: {avg_fps:.1f}")

    # 诊断建议
    result_lines.append(f"\n  诊断：")
    if janky_pct < 5:
        result_lines.append(f"  ✅ 帧率表现良好，掉帧比例 < 5%")
    elif janky_pct < 15:
        result_lines.append(f"  ⚠️ 存在一定卡顿，掉帧比例 {janky_pct:.1f}%，建议检查主线程耗时操作")
    else:
        result_lines.append(f"  🔴 严重卡顿！掉帧比例 {janky_pct:.1f}%，建议使用 Perfetto 系统追踪定位")

    return "\n".join(result_lines)


@tool
def get_cpu_info(package_name: str) -> str:
    """
    获取指定应用的 CPU 使用率。
    参数: package_name - 应用包名
    """
    if not package_name:
        return "错误：请提供应用包名"

    raw = _run_adb(f"shell top -n 1 | grep {package_name}", timeout=10)
    if not raw or raw == "(无输出)":
        return f"未找到应用 '{package_name}' 的进程，请确认应用正在运行。"

    result_lines = [f"=== {package_name} CPU 使用情况 ==="]
    for line in raw.split("\n"):
        parts = line.split()
        # top 输出格式: PID USER PR NI CPU% S #THR VSS RSS PCY Name
        if len(parts) >= 10:
            result_lines.append(f"  PID: {parts[0]} | CPU: {parts[4]} | 进程: {parts[9]}")

    return "\n".join(result_lines)


def get_cpu_info_raw(package_name: str) -> dict:
    """返回 CPU 信息的字典格式（供后端 API 使用）"""
    raw = _run_adb(f"shell top -n 1 | grep {package_name}", timeout=10)
    cpu_total = 0.0
    for line in raw.split("\n"):
        parts = line.split()
        # top 输出格式: PID USER PR NI CPU% S #THR VSS RSS PCY Name
        if len(parts) >= 10:
            try:
                cpu_total += float(parts[4].replace("%", ""))
            except ValueError:
                continue
    return {"cpu_percent": round(cpu_total, 1)}


def get_frame_info_raw(package_name: str) -> dict:
    """返回帧率信息的字典格式（供后端 SSE 实时采集，不 reset 以免破坏累积数据）"""
    raw = _run_adb(f"shell dumpsys gfxinfo {package_name}", timeout=15)

    frame_count = 0
    janky_count = 0
    total_render = 0.0

    # 优先用新版格式: "Stats since:" → "Total frames rendered:" / "Janky frames:"
    for line in raw.split("\n"):
        line = line.strip()
        if "Total frames rendered:" in line:
            try:
                frame_count = int(line.split(":")[1].strip())
            except ValueError:
                pass
        elif "Janky frames:" in line:
            try:
                janky_count = int(line.split(":")[1].strip().split()[0])
            except ValueError:
                pass

    # 如果新版格式没数据，回退到旧版 PROFILEDATA 格式
    if frame_count == 0:
        in_profile = False
        for line in raw.split("\n"):
            line = line.strip()
            if "---PROFILEDATA---" in line:
                in_profile = True
                continue
            if not in_profile:
                continue
            if line.startswith("---") or not line:
                break
            parts = line.split(",")
            if len(parts) >= 3:
                try:
                    intended_vsync = float(parts[1])
                    frame_completed = float(parts[2])
                    if intended_vsync > 0 and frame_completed > 0:
                        frame_ms = (frame_completed - intended_vsync) / 1000000.0
                        frame_count += 1
                        if frame_ms > 16.67:
                            janky_count += 1
                        total_render += frame_ms
                except (ValueError, IndexError):
                    continue

    return {
        "frame_count": frame_count,
        "janky_count": janky_count,
        "janky_percent": round((janky_count / frame_count) * 100, 1) if frame_count > 0 else 0,
        "avg_frame_ms": round(total_render / frame_count, 2) if frame_count > 0 and total_render > 0 else 0,
        "estimated_fps": round(1000.0 / (total_render / frame_count), 1) if frame_count > 0 and total_render > 0 else 0,
    }
