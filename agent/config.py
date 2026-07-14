"""Agent 配置 — 工具注册表 + 运行参数

集中管理所有工具的注册和 Agent 运行参数，方便增删工具。
"""

from agent.tools import (
    execute_adb_command,
    list_files,
    get_device_info,
    get_app_info,
    get_app_memory,
    get_frame_info,
    get_cpu_info,
    capture_screenshot,
    get_crash_logs,
    get_anr_info,
    memory_diagnosis,
    query_android_code,
)

# ============================================================
# 工具注册表
# ============================================================
# 添加新工具只需在此列表中添加一行，Agent 和 prompt 会自动感知。
# 工具分组仅用于文档，不影响 Agent 行为。

TOOLS = [
    # 通用操作
    execute_adb_command,   # 万能兜底，受 SYSTEM_PROMPT 规则限制使用
    list_files,            # Mac 文件系统浏览

    # 设备与应用信息
    get_device_info,       # 设备配置（型号/系统/CPU/存储）
    get_app_info,          # 应用详情（包名/版本/PID/Activity）

    # 性能诊断
    get_app_memory,        # 内存占用（dumpsys meminfo）
    get_cpu_info,          # CPU 使用率（top）
    get_frame_info,        # 帧率卡顿（dumpsys gfxinfo）

    # 系统工具
    capture_screenshot,     # 手机截图 → 前端展示
    get_crash_logs,         # 崩溃日志（logcat）
    get_anr_info,           # ANR 检查

    # 深度诊断
    memory_diagnosis,       # 一键内存诊断（heap dump → 解析 → 报告）

    # 代码检索
    query_android_code,     # 检索当前激活 Android 项目的源码
]

# ============================================================
# Agent 运行参数
# ============================================================

# Agent 最大推理轮次（防止死循环）
MAX_ITERATIONS = 15

# 是否在控制台打印 LangChain 详细日志
AGENT_VERBOSE = True

# 遇到 LLM 输出解析错误时是否自动重试
HANDLE_PARSING_ERRORS = True
