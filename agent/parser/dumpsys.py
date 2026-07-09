"""dumpsys 输出解析器"""
from typing import Optional


def parse_meminfo(raw: str) -> Optional[dict]:
    """
    解析 dumpsys meminfo 输出，提取关键内存指标。

    返回格式:
    {
        "pss_total": int,    # KB
        "rss_total": int,
        "java_heap": int,
        "native_heap": int,
        "code": int,
        "stack": int,
        "graphics": int,
        "private_other": int,
        "system": int,
    }
    """
    if not raw or "No process found" in raw:
        return None

    result = {
        "pss_total": 0, "rss_total": 0,
        "java_heap": 0, "native_heap": 0,
        "code": 0, "stack": 0,
        "graphics": 0, "private_other": 0, "system": 0,
    }

    for line in raw.split("\n"):
        line = line.strip()
        if "TOTAL PSS:" in line:
            result["pss_total"] = _extract_number(line)
        elif "TOTAL RSS:" in line:
            result["rss_total"] = _extract_number(line)
        elif "Java Heap:" in line:
            result["java_heap"] = _extract_number(line)
        elif "Native Heap:" in line:
            result["native_heap"] = _extract_number(line)
        elif line.startswith("Code:") and "Heap" not in line:
            result["code"] = _extract_number(line)
        elif "Stack:" in line:
            result["stack"] = _extract_number(line)
        elif "Graphics:" in line:
            result["graphics"] = _extract_number(line)
        elif "Private Other:" in line:
            result["private_other"] = _extract_number(line)
        elif line.startswith("System:") and "Heap" not in line:
            result["system"] = _extract_number(line)

    return result


def parse_package_info(raw: str) -> Optional[dict]:
    """
    解析 dumpsys package 输出，提取应用包信息。

    返回格式:
    {
        "package_name": str,
        "version_name": str,
        "version_code": str,
        "target_sdk": str,
        "min_sdk": str,
        "apk_path": str,
    }
    """
    if not raw:
        return None

    result = {
        "package_name": "", "version_name": "", "version_code": "",
        "target_sdk": "", "min_sdk": "", "apk_path": "",
    }

    for line in raw.split("\n"):
        line = line.strip()
        if "Package [" in line:
            start = line.find("[") + 1
            end = line.find("]")
            if start > 0 and end > start:
                result["package_name"] = line[start:end]
        elif "versionName=" in line:
            for part in line.split():
                if "versionName=" in part:
                    result["version_name"] = part.split("=")[1]
                elif "versionCode=" in part:
                    result["version_code"] = part.split("=")[1]
        elif "targetSdk=" in line:
            for part in line.split():
                if "targetSdk=" in part:
                    result["target_sdk"] = part.split("=")[1]
        elif "codePath=" in line:
            for part in line.split():
                if "codePath=" in part:
                    result["apk_path"] = part.split("=")[1]

    return result


def _extract_number(line: str) -> int:
    """从行中提取第一个数字"""
    for part in line.replace(",", "").replace("(", " ").replace(")", " ").split():
        try:
            return int(part)
        except ValueError:
            continue
    return 0
