"""Agent 创建模块 — 核心执行器工厂

职责：
    1. 创建 LangChain Function Calling Agent
    2. 管理 AgentExecutor 全局单例

其他功能已迁移至:
    - agent.callbacks  → StreamingCallback (回调处理器)
    - agent.streaming  → stream_agent / invoke_agent (流式/同步调用)
    - agent.prompts    → SYSTEM_PROMPT / build_chat_prompt_template (提示词)
    - agent.config     → TOOLS / MAX_ITERATIONS (配置)
"""

from langchain_classic.agents import AgentExecutor, create_tool_calling_agent

from agent.llm import create_llm
from agent.config import TOOLS, MAX_ITERATIONS, AGENT_VERBOSE, HANDLE_PARSING_ERRORS
from agent.prompts import build_chat_prompt_template


def create_agent() -> AgentExecutor:
    """
    创建完整的 Agent 执行器。

    步骤:
        1. 初始化 LLM (DeepSeek / OpenAI)
        2. 构建 ChatPromptTemplate (system + chat_history + input + scratchpad)
        3. 创建 Function Calling Agent
        4. 包装为 AgentExecutor (带错误处理 + 迭代限制)

    Returns:
        配置好的 AgentExecutor 实例
    """
    llm = create_llm()
    prompt = build_chat_prompt_template()

    agent = create_tool_calling_agent(llm, TOOLS, prompt)
    executor = AgentExecutor(
        agent=agent,
        tools=TOOLS,
        verbose=AGENT_VERBOSE,
        handle_parsing_errors=HANDLE_PARSING_ERRORS,
        max_iterations=MAX_ITERATIONS,
    )
    return executor


# ============================================================
# 全局单例管理
# ============================================================

_agent_executor: AgentExecutor = None


def get_agent() -> AgentExecutor:
    """
    获取全局 AgentExecutor 单例。

    首次调用时创建 Agent，后续调用返回缓存实例。
    使用单例避免了每次对话都重新创建 LLM 连接和加载 prompt。

    Returns:
        AgentExecutor 单例
    """
    global _agent_executor
    if _agent_executor is None:
        _agent_executor = create_agent()
    return _agent_executor
