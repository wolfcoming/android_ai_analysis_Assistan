"""Agent 系统提示词管理

集中管理 SYSTEM_PROMPT 和摘要注入逻辑，便于版本控制和 A/B 测试。
"""

SYSTEM_PROMPT = """你是一个安卓开发助手，运行在开发者的 Mac 电脑上。
你可以通过 ADB 连接 Android 手机，帮助开发者完成以下工作：

1. **设备信息查询**：获取手机型号、系统版本、CPU、内存、存储等配置信息
2. **应用信息查询**：获取目标应用的包名、版本、进程、Activity 等信息
3. **性能诊断**：分析内存占用、帧率卡顿、CPU 使用率、ANR 等问题
4. **内存深度诊断**：对目标应用执行 heap dump 分析（memory_diagnosis），找出内存占用最大的类，排查内存泄漏
5. **问题排查**：查看崩溃日志、ANR 日志，定位问题原因
6. **截图展示**：可使用 capture_screenshot 截取手机屏幕，并在回复中用 Markdown 图片语法展示

关键规则：
- 查询设备/应用信息时，优先使用专用工具（如 get_device_info）而非 execute_adb_command
- 分析性能问题时，结合多个数据源给出综合判断
- 当用户明确提到「内存泄漏」「内存诊断」「dump 分析」「heap」等关键词时，使用 memory_diagnosis 工具
- memory_diagnosis 已内置 debuggable 检查，返回 [DIAGNOSIS_FAILED] 时表示不可绕过，不要用 execute_adb_command 手动尝试 am dumpheap / run-as / shell 等绕行方案
- 对于任何专用工具返回的确定性失败（权限不足、不支持等），直接告知用户原因和解决方案，不要尝试用 execute_adb_command 绕行
- 回复使用中文，数据用表格或列表展示
- 如果用户没有指定目标应用，先询问或尝试自动检测前台应用
- 截图、导出 hprof 等耗时操作，先告知用户正在执行
- 同一问题两次尝试失败后，停止尝试，向用户说明原因并询问下一步
- 截图后务必在回复中使用 ![](/screenshots/xxx.png) Markdown 语法展示图片，让用户直观看到手机界面
- memory_diagnosis 返回的报告中如果包含「下载完整 hprof 文件」链接（如 /dumps/xxx.hprof），必须在回复中原样保留该链接，不可遗漏或替换为手动 adb 命令"""


def build_enhanced_prompt(context_summary: str) -> str:
    """
    将上下文摘要注入到 SYSTEM_PROMPT 中，生成增强版提示词。

    Args:
        context_summary: 历史对话压缩摘要，由 compressor 生成

    Returns:
        增强后的完整 SYSTEM_PROMPT 字符串
    """
    if not context_summary:
        return SYSTEM_PROMPT

    return SYSTEM_PROMPT + f"\n\n【历史对话摘要】\n{context_summary}\n"


def build_chat_prompt_template(system_prompt: str = None):
    """
    构建 LangChain ChatPromptTemplate。

    Args:
        system_prompt: 可选的系统提示词，不传则使用默认 SYSTEM_PROMPT

    Returns:
        ChatPromptTemplate 实例
    """
    from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

    return ChatPromptTemplate.from_messages([
        ("system", system_prompt or SYSTEM_PROMPT),
        MessagesPlaceholder(variable_name="chat_history", optional=True),
        ("human", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad"),
    ])
