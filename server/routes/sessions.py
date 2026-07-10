"""会话管理 API 路由"""
from fastapi import APIRouter

from server.db import (
    create_session,
    list_sessions,
    get_session,
    delete_session,
    get_messages,
    update_session_title,
)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("")
async def api_list_sessions():
    """获取所有会话列表"""
    return list_sessions()


@router.post("")
async def api_create_session():
    """创建新会话"""
    return create_session()


@router.get("/{session_id}")
async def api_get_session(session_id: str):
    """获取会话详情及消息历史"""
    session = get_session(session_id)
    if not session:
        return {"error": "会话不存在", "code": 404}
    messages = get_messages(session_id, include_compressed=False)
    return {"session": session, "messages": messages}


@router.delete("/{session_id}")
async def api_delete_session(session_id: str):
    """删除会话及所有消息"""
    delete_session(session_id)
    return {"ok": True}
