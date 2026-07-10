"""heap_dump 工具 — 一键内存诊断：dump → pull → 解析 → 返回类直方图"""

import os
import subprocess
import shutil
import tempfile
import time
from typing import Optional

from langchain_core.tools import tool

from .hprof_parser import parse_hprof_file
from .adb_device import _run_adb

# dump 文件保留目录（供用户下载，用 Android Studio 打开分析）
_DUMPS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "web", "dumps"
)


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

    # 构建报告
    lines = []
    if result.get("fallback"):
        lines.append(f"## 内存诊断报告 — {package_name} (降级方案)")
        lines.append("")
        lines.append(f"> **注意**: hprof 解析失败（{result.get('fallback_reason', '')}），")
        lines.append(f"> 已自动回退到 dumpsys meminfo 分析。如需完整 heap dump 分析，请使用 Android Studio Profiler。")
    else:
        lines.append(f"## 内存诊断报告 — {package_name}")

    lines.append("")
    lines.append(f"- hprof 文件大小: {result.get('file_size_mb', 0):.1f} MB")

    # 采样模式说明
    parse_mode = result.get("parse_mode", "")
    if parse_mode == "sampled":
        sampled_from = result.get("sampled_from", 0)
        sampled_max = result.get("sampled_max", 0)
        lines.append(f"- 解析模式: **采样解析**（从 {sampled_from:,} 个实例中采样了 {sampled_max:,} 个）")
        lines.append(f"- > 采样数据已具有统计代表性。如需完整精确数据，请下载 hprof 文件用 Android Studio Profiler 打开。")

    # 下载链接（放在数据前面，确保 LLM 不会遗漏）
    dump_url = result.get("dump_url", "")
    download_section = ""
    if dump_url:
        download_section = (
            f"\n**【下载完整 hprof 文件】**: [{dump_url}]({dump_url})（右键另存为，用 Android Studio Profiler 打开进行引用链深度分析）\n"
        )
        lines.append(download_section.strip())

    lines.append(f"- Top 类总内存: {result.get('total_bytes_top50', 0) / (1024 * 1024):.1f} MB")
    lines.append("")
    lines.append("| 分类 | 实例数 | 总大小 |")
    lines.append("|------|--------|--------|")
    for c in result.get("top_classes", [])[:20]:
        if result.get("fallback"):
            # meminfo 数据单位是 KB
            if c["total_size"] > 1024:
                size_str = f"{c['total_size']/1024:.1f} MB"
            else:
                size_str = f"{c['total_size']} KB"
        else:
            # hprof 数据单位是 bytes
            if c["total_size"] > 1024 * 1024:
                size_str = f"{c['total_size']/(1024*1024):.1f} MB"
            else:
                size_str = f"{c['total_size']/1024:.0f} KB"
        lines.append(f"| {c['class_name']} | {c['instance_count']} | {size_str} |")

    lines.append("")
    lines.append(f"诊断摘要: {result.get('summary', '')}")

    # 重复字符串警告
    dupes = result.get("duplicate_strings", [])
    if dupes:
        lines.append("")
        lines.append("### 重复字符串检测")
        lines.append("以下字符串在堆中出现超过 100 次，可能存在 String.intern() 过度或字符串拼接问题：")
        lines.append("| 字符串 | 出现次数 |")
        lines.append("|--------|----------|")
        for d in dupes[:5]:
            lines.append(f"| {d['string']} | {d['count']} |")

    # 底部再次强调下载链接
    if download_section:
        lines.append("")
        lines.append(download_section.strip())

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

    # 2. 在设备上 dump heap (am dumpheap 是异步的，只发信号)
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

    # 2.5 等待异步 dump 完成（轮询文件大小，最长 60 秒）
    waited = 0
    while waited < 60:
        time.sleep(2)
        waited += 2
        try:
            size_output = _run_adb(f"shell stat -c %s {remote_path} 2>/dev/null", timeout=5)
            size = int(size_output.strip())
            if size > 1024:  # 至少 1KB 才算有效
                break
        except (ValueError, Exception):
            pass
    else:
        result["error"] = f"heap dump 超时：等待 60 秒后文件仍为空。应用可能处于 D 状态（disk sleep）或内存太大"
        # 清理残留空文件
        try:
            _run_adb(f"shell rm {remote_path}", timeout=5)
        except Exception:
            pass
        return result

    # 3. 创建本地临时目录
    tmp_dir = tempfile.mkdtemp(prefix="hprof_")
    local_raw = os.path.join(tmp_dir, "raw.hprof")
    local_std = os.path.join(tmp_dir, "std.hprof")

    try:
        # 4. 拉取 hprof 文件（大文件可能需要较长时间）
        pull_timeout = 120  # 大 dump 可能需要 2 分钟
        pull_result = subprocess.run(
            ["adb", "pull", remote_path, local_raw],
            capture_output=True, text=True, timeout=pull_timeout
        )
        if "error" in pull_result.stdout.lower() or "error" in pull_result.stderr.lower():
            result["error"] = f"拉取 hprof 文件失败: {pull_result.stdout} {pull_result.stderr}"
            return result

        if not os.path.exists(local_raw) or os.path.getsize(local_raw) < 100:
            result["error"] = "拉取的 hprof 文件为空或太小"
            return result

        file_size_mb = os.path.getsize(local_raw) / (1024 * 1024)
        result["file_size_mb"] = round(file_size_mb, 2)

        # 3.5 保留一份 dump 文件供用户下载
        os.makedirs(_DUMPS_DIR, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        dump_filename = f"{package_name}_{timestamp}.hprof"
        dump_save_path = os.path.join(_DUMPS_DIR, dump_filename)
        dump_url = None

        # 5. 用 hprof-conv 转换为标准格式
        hprof_conv = os.path.expanduser("~/Library/Android/sdk/platform-tools/hprof-conv")
        if not os.path.exists(hprof_conv):
            hprof_conv = "hprof-conv"

        conv_result = subprocess.run(
            [hprof_conv, local_raw, local_std],
            capture_output=True, text=True, timeout=120
        )
        if conv_result.returncode != 0:
            parse_target = local_raw
            # 转换失败时也保留原始文件
            try:
                shutil.copy2(local_raw, dump_save_path)
                dump_url = f"/dumps/{dump_filename}"
            except Exception:
                pass
        else:
            parse_target = local_std
            # 保留转换后的标准格式
            try:
                shutil.copy2(local_std, dump_save_path)
                dump_url = f"/dumps/{dump_filename}"
            except Exception:
                pass

        if not os.path.exists(parse_target) or os.path.getsize(parse_target) < 100:
            result["error"] = "hprof 转换后文件为空"
            return result

        final_mb = os.path.getsize(parse_target) / (1024 * 1024)
        result["file_size_mb"] = round(final_mb, 2)
        if dump_url:
            result["dump_url"] = dump_url

        # 6. 解析 hprof（已内置 mmap + 大文件采样）
        parsed = parse_hprof_file(parse_target)
        if "error" in parsed:
            fallback = _fallback_meminfo(package_name, pid)
            result["success"] = True
            result["fallback"] = True
            result["fallback_reason"] = parsed["error"]
            result["top_classes"] = fallback.get("categories", [])
            result["summary"] = fallback.get("summary", "")
            result["total_bytes_top50"] = fallback.get("total_pss_kb", 0)
            result["total_instances_top50"] = 0
            return result

        result["success"] = True
        result["format"] = parsed.get("format", "unknown")
        result["parse_mode"] = parsed.get("parse_mode", "full")
        result["sampled_from"] = parsed.get("sampled_from", 0)
        result["sampled_max"] = parsed.get("sampled_max", 0)
        result["duplicate_strings"] = parsed.get("duplicate_strings", [])
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


def _fallback_meminfo(package_name: str, pid: str) -> dict:
    """回退方案：通过 dumpsys meminfo 获取详细内存分析"""
    try:
        raw = _run_adb(f"shell dumpsys meminfo {pid}", timeout=15)
    except Exception:
        raw = ""

    categories = []
    total_pss = 0
    in_table = False
    saw_pss_header = False

    for line in raw.split("\n"):
        stripped = line.strip()

        # 检测内存表格头（跨两行）
        if "Pss" in stripped and "Private" in stripped:
            saw_pss_header = True
            continue
        if saw_pss_header and "Total" in stripped and "Dirty" in stripped:
            in_table = True
            saw_pss_header = False
            continue
        if stripped.startswith("------"):
            continue

        # 表格结束
        if in_table and ("App Summary" in stripped or "Objects" in stripped):
            in_table = False
            continue

        if not in_table:
            # 检查 App Summary 中的 TOTAL PSS
            if "TOTAL PSS:" in stripped:
                parts = stripped.split()
                for p in parts:
                    try:
                        total_pss = int(p)
                        break
                    except ValueError:
                        continue
            # Objects 计数
            if "Views:" in stripped or "Activities:" in stripped or "AppContexts:" in stripped:
                parts = stripped.split(":")
                if len(parts) >= 2:
                    label = parts[0].strip()
                    try:
                        val = int(parts[1].split()[0])
                        if val >= 0:
                            categories.append({
                                "class_name": label,
                                "instance_count": val,
                                "total_size": 0,
                            })
                    except (ValueError, IndexError):
                        pass
            continue

        # 表格内的数据行
        # 名称可能含空格（如 "Native Heap", "Dalvik Other"），需要找到名称结束位置
        parts = stripped.split()
        if len(parts) < 2:
            continue
        try:
            # 从左边遍历，找到第一个纯数字列 = Pss Total
            name_parts = []
            pss_kb = 0
            for i, p in enumerate(parts):
                try:
                    pss_kb = int(p)
                    name_parts = parts[:i]
                    break
                except ValueError:
                    continue
            if not name_parts or pss_kb <= 0:
                continue
            label = " ".join(name_parts).rstrip(":")
            if label and not label.startswith("---"):
                categories.append({
                    "class_name": label,
                    "instance_count": 0,
                    "total_size": pss_kb,
                })
        except ValueError:
            continue

    categories.sort(key=lambda x: x["total_size"], reverse=True)

    summary_parts = []
    for c in categories[:8]:
        kb = c["total_size"]
        if kb > 1024:
            summary_parts.append(f"{c['class_name']}: {kb/1024:.1f} MB")
        else:
            summary_parts.append(f"{c['class_name']}: {kb} KB")

    return {
        "categories": categories[:20],
        "summary": " | ".join(summary_parts),
        "total_pss_kb": total_pss,
    }


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
