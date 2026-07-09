"""logcat 输出解析器"""


def parse_crash_log(raw: str) -> dict:
    """
    解析 logcat 中的崩溃日志。

    返回格式:
    {
        "has_crash": bool,
        "process": str,
        "exception_type": str,
        "exception_message": str,
        "stack_trace": str,
        "timestamp": str,
    }
    """
    result = {
        "has_crash": False,
        "process": "",
        "exception_type": "",
        "exception_message": "",
        "stack_trace": "",
        "timestamp": "",
    }

    if not raw or raw == "(无输出)":
        return result

    lines = raw.split("\n")
    for i, line in enumerate(lines):
        if "FATAL EXCEPTION" in line:
            result["has_crash"] = True
            # 提取时间戳
            parts = line.split()
            if len(parts) >= 2:
                result["timestamp"] = f"{parts[0]} {parts[1]}"
        elif "Process:" in line and "died" in line.lower():
            result["has_crash"] = True
            result["process"] = line.split("Process:")[-1].split(",")[0].strip()
        elif "java.lang." in line or "android." in line or "kotlin." in line:
            if ":" in line and result["exception_type"] == "":
                result["exception_type"] = line.strip().split(":")[0]
                if ":" in line:
                    msg = line.split(":", 1)
                    result["exception_message"] = msg[1].strip() if len(msg) > 1 else ""
        elif "at " in line and "(" in line and ")" in line:
            if result["stack_trace"]:
                result["stack_trace"] += "\n"
            result["stack_trace"] += line.strip()
            if len(result["stack_trace"].split("\n")) >= 15:
                break

    return result
