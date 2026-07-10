"""Agent 创建与执行模块"""
import asyncio
import json

from langchain_classic.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.callbacks import AsyncCallbackHandler
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
    memory_diagnosis,
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
    memory_diagnosis,
]

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


class StreamingCallback(AsyncCallbackHandler):
    """流式回调处理器 — 实时推送 Agent 思考过程和工具调用"""

    def __init__(self, queue: asyncio.Queue):
        self.queue = queue

    async def on_agent_action(self, action, **kwargs):
        """
        Agent 决定了下一步行动（LLM 思考完毕 → 决定调用工具）。
        action.log 包含 LLM 的推理文本。
        """
        if action.log:
            await self.queue.put({
                "type": "thinking",
                "content": str(action.log)[:1000],
            })

        await self.queue.put({
            "type": "tool_start",
            "tool": action.tool,
            "input": str(action.tool_input),
        })

    async def on_tool_end(self, output: str, **kwargs):
        await self.queue.put({
            "type": "tool_end",
            "output": str(output)[:800],
        })

    async def on_tool_error(self, error, **kwargs):
        await self.queue.put({
            "type": "tool_error",
            "error": str(error),
        })

    async def on_agent_finish(self, finish, **kwargs):
        """
        Agent 执行完毕，不再调用工具。
        finish.log 包含 LLM 在给出最终回复前的推理。
        """
        if finish.log:
            await self.queue.put({
                "type": "thinking",
                "content": str(finish.log)[:1000],
            })


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


async def stream_agent(message: str, chat_history: list = None, context_summary: str = ""):
    """
    流式调用 Agent — 实时 yield SSE 事件。

    Args:
        message: 用户消息
        chat_history: [(role, content), ...] 对话历史
        context_summary: 可选的上下文摘要，会追加到 SYSTEM_PROMPT 中

    事件类型:
      - thinking:   LLM 推理过程
      - tool_start: 工具开始执行
      - tool_end:   工具执行完毕
      - tool_error: 工具执行出错
      - output:     最终 LLM 回复
      - done:       流结束
    """
    queue = asyncio.Queue()
    callback = StreamingCallback(queue)

    # 如果有上下文摘要，注入到系统提示中，创建临时 agent
    if context_summary:
        enhanced_system = SYSTEM_PROMPT + f"\n\n【历史对话摘要】\n{context_summary}\n"
        llm = create_llm()
        prompt = ChatPromptTemplate.from_messages([
            ("system", enhanced_system),
            MessagesPlaceholder(variable_name="chat_history", optional=True),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])
        agent = create_tool_calling_agent(llm, TOOLS, prompt)
        current_executor = AgentExecutor(
            agent=agent,
            tools=TOOLS,
            verbose=True,
            handle_parsing_errors=True,
            max_iterations=15,
        )
    else:
        current_executor = get_agent()

    # 在后台运行 Agent
    task = asyncio.create_task(
        current_executor.ainvoke(
            {"input": message, "chat_history": chat_history or []},
            config={"callbacks": [callback]},
        )
    )

    # 轮询回调队列，实时推送工具调用事件
    while not task.done():
        try:
            event = await asyncio.wait_for(queue.get(), timeout=0.15)
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except asyncio.TimeoutError:
            continue

    # Agent 执行完毕，获取最终结果
    try:
        result = await task
        output = result.get("output", "抱歉，没有获取到回复。")
    except Exception as e:
        output = f"❌ Agent 执行出错: {str(e)}"

    yield f"data: {json.dumps({'type': 'output', 'content': output}, ensure_ascii=False)}\n\n"
    yield "data: {\"type\": \"done\"}\n\n"
