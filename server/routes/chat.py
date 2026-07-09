"""对话 API 路由"""
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent.agent import stream_agent

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    chat_history: list = []


@router.post("/api/chat")
async def chat(request: ChatRequest):
    """流式对话 — POST 请求，SSE 流式返回工具调用过程 + 最终回复"""

    async def event_stream():
        async for event in stream_agent(request.message, request.chat_history):
            # 客户端断开时停止
            yield event

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
