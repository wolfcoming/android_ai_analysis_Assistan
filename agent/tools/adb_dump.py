"""heap_dump 工具 — 一键内存诊断：dump → pull → 解析 → 返回类直方图"""

import os
import subprocess
import tempfile
from typing import Optional

from langchain_core.tools import tool

from .hprof_parser import parse_hprof_file
from .adb_device import _run_adb


@tool
def memory_diagnosis(package_name: str) -> str:
    """
    一键内存诊断工具。对目标应用执行完整的 heap dump 分析，找出内存占用最大的类。
    返回类直方图（Top 类按内存占用排序），用于排查内存泄漏和内存占用过高的问题。

    **重要**: 此工具已内置 debuggable 检查。如果返回权限错误，表示该应用确实不可调试，
    不存在任何绕行方案。不要用 execute_adb_command 手动尝试 dump，直接告知用户原因即可。

    参数:
        package_name: 目标应用的包名，例如 "com.tencent.mm"

    返回:
        诊断报告，包含 Top 内存大户类名、实例数量、占用内存大小。
        如果应用不可调试，返回明确的权限错误（不要再尝试其他方法）。
    """
    result = heap_dump_analysis(package_name)
    if not result.get("success"):
        error_msg = result.get('error', '未知错误')
        return (
            f"[DIAGNOSIS_FAILED] 内存诊断失败: {error_msg}\n\n"
            "此诊断结果已确定，不要用 execute_adb_command 或其他方式再次尝试 dump。直接告知用户失败原因和解决方案。"
        )

    # 构建可读的报告
    lines = [f"## 内存诊断报告 — {package_name}", ""]
    lines.append(f"- hprof 文件大小: {result.get('file_size_mb', 0):.1f} MB")
    lines.append(f"- Top 50 类实例总数: {result.get('total_instances_top50', 0)}")
    lines.append(f"- Top 50 类总内存: {result.get('total_bytes_top50', 0) / (1024 * 1024):.1f} MB")
    lines.append("")
    lines.append("| 类名 | 实例数 | 总大小 (MB) |")
    lines.append("|------|--------|-------------|")
    for c in result.get("top_classes", [])[:20]:
        size_mb = c["total_size"] / (1024 * 1024)
        lines.append(f"| {c['class_name']} | {c['instance_count']} | {size_mb:.1f} |")

    lines.append("")
    lines.append(f"诊断摘要: {result.get('summary', '')}")
    lines.append("")
    lines.append("提示: 如果某个类的实例数异常多或内存占用异常高，可能存在内存泄漏。重点关注 Activity、Fragment、Bitmap、Cursor 等常见泄漏源。")

    return "\n".join(lines)


