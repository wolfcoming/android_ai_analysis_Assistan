"""Agent 流式调用 — SSE 事件流 + 同步调用

核心职责:
    1. stream_agent(): 流式调用 Agent，通过 SSE 实时推送事件
    2. invoke_agent(): 同步调用 Agent，返回完整结果

数据流:
    stream_agent
      ├── 创建 StreamingCallback (事件捕获器)
      ├── 创建 asyncio.Task 后台执行 Agent
      ├── 轮询 asyncio.Queue 获取事件 → yield SSE
      └── Agent 完成后 → yield output + done
"""

import asyncio
import json
import time

from langchain_classic.agents import AgentExecutor, create_tool_calling_agent

from agent.callbacks import StreamingCallback
from agent.llm import create_llm
from agent.prompts import build_enhanced_prompt, build_chat_prompt_template
from agent.config import TOOLS
from agent.agent import get_agent
from server.logger import log_agent_start, log_agent_end


async def stream_agent(message: str, chat_history: list = None, context_summary: str = ""):
    """
    流式调用 Agent — 实时 yield SSE 事件。

    这是整个 Agent 系统的核心入口，负责:
        1. 准备 Agent 执行环境（上下文摘要注入、回调注册）
        2. 在后台异步运行 Agent
        3. 实时轮询并推送事件给前端

    Args:
        message:         用户输入消息
        chat_history:    对话历史，格式 [(role, content), ...]
        context_summary: 可选的上下文摘要，会注入到 SYSTEM_PROMPT 中

    Yields:
        SSE 格式的事件字符串，格式: "data: {json}\n\n"

        事件类型:
          - thinking:   LLM 推理过程     {"type":"thinking", "content":"..."}
          - tool_start: 工具开始执行     {"type":"tool_start", "tool":"...", "input":"..."}
          - tool_end:   工具执行完毕     {"type":"tool_end", "output":"..."}
          - tool_error: 工具执行出错     {"type":"tool_error", "error":"..."}
          - output:     最终 LLM 回复     {"type":"output", "content":"..."}
          - done:       流结束           {"type":"done"}
    """
    # ===== 1. 创建事件队列和回调处理器 =====
    queue = asyncio.Queue()
    callback = StreamingCallback(queue)

    # ===== 2. 日志：Agent 开始 =====
    agent_start_time = time.time()
    log_agent_start(message, bool(chat_history), bool(context_summary))

    # ===== 3. 确定使用哪个 Agent =====
    if context_summary:
        # 有摘要时，创建临时 agent（注入增强的 SYSTEM_PROMPT）
        enhanced_system = build_enhanced_prompt(context_summary)
        llm = create_llm()
        prompt = build_chat_prompt_template(enhanced_system)
        agent = create_tool_calling_agent(llm, TOOLS, prompt)
        current_executor = AgentExecutor(
            agent=agent,
            tools=TOOLS,
            verbose=True,
            handle_parsing_errors=True,
            max_iterations=15,
        )
    else:
        # 无摘要，使用全局单例 agent
        current_executor = get_agent()

    # ===== 4. 在后台运行 Agent =====
    task = asyncio.create_task(
        current_executor.ainvoke(
            {"input": message, "chat_history": chat_history or []},
            config={"callbacks": [callback]},
        )
    )

    # ===== 5. 轮询回调队列，实时推送 =====
    while not task.done():
        try:
            event = await asyncio.wait_for(queue.get(), timeout=0.15)
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except asyncio.TimeoutError:
            # 超时说明队列为空，继续等待
            continue

    # ===== 6. Agent 执行完毕，获取最终结果 =====
    try:
        result = await task
        output = result.get("output", "抱歉，没有获取到回复。")
    except Exception as e:
        output = f"❌ Agent 执行出错: {str(e)}"

    log_agent_end(len(output), agent_start_time)

    yield f"data: {json.dumps({'type': 'output', 'content': output}, ensure_ascii=False)}\n\n"
    yield "data: {\"type\": \"done\"}\n\n"


async def invoke_agent(message: str, chat_history: list = None) -> dict:
    """
    同步调用 Agent 处理用户消息。

    与 stream_agent 不同，此函数不提供流式输出，
    适合测试和批量处理场景。

    Args:
        message:      用户输入消息
        chat_history: 对话历史

    Returns:
        {
            "output": "Agent 回复内容",
            "intermediate_steps": [
                {"tool": "工具名", "input": "参数", "output": "结果"},
                ...
            ]
        }
    """
    executor = get_agent()
    response = await executor.ainvoke({
        "input": message,
        "chat_history": chat_history or [],
    })
    return {
        "output": response["output"],
        "intermediate_steps": [
            {
                "tool": step[0].tool,
                "input": step[0].tool_input,
                "output": str(step[1])[:500],
            }
            for step in response.get("intermediate_steps", [])
        ],
    }
