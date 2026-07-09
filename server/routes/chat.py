"""对话 API 路由"""
from fastapi import APIRouter
from pydantic import BaseModel

from agent.agent import invoke_agent

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    chat_history: list = []


class ChatResponse(BaseModel):
    output: str
    intermediate_steps: list = []


@router.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """处理用户对话消息，调用 Agent 并返回结果"""
    result = await invoke_agent(request.message, request.chat_history)
    return ChatResponse(
        output=result["output"],
        intermediate_steps=result["intermediate_steps"],
    )
