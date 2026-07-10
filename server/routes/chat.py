"""对话 API 路由 — 集成会话持久化 + 上下文压缩"""
import json

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent.agent import stream_agent
from server.db import (
    add_message, get_messages, mark_compressed,
    touch_session, update_session_title, get_session,
)
from server.compressor import compress_messages
from agent.llm import create_llm

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    session_id: str = ""
    chat_history: list = []


async def _call_llm_for_summary(prompt: str) -> str:
    """调用 LLM 生成摘要"""
    try:
        llm = create_llm()
        response = await llm.ainvoke(prompt)
        return response.content if hasattr(response, "content") else str(response)
    except Exception as e:
        print(f"[compressor] 摘要生成失败: {e}")
        return ""


@router.post("/api/chat")
async def chat(request: ChatRequest):
    """
    流式对话 — 集成会话持久化与上下文压缩。

    新格式（推荐）: { "message": "...", "session_id": "uuid-xxx" }
    旧格式（兼容）: { "message": "...", "chat_history": [...] }
    """
    session_id = request.session_id
    user_message = request.message

    # ---- 兼容旧格式（无 session_id） ----
    if not session_id:
        if request.chat_history and len(request.chat_history) > 0:
            # 旧格式回退：直接传 chat_history，不持久化
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

    # ---- 新格式：session_id 模式 ----
    # 验证 session 存在
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    # 从 DB 加载消息历史
    db_messages = get_messages(session_id, include_compressed=False)

    # 上下文压缩
    context_summary = ""
    if db_messages:
        summary, compressed_ids = await compress_messages(
            db_messages,
            _call_llm_for_summary,
        )
        if summary:
            mark_compressed(compressed_ids)
            # 添加摘要到 DB
            add_message(session_id, "summary", summary)
            context_summary = summary

            # 重新加载（排除已压缩的旧消息）
            db_messages = get_messages(session_id, include_compressed=False)

    # 构建 LangChain 格式的 chat_history
    chat_history = []
    for msg in db_messages:
        if msg.get("role") in ("user", "human"):
            chat_history.append(["human", msg["content"]])
        elif msg.get("role") in ("assistant", "ai"):
            chat_history.append(["ai", msg["content"]])
        # summary 和 tool 角色不加入 chat_history

    # 保存用户消息到 DB
    add_message(session_id, "user", user_message)

    # 自动更新会话标题（取首条消息的前 20 字）
    message_count = len(db_messages)
    if message_count == 0 and session.get("title", "新对话") == "新对话":
        title = user_message[:20] + ("..." if len(user_message) > 20 else "")
        update_session_title(session_id, title)

    touch_session(session_id)

    # 流式响应（在流结束后保存 assistant 回复）

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

        # 保存 assistant 回复到 DB
        if final_output:
            add_message(session_id, "assistant", final_output)
            touch_session(session_id)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
