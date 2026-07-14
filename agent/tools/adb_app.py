"""应用信息相关工具 - adb app"""
import subprocess
from langchain_core.tools import tool
from agent.tools.adb_device import _run_adb


@tool
def get_app_info(package_name: str) -> str:
    """
    获取指定 Android 应用的详细信息，包括版本号、目标 SDK、进程 PID、
    当前 Activity、APK 路径、权限等。
    参数: package_name - 应用包名，如 'com.tencent.mm'
    """
    if not package_name:
        return "错误：请提供应用包名"

    # 检查应用是否存在
    check = _run_adb(f"shell pm list packages {package_name}")
    if package_name not in check:
        return f"错误：设备上未找到应用 '{package_name}'"

    info_lines = [f"=== {package_name} 应用信息 ==="]

    # 版本信息
    dumpsys = _run_adb(f"shell dumpsys package {package_name}", timeout=15)
    for line in dumpsys.split("\n"):
        line = line.strip()
        if "versionCode=" in line and "versionName=" in line:
            info_lines.append(f"  {line.split('pkgFlag')[0].strip():>8}")
        elif "targetSdk=" in line:
            info_lines.append(f"  {line.strip()}")
        elif "minSdk=" in line and "targetSdk=" not in line:
            info_lines.append(f"  {line.strip()}")

    # 进程 PID
    pid = _run_adb(f"shell pidof {package_name}", timeout=5)
    if pid and pid.isdigit():
        info_lines.append(f"  主进程 PID: {pid}")
    else:
        # 尝试 ps 方式
        ps = _run_adb(f"shell ps -A | grep {package_name}", timeout=5)
        if ps and ps != "(无输出)":
            info_lines.append(f"  进程信息: {ps.strip()}")

    # 当前 Activity
    activity = _run_adb("shell dumpsys activity activities | grep -E 'topResumedActivity|mResumedActivity' | head -1", timeout=10)
    if activity:
        info_lines.append(f"  当前 Activity: {activity.strip()}")

    # APK 路径
    apk_path = _run_adb(f"shell pm path {package_name}", timeout=5)
    if apk_path:
        info_lines.append(f"  APK 路径: {apk_path.strip()}")

    return "\n".join(info_lines)


@tool
def get_app_memory(package_name: str) -> str:
    """
    获取指定应用的详细内存信息，包括 PSS、RSS、VSS、USS、
    Java Heap、Native Heap、Code、Stack、Graphics 等内存分布。
    参数: package_name - 应用包名

    内存指标说明：
    - PSS: 按比例分摊共享内存后的实际占用（最常用）
    - RSS: 进程独占内存 + 共享内存（未分摊）
    - USS: 进程独占内存（不含共享）
    - Java Heap: Java 堆内存
    - Native Heap: Native 层堆内存
    """
    if not package_name:
        return "错误：请提供应用包名"

    raw = _run_adb(f"shell dumpsys meminfo {package_name}", timeout=15)
    if "No process found" in raw:
        return f"错误：未找到应用 '{package_name}' 的进程。请确认应用正在运行。"

    # 提取关键信息
    result_lines = [f"=== {package_name} 内存详情 ==="]
    headers_found = False

    for line in raw.split("\n"):
        line = line.strip()
        # 找到 App Summary 表格
        if "Pss" in line and "Private" in line and "Private" in line:
            headers_found = True
            continue
        if not headers_found:
            continue
        # 关键行
        if any(kw in line for kw in ["Java Heap:", "Native Heap:", "Code:", "Stack:", "Graphics:",
                                        "Private Other:", "System:", "TOTAL:", "TOTAL PSS:",
                                        "TOTAL RSS:", "TOTAL SWAP PSS:"]):
            result_lines.append(f"  {line}")
        if "Objects" in line:
            break  # 已经到 Objects 部分，停止

    return "\n".join(result_lines) if len(result_lines) > 1 else "未获取到内存详情，请确认应用正在运行。"


def get_foreground_app() -> str:
    """获取当前前台应用的包名"""
    result = _run_adb("shell dumpsys activity activities | grep -E 'topResumedActivity|mResumedActivity' | head -1", timeout=10)
    if not result:
        print(f"[foreground] 未检测到前台应用")
        return ""
    # 提取包名
    for part in result.split():
        if "/" in part and "." in part:
            pkg = part.split("/")[0]
            # print(f"[foreground] 检测到前台应用: {pkg}")
            return pkg
    print(f"[foreground] 无法从前台activity提取包名: {result[:100]}")
    return ""


def get_app_memory_raw(package_name: str) -> dict:
    """返回应用内存的字典格式（供后端 API 使用）"""
    raw = _run_adb(f"shell dumpsys meminfo {package_name}", timeout=15)
    mem = {"pss_total": 0, "rss_total": 0, "java_heap": 0, "native_heap": 0, "code": 0, "stack": 0, "graphics": 0}

    for line in raw.split("\n"):
        line = line.strip()
        # 兼容新旧 Android 版本的 PSS 格式
        # 旧: "TOTAL PSS:   194538"
        # 新: "       TOTAL:   194538       TOTAL SWAP PSS:    34221"
        if "TOTAL PSS:" in line:
            mem["pss_total"] = _extract_kb(line)
        elif "TOTAL:" in line:
            # 新格式: "TOTAL:   195096       TOTAL SWAP PSS:    34213"
            # _extract_kb 取第一个数值即 PSS
            mem["pss_total"] = _extract_kb(line)
        elif "TOTAL RSS:" in line:
            mem["rss_total"] = _extract_kb(line)
        elif "Java Heap:" in line:
            mem["java_heap"] = _extract_kb(line)
        elif "Native Heap:" in line:
            mem["native_heap"] = _extract_kb(line)
        elif line.startswith("Code:") and "Heap" not in line:
            mem["code"] = _extract_kb(line)
        elif line.startswith("Stack:"):
            mem["stack"] = _extract_kb(line)
        elif "Graphics:" in line:
            mem["graphics"] = _extract_kb(line)

    return mem


def _extract_kb(line: str) -> int:
    """从内存行中提取 KB 数值"""
    parts = line.split()
    for p in parts:
        p = p.replace(",", "").replace("(", "").replace(")", "")
        try:
            return int(p)
        except ValueError:
            continue
    return 0
