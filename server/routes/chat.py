"""对话 API 路由 — 流式对话 + 会话持久化 + 上下文压缩

核心流程:
    1. 验证 session_id ↔ 加载历史 ↔ 压缩 ↔ 保存用户消息
    2. 调用 Agent 流式推理
    3. 保存 assistant 回复

支持格式:
    新格式 (推荐): { "session_id": "xxx", "message": "..." }
    旧格式 (兼容): { "chat_history": [...], "message": "..." }
"""

import json
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent.streaming import stream_agent
from agent.llm import create_llm
from server.db import (
    add_message, get_messages, mark_compressed,
    touch_session, update_session_title, get_session,
)
from server.compressor import compress_messages
from server.logger import (
    log_request,
    log_session_loaded,
    log_compression_decision,
    log_compression_done,
    log_response_saved,
)

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    session_id: str = ""
    chat_history: list = []


async def _call_llm_for_summary(prompt: str) -> str:
    """调用 LLM 生成摘要"""
    try:
        from server.compressor import estimate_tokens
        print(f"  🤖 [压缩] 调用 LLM 生成摘要 (prompt token≈{estimate_tokens(prompt)})")
        llm = create_llm()
        response = await llm.ainvoke(prompt)
        result = response.content if hasattr(response, "content") else str(response)
        print(f"  🤖 [压缩] LLM 返回摘要: {len(result)}字")
        return result
    except Exception as e:
        print(f"  ❌ [压缩] 摘要生成失败: {e}")
        return ""


@router.post("/api/chat")
async def chat(request: ChatRequest):
    """
    流式对话接口 — 完整处理一条用户消息。

    SSE 事件流:
      - thinking:   LLM 推理过程
      - tool_start: 工具开始执行
      - tool_end:   工具执行完毕
      - tool_error: 工具执行出错
      - output:     最终回复
      - done:       流结束
    """
    session_id = request.session_id
    user_message = request.message

    # ===== 日志：请求进入 =====
    log_request(session_id or "(旧格式兼容)", user_message)

    # ===== 兼容旧格式（无 session_id）=====
    if not session_id:
        if request.chat_history and len(request.chat_history) > 0:
            # 旧格式：直接传 chat_history，不持久化
            async def compat_stream():
                async for evt in stream_agent(user_message, request.chat_history):
                    yield evt
            return StreamingResponse(
                compat_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )
        else:
            raise HTTPException(status_code=400, detail="缺少 session_id，请先创建会话")

    # ===== 验证会话 =====
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    # ===== 加载历史消息 =====
    db_messages = get_messages(session_id, include_compressed=False)
    log_session_loaded(len(db_messages), session.get("title", "新对话"))

    # ===== 上下文压缩 =====
    context_summary = ""
    if db_messages:
        summary, compressed_ids = await compress_messages(
            db_messages,
            _call_llm_for_summary,
        )
        if summary:
            mark_compressed(compressed_ids)
            add_message(session_id, "summary", summary)
            context_summary = summary
            # 重新加载（排除已压缩的旧消息）
            db_messages = get_messages(session_id, include_compressed=False)

    # ===== 构建 LangChain 格式 chat_history =====
    chat_history = []
    for msg in db_messages:
        if msg.get("role") in ("user", "human"):
            chat_history.append(["human", msg["content"]])
        elif msg.get("role") in ("assistant", "ai"):
            chat_history.append(["ai", msg["content"]])
        # summary 和 tool 角色不加入 chat_history

    # ===== 保存用户消息 + 自动标题 =====
    add_message(session_id, "user", user_message)

    if len(db_messages) == 0 and session.get("title", "新对话") == "新对话":
        title = user_message[:20] + ("..." if len(user_message) > 20 else "")
        update_session_title(session_id, title)

    touch_session(session_id)

    # ===== 流式响应 =====
    async def event_stream():
        final_output = ""
        async for evt in stream_agent(user_message, chat_history, context_summary):
            # 捕获 output 事件以保存到 DB
            if '{"type":"output"' in evt or '"type":"output"' in evt:
                try:
                    _, json_str = evt.split("data: ", 1)
                    data = json.loads(json_str)
                    final_output = data.get("content", "")
                except Exception:
                    pass
            yield evt

        # 保存 assistant 回复
        if final_output:
            add_message(session_id, "assistant", final_output)
            touch_session(session_id)
            log_response_saved(len(final_output))

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
