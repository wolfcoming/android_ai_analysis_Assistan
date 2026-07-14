"""RAG 管理 API 路由 — Android 项目知识库的 CRUD 操作"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server.rag_android import get_rag_manager

router = APIRouter(prefix="/api/rag", tags=["知识库"])


# ============================================================
# 请求/响应模型
# ============================================================

class CreateProjectRequest(BaseModel):
    name: str
    path: str


# ============================================================
# RAG 管理 API
# ============================================================

@router.get("/projects")
async def list_projects():
    """列出所有已索引项目。"""
    mgr = get_rag_manager()
    projects = mgr.list_projects()
    active_project = None
    for p in projects:
        if p.get("active"):
            active_project = p["name"]
    return {
        "projects": projects,
        "active_project": active_project,
    }


@router.post("/projects")
async def create_project(req: CreateProjectRequest):
    """创建新项目并开始索引。"""
    mgr = get_rag_manager()
    result = mgr.create_project(req.name, req.path)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.delete("/projects/{name}")
async def delete_project(name: str):
    """删除项目索引。"""
    mgr = get_rag_manager()
    result = mgr.delete_project(name)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.put("/projects/{name}/activate")
async def activate_project(name: str):
    """切换激活项目。"""
    mgr = get_rag_manager()
    result = mgr.activate_project(name)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/projects/{name}/reindex")
async def reindex_project(name: str):
    """重新索引项目。"""
    mgr = get_rag_manager()
    result = mgr.reindex(name)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/projects/{name}/status")
async def get_project_status(name: str):
    """获取索引状态/进度。"""
    mgr = get_rag_manager()
    status = mgr.get_project_status(name)
    if status is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return status


@router.get("/active")
async def get_active_project():
    """获取当前激活项目信息。"""
    mgr = get_rag_manager()
    active = mgr.get_active_project()
    if active is None:
        return {"active": None, "message": "无激活项目"}
    return {"active": active}


# ============================================================
# RAG 查询 API（调试用）
# ============================================================

@router.get("/browse-folder")
async def browse_folder():
    """打开系统原生文件夹选择对话框，返回用户选择的路径。"""
    import subprocess
    import sys as _sys

    try:
        # 使用子进程运行 tkinter 文件夹选择（避免主线程冲突）
        script = (
            "import tkinter as tk; from tkinter import filedialog; "
            "r = tk.Tk(); r.withdraw(); r.attributes('-topmost', True); "
            "d = filedialog.askdirectory(parent=r, title='选择Android项目目录'); "
            "r.destroy(); print(d if d else '')"
        )
        result = subprocess.run(
            [_sys.executable, "-c", script],
            capture_output=True, text=True, timeout=60
        )

        selected = result.stdout.strip()
        if result.returncode != 0 or not selected:
            return {"path": None, "message": "用户取消选择"}

        return {"path": selected}
    except subprocess.TimeoutExpired:
        return {"error": "选择超时"}
    except Exception as e:
        return {"error": f"文件夹选择失败: {str(e)}"}


@router.get("/query")
async def query_code(q: str, top_k: int = 5, file_filter: str = ""):
    """检索测试接口（调试用）。"""
    from server.rag_android import retrieve
    mgr = get_rag_manager()
    active = mgr.get_active_project()
    if not active:
        return {"error": "无激活项目", "results": []}

    results = retrieve(active["collection_name"], q, file_filter, top_k)
    return {"query": q, "project": active["name"], "results": results}