def heap_dump_analysis(package_name: str) -> dict:
    """
    对目标应用执行完整的内存诊断：
    1. 在设备上 dump heap 到 /data/local/tmp/
    2. 拉取 hprof 文件到本地
    3. 用 hprof-conv 转换为标准格式
    4. 解析类直方图，返回 Top 50 内存大户

    Args:
        package_name: 目标应用包名，如 "com.tencent.mm"

    Returns:
        {
            "success": True/False,
            "error": "...",                    # 失败时
            "package": "...",
            "pid": "...",
            "format": "JAVA PROFILE 1.0.3",
            "file_size_mb": 12.5,
            "top_classes": [
                {"class_name": "android.graphics.Bitmap", "instance_count": 120, "total_size": 52428800, "instance_size": 4096},
                ...
            ],
            "summary": "Top 5 类占用内存: ..."
        }
    """
    result = {
        "success": False,
        "package": package_name,
    }

    # 1. 获取 PID
    pid = _get_pid(package_name)
    if not pid:
        result["error"] = f"找不到应用 {package_name}，请确认应用正在运行"
        return result
    result["pid"] = pid

    # 1.5 检查应用是否可调试
    if not _is_debuggable(package_name):
        result["error"] = (
            f"目标应用 {package_name} 不是 debuggable 的，无法进行 heap dump。\n"
            "请确认：\n"
            "1. 你的手机已 ROOT，或\n"
            "2. 手机刷了 userdebug 镜像，或\n"
            "3. 应用是 debug 构建（AndroidManifest 中 android:debuggable=\"true\"）"
        )
        return result

    # 2. 在设备上 dump heap
    remote_path = f"/data/local/tmp/heap_dump_{package_name.replace('.', '_')}.hprof"
    dump_cmd = f"shell am dumpheap {pid} {remote_path}"
    try:
        dump_output = _run_adb(dump_cmd, timeout=30)
        # 检查 dump 是否报错
        if "SecurityException" in dump_output or "not debuggable" in dump_output:
            result["error"] = f"heap dump 权限不足: 应用 {package_name} 不是 debuggable 的"
            return result
    except Exception as e:
        result["error"] = f"heap dump 失败: {e}"
        return result

    # 3. 创建本地临时目录
    tmp_dir = tempfile.mkdtemp(prefix="hprof_")
    local_raw = os.path.join(tmp_dir, "raw.hprof")
    local_std = os.path.join(tmp_dir, "std.hprof")

    try:
        # 4. 拉取 hprof 文件
        pull_result = subprocess.run(
            ["adb", "pull", remote_path, local_raw],
            capture_output=True, text=True, timeout=30
        )
        if "error" in pull_result.stdout.lower() or "error" in pull_result.stderr.lower():
            result["error"] = f"拉取 hprof 文件失败: {pull_result.stdout} {pull_result.stderr}"
            return result

        if not os.path.exists(local_raw) or os.path.getsize(local_raw) < 100:
            result["error"] = "拉取的 hprof 文件为空或太小"
            return result

        # 5. 用 hprof-conv 转换为标准格式
        hprof_conv = os.path.expanduser("~/Library/Android/sdk/platform-tools/hprof-conv")
        if not os.path.exists(hprof_conv):
            # 尝试 PATH 中查找
            hprof_conv = "hprof-conv"

        conv_result = subprocess.run(
            [hprof_conv, local_raw, local_std],
            capture_output=True, text=True, timeout=60
        )
        if conv_result.returncode != 0:
            # 如果转换失败，尝试直接解析原始文件（Android 格式）
            parse_target = local_raw
        else:
            parse_target = local_std

        if not os.path.exists(parse_target) or os.path.getsize(parse_target) < 100:
            result["error"] = "hprof 转换后文件为空"
            return result

        file_size_mb = os.path.getsize(parse_target) / (1024 * 1024)
        result["file_size_mb"] = round(file_size_mb, 2)

        # 6. 解析 hprof
        parsed = parse_hprof_file(parse_target)
        if "error" in parsed:
            result["error"] = f"hprof 解析失败: {parsed['error']}"
            return result

        result["success"] = True
        result["format"] = parsed.get("format", "unknown")
        result["top_classes"] = parsed.get("top_classes", [])
        result["total_instances_top50"] = parsed.get("total_instances_top50", 0)
        result["total_bytes_top50"] = parsed.get("total_bytes_top50", 0)

        # 7. 生成摘要
        top5 = result["top_classes"][:5]
        summary_parts = []
        for c in top5:
            size_mb = c["total_size"] / (1024 * 1024)
            summary_parts.append(
                f"{c['class_name']}: {c['instance_count']} 实例, {size_mb:.1f} MB"
            )
        result["summary"] = " | ".join(summary_parts)

    finally:
        # 清理本地临时文件
        try:
            os.remove(local_raw)
        except Exception:
            pass
        try:
            os.remove(local_std)
        except Exception:
            pass
        try:
            os.rmdir(tmp_dir)
        except Exception:
            pass
        # 清理设备上的文件
        try:
            _run_adb(f"shell rm {remote_path}", timeout=5)
        except Exception:
            pass

    return result


def _get_pid(package_name: str) -> Optional[str]:
    """获取应用的 PID"""
    try:
        output = _run_adb("shell pidof " + package_name, timeout=5)
        pids = output.strip().split()
        if pids:
            return pids[0]
    except Exception:
        pass

    # 备选：通过 ps 查找
    try:
        output = _run_adb(f"shell ps -A | grep {package_name}", timeout=5)
        for line in output.strip().split("\n"):
            if package_name in line:
                parts = line.strip().split()
                if len(parts) >= 2:
                    return parts[1]  # PID 通常在第二列
    except Exception:
        pass

    return None


def _is_debuggable(package_name: str) -> bool:
    """检查目标应用是否可调试"""
    try:
        output = _run_adb(f"shell dumpsys package {package_name} | grep -A 5 'flags=' | head -10", timeout=10)
        # debuggable 的应用会有: flags=[ DEBUGGABLE HAS_CODE ALLOW_CLEAR_USER_DATA ... ]
        if "DEBUGGABLE" in output:
            return True
        # 备选：检查 applicationInfo 的 flags
        output2 = _run_adb(f"shell dumpsys package {package_name} | grep 'FLAG_DEBUGGABLE'", timeout=10)
        if "FLAG_DEBUGGABLE" in output2:
            return True
    except Exception:
        pass
    return False
