"""系统级工具 - 截图、崩溃日志、ANR、bugreport 等"""
import os
import time
from langchain_core.tools import tool
from agent.tools.adb_device import _run_adb


@tool
def capture_screenshot(output_path: str = "") -> str:
    """
    截取手机屏幕截图。截图保存在手机 /sdcard 下，并拉取到 Mac 本地。
    参数: output_path (可选) - Mac 上保存截图的目录路径，默认为当前工作目录。
    返回截图文件的本地路径。
    """
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    remote_path = f"/sdcard/screenshot_{timestamp}.png"

    # 截图
    result = _run_adb(f"shell screencap -p {remote_path}", timeout=10)
    if result and "错误" in result:
        return f"截图失败: {result}"

    # 拉取到本地
    local_dir = output_path or os.getcwd()
    local_path = os.path.join(local_dir, f"screenshot_{timestamp}.png")
    _run_adb(f"pull {remote_path} {local_path}", timeout=15)

    if os.path.exists(local_path):
        return f"截图已保存到: {local_path}"
    return "截图拉取失败，请检查 adb 连接"


@tool
def get_crash_logs(package_name: str = "", lines: int = 200) -> str:
    """
    获取最近的 Android 崩溃日志（logcat 中的 FATAL EXCEPTION 和 AndroidRuntime 错误）。
    参数:
      package_name (可选) - 过滤指定应用的崩溃日志
      lines (可选) - 搜索的 logcat 行数，默认 200
    """
    cmd = f"shell logcat -d -b crash -t {lines}"
    if package_name:
        cmd += f" | grep -A 20 '{package_name}'"

    crash_log = _run_adb(cmd, timeout=10)

    # 如果 crash buffer 没有数据，尝试 main buffer
    if not crash_log or crash_log == "(无输出)":
        cmd = f"shell logcat -d -t {lines} | grep -E 'FATAL EXCEPTION|AndroidRuntime|Process:.*died'"
        if package_name:
            cmd += f" | grep -A 20 '{package_name}'"
        crash_log = _run_adb(cmd, timeout=10)

    if not crash_log or crash_log == "(无输出)":
        return "未找到最近的崩溃日志。"

    return f"=== 崩溃日志 ===\n{crash_log}"


@tool
def get_anr_info(package_name: str = "") -> str:
    """
    检查目标应用是否存在 ANR (Application Not Responding) 记录。
    参数: package_name (可选) - 应用包名，不提供则检查所有应用
    """
    result_lines = ["=== ANR 检查 ==="]

    # 检查最近的 ANR
    anr_check = _run_adb("shell dumpsys activity activities | grep -A 5 'ANR'", timeout=10)
    if anr_check and anr_check != "(无输出)":
        if package_name and package_name not in anr_check:
            result_lines.append(f"  未找到 {package_name} 的 ANR 记录。")
        else:
            result_lines.append(f"  ⚠️ 发现 ANR 记录:\n{anr_check}")
    else:
        result_lines.append("  ✅ 未发现 ANR 记录。")

    # 检查 traces 文件
    traces_dir = _run_adb("shell ls /data/anr/ 2>/dev/null", timeout=5)
    if traces_dir and traces_dir != "(无输出)" and "No such file" not in traces_dir:
        result_lines.append(f"\n  ANR traces 目录内容:\n  {traces_dir}")

    return "\n".join(result_lines)
