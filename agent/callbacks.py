"""Agent 回调处理器 — 实时捕获 Agent 执行过程中的事件

StreamingCallback 继承 LangChain 的 AsyncCallbackHandler，
在 Agent 思考、调用工具、返回结果时实时推送 SSE 事件。
"""

import asyncio
import time

from langchain_core.callbacks import AsyncCallbackHandler

from server.logger import (
    log_agent_thinking,
    log_tool_call,
    log_tool_result,
    log_tool_error,
    log_agent_final_answer,
)


class StreamingCallback(AsyncCallbackHandler):
    """
    流式回调处理器。

    工作流程:
        1. Agent 决定调用工具 → on_agent_action() → 推送 thinking + tool_start
        2. 工具执行完毕      → on_tool_end()     → 推送 tool_end
        3. 工具执行出错      → on_tool_error()   → 推送 tool_error
        4. Agent 给出最终答案 → on_agent_finish() → 推送 thinking

    所有事件通过 asyncio.Queue 传递给 stream_agent 的轮询循环。
    """

    def __init__(self, queue: asyncio.Queue):
        """初始化回调处理器

        Args:
            queue: 异步事件队列。回调方法将事件写入此队列，
                   stream_agent 从队列中读取并 yield SSE 事件。
        """
        self.queue = queue
        self._tool_start_time = time.time()

    async def on_agent_action(self, action, **kwargs):
        """
        LLM 决定调用工具时触发。

        这是 Agent 循环的核心节点：LLM 完成了推理，决定下一步要调用
        哪个工具、传什么参数。action.log 包含了 LLM 做出这个决定前的
        思考过程，是我们最想看到的推理内容。

        Args:
            action: AgentAction 对象，包含:
                - action.tool: 工具名称 (str)
                - action.tool_input: 工具参数 (dict)
                - action.log: LLM 推理文本 (str)
        """
        # 记录工具开始时间，用于计算执行耗时
        self._tool_start_time = time.time()

        # 终端日志：打印推理过程和工具调用
        thought = str(action.log)[:1000] if action.log else ""
        if thought:
            log_agent_thinking(thought)
        log_tool_call(action.tool, str(action.tool_input)[:100])

        # 推送 thinking 事件（LLM 思考过程）
        if action.log:
            await self.queue.put({
                "type": "thinking",
                "content": str(action.log)[:1000],
            })

        # 推送 tool_start 事件（工具开始执行）
        await self.queue.put({
            "type": "tool_start",
            "tool": action.tool,
            "input": str(action.tool_input),
        })

    async def on_tool_end(self, output: str, **kwargs):
        """
        工具执行完成时触发。

        工具函数已经返回了结果，这里将结果推送给前端显示，
        同时记录执行耗时。

        Args:
            output: 工具返回的字符串结果
        """
        elapsed = time.time() - self._tool_start_time
        log_tool_result("", str(output)[:200], elapsed)

        await self.queue.put({
            "type": "tool_end",
            "output": str(output)[:800],
        })

    async def on_tool_error(self, error, **kwargs):
        """
        工具执行出错时触发。

        工具函数抛出异常，AgentExecutor 捕获后调用此方法。
        错误信息会推送给前端显示。

        Args:
            error: 异常对象
        """
        log_tool_error("", str(error)[:200])

        await self.queue.put({
            "type": "tool_error",
            "error": str(error),
        })

    async def on_agent_finish(self, finish, **kwargs):
        """
        Agent 执行完成时触发。

        LLM 决定不再调用工具，而是给出最终答案。
        finish.log 包含 LLM 在给出答案前的推理。

        Args:
            finish: AgentFinish 对象，包含:
                - finish.log: 最终推理文本 (str)
                - finish.return_values: 包含最终输出 (dict)
        """
        if finish.log:
            log_agent_final_answer(str(finish.log)[:300])

        if finish.log:
            await self.queue.put({
                "type": "thinking",
                "content": str(finish.log)[:1000],
            })

    async def on_llm_start(self, serialized, prompts, **kwargs):
        """LLM 开始推理时触发（调试用）"""
        pass  # 可在此添加 LLM 调用日志

    async def on_llm_end(self, response, **kwargs):
        """LLM 推理完成时触发（调试用）"""
        pass  # 可在此添加 token 消耗日志
