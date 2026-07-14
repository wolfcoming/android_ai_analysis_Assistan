"""设备信息相关工具 - adb device"""
import os
import subprocess
from langchain_core.tools import tool


def _run_adb(command: str, timeout: int = 30) -> str:
    """执行 ADB 命令并返回输出"""
    try:
        # print(f"[ADB] 执行命令: adb {command}")
        full_cmd = ["adb"] + command.split()
        result = subprocess.run(full_cmd, capture_output=True, text=True, timeout=timeout)
        output = result.stdout.strip()
        if result.stderr:
            stderr = result.stderr.strip()
            if stderr:
                output += f"\n[stderr]: {stderr}"
                print(f"[ADB] stderr: {stderr[:200]}")
        # print(f"[ADB] 返回: {output[:200] if output else '(无输出)'}")
        return output if output else "(无输出)"
    except subprocess.TimeoutExpired:
        print(f"[ADB] 超时错误: {timeout}s")
        return f"错误：ADB 命令执行超时（{timeout}秒）"
    except FileNotFoundError:
        print(f"[ADB] 未找到adb命令")
        return "错误：未找到 adb 命令，请确认 Android SDK 已正确安装并添加到 PATH"
    except Exception as e:
        print(f"[ADB] 错误: {e}")
        return f"执行 ADB 命令时出错: {str(e)}"


@tool
def execute_adb_command(command: str) -> str:
    """
    执行一条 ADB 命令并返回输出。命令中不要包含 'adb' 前缀。
    适用于执行未封装为专用工具的其他 ADB 操作。
    示例：'devices'、'shell pm list packages'、'shell getprop ro.build.version.sdk'
    """
    return _run_adb(command)


@tool
def list_files(directory_path: str) -> str:
    """列出 Mac 上指定目录下的所有文件和文件夹。需要使用绝对路径。"""
    try:
        if not os.path.exists(directory_path):
            return f"错误：路径 '{directory_path}' 不存在。"
        items = os.listdir(directory_path)
        if not items:
            return f"目录 '{directory_path}' 为空。"
        result = f"目录 '{directory_path}' 中的内容:\n"
        for item in sorted(items):
            full = os.path.join(directory_path, item)
            tag = "[DIR]" if os.path.isdir(full) else "[FILE]"
            result += f"  {tag} {item}\n"
        return result.strip()
    except PermissionError:
        return f"错误：没有权限访问 '{directory_path}'。"
    except Exception as e:
        return f"操作失败: {str(e)}"


@tool
def get_device_info() -> str:
    """
    获取当前连接的 Android 设备的详细配置信息，包括：
    型号、品牌、Android 版本、API Level、CPU 架构、内存、存储、屏幕、电池、网络等。
    不需要参数。
    """
    # 先检查设备连接
    devices = _run_adb("devices")
    if "device" not in devices or devices.count("\n") < 2:
        return "错误：没有检测到已连接的 Android 设备。请确认：\n1. 手机已通过 USB 连接\n2. 已开启开发者模式和 USB 调试\n3. 已在手机上授权此电脑"

    info_lines = ["=== 设备概览 ==="]

    # 基本信息
    props = {
        "品牌": "ro.product.brand",
        "型号": "ro.product.model",
        "设备代号": "ro.product.device",
        "Android 版本": "ro.build.version.release",
        "API Level": "ro.build.version.sdk",
        "构建号": "ro.build.display.id",
        "CPU 架构": "ro.product.cpu.abi",
        "CPU 核心数": None,  # 特殊处理
        "屏幕分辨率": None,  # 特殊处理
        "屏幕密度(DPI)": None,  # 特殊处理
    }

    for label, prop in props.items():
        if prop is None:
            continue
        value = _run_adb(f"shell getprop {prop}", timeout=5)
        if value and value != "(无输出)":
            info_lines.append(f"  {label}: {value}")

    # CPU 核心数
    cpu_cores = _run_adb("shell cat /proc/cpuinfo | grep processor | wc -l", timeout=5)
    if cpu_cores.isdigit():
        info_lines.append(f"  CPU 核心数: {cpu_cores}")

    # 屏幕信息
    size = _run_adb("shell wm size", timeout=5)
    density = _run_adb("shell wm density", timeout=5)
    if "override" not in size.lower():
        info_lines.append(f"  屏幕分辨率: {size.replace('Physical size: ', '').strip()}")
    info_lines.append(f"  屏幕密度: {density.replace('Physical density: ', '').strip()}")

    # RAM 信息
    meminfo = _run_adb("shell cat /proc/meminfo | grep -E 'MemTotal|MemAvailable'", timeout=5)
    for line in meminfo.split("\n"):
        if ":" in line:
            key, val = line.split(":", 1)
            kb = int(val.strip().replace(" kB", ""))
            if "Total" in key:
                info_lines.append(f"  总 RAM: {kb / 1024:.1f} MB")
            elif "Available" in key:
                info_lines.append(f"  可用 RAM: {kb / 1024:.1f} MB")

    # 存储信息
    storage = _run_adb("shell df -h /data", timeout=5)
    storage_lines = storage.split("\n")
    if len(storage_lines) > 1:
        info_lines.append(f"  存储：{storage_lines[1].strip()}")

    # 电池
    battery = _run_adb("shell dumpsys battery", timeout=5)
    for line in battery.split("\n"):
        line = line.strip()
        if "level:" in line:
            info_lines.append(f"  电池电量: {line.split(':')[1].strip()}%")
        elif "temperature:" in line:
            temp = int(line.split(":")[1].strip()) / 10
            info_lines.append(f"  电池温度: {temp}°C")

    return "\n".join(info_lines)


def get_device_info_raw() -> dict:
    """返回设备信息的字典格式（供后端 API 使用）"""
    info = {
        "brand": _run_adb("shell getprop ro.product.brand", timeout=5).strip(),
        "model": _run_adb("shell getprop ro.product.model", timeout=5).strip(),
        "device": _run_adb("shell getprop ro.product.device", timeout=5).strip(),
        "android_version": _run_adb("shell getprop ro.build.version.release", timeout=5).strip(),
        "api_level": _run_adb("shell getprop ro.build.version.sdk", timeout=5).strip(),
        "build": _run_adb("shell getprop ro.build.display.id", timeout=5).strip(),
        "cpu_abi": _run_adb("shell getprop ro.product.cpu.abi", timeout=5).strip(),
        "cpu_cores": _run_adb("shell cat /proc/cpuinfo | grep processor | wc -l", timeout=5).strip(),
        "screen_size": _run_adb("shell wm size", timeout=5).strip().replace("Physical size: ", ""),
        "screen_density": _run_adb("shell wm density", timeout=5).strip().replace("Physical density: ", ""),
        "connected": True,
    }
    return info
