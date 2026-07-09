"""Agent 创建与执行模块"""
from langchain_classic.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from agent.llm import create_llm
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
)

# 所有工具
TOOLS = [
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
]

SYSTEM_PROMPT = """你是一个安卓开发助手，运行在开发者的 Mac 电脑上。
你可以通过 ADB 连接 Android 手机，帮助开发者完成以下工作：

1. **设备信息查询**：获取手机型号、系统版本、CPU、内存、存储等配置信息
2. **应用信息查询**：获取目标应用的包名、版本、进程、Activity 等信息
3. **性能诊断**：分析内存占用、帧率卡顿、CPU 使用率、ANR 等问题
4. **问题排查**：查看崩溃日志、ANR 日志，定位问题原因

关键规则：
- 查询设备/应用信息时，优先使用专用工具（如 get_device_info）而非 execute_adb_command
- 分析性能问题时，结合多个数据源给出综合判断
- 回复使用中文，数据用表格或列表展示
- 如果用户没有指定目标应用，先询问或尝试自动检测前台应用
- 截图、导出 hprof 等耗时操作，先告知用户正在执行"""


def create_agent():
    """创建 Agent 和 AgentExecutor"""
    llm = create_llm()

    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        MessagesPlaceholder(variable_name="chat_history", optional=True),
        ("human", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad"),
    ])

    agent = create_tool_calling_agent(llm, TOOLS, prompt)
    executor = AgentExecutor(
        agent=agent,
        tools=TOOLS,
        verbose=True,
        handle_parsing_errors=True,
        max_iterations=15,
    )
    return executor


# 全局单例
_agent_executor = None


def get_agent() -> AgentExecutor:
    """获取全局 AgentExecutor 单例"""
    global _agent_executor
    if _agent_executor is None:
        _agent_executor = create_agent()
    return _agent_executor


async def invoke_agent(message: str, chat_history: list = None) -> dict:
    """调用 Agent 处理用户消息"""
    executor = get_agent()
    response = await executor.ainvoke({
        "input": message,
        "chat_history": chat_history or [],
    })
    return {
        "output": response["output"],
        "intermediate_steps": [
            {"tool": step[0].tool, "input": step[0].tool_input, "output": str(step[1])[:500]}
            for step in response.get("intermediate_steps", [])
        ],
    }
