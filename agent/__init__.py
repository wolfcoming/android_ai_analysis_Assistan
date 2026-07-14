"""Agent 模块 — 统一的公共接口

内部模块:
    agent.agent      → create_agent / get_agent (核心执行器)
    agent.streaming  → stream_agent / invoke_agent (流式/同步调用)
    agent.callbacks  → StreamingCallback (回调处理器)
    agent.prompts    → SYSTEM_PROMPT / build_chat_prompt_template
    agent.config     → TOOLS / Agent 运行参数
    agent.llm        → create_llm (LLM 工厂)
    agent.tools      → 所有 ADB 工具函数
"""

from agent.agent import create_agent, get_agent
from agent.streaming import stream_agent, invoke_agent
from agent.callbacks import StreamingCallback
from agent.prompts import SYSTEM_PROMPT, build_enhanced_prompt, build_chat_prompt_template
from agent.config import TOOLS, MAX_ITERATIONS

__all__ = [
    "create_agent",
    "get_agent",
    "stream_agent",
    "invoke_agent",
    "StreamingCallback",
    "SYSTEM_PROMPT",
    "build_enhanced_prompt",
    "build_chat_prompt_template",
    "TOOLS",
    "MAX_ITERATIONS",
]
