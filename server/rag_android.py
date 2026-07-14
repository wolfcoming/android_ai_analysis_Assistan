"""Android 项目 RAG 核心 — 文件扫描、智能分块、向量索引、检索

模块职责：
- scan_files()     文件扫描（Java/Kotlin/XML/Gradle/Manifest/Markdown）
- chunk_file()     智能分块（按类/方法/View/Component 边界）
- build_index()    向量化 + 存入 ChromaDB（后台异步，支持进度回调）
- retrieve()       向量检索
- RAGManager       多项目生命周期管理（创建/删除/激活/列表/状态）
"""

import os
import re
import json
import hashlib
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import chromadb
from chromadb.config import Settings

from server.config import CHROMA_PROJECTS_DIR, RAG_PROJECTS_FILE

# ============================================================
# 文件扫描
# ============================================================

# 支持的文件扩展名
SUPPORTED_EXTENSIONS = {
    ".java", ".kt", ".xml", ".gradle", ".gradle.kts", ".pro", ".md", ".txt"
}

# 排除的目录
EXCLUDE_DIRS = {"build", ".gradle", ".idea", ".git", "node_modules", ".cxx",
                "__pycache__", ".venv", "venv", "generated", "intermediates"}

# 排除的文件扩展名
EXCLUDE_EXTENSIONS = {".class", ".apk", ".aar", ".jar", ".png", ".jpg",
                       ".jpeg", ".webp", ".so", ".dex", ".gif", ".svg",
                       ".ttf", ".otf", ".mp3", ".mp4", ".ogg", ".db", ".bin"}


def scan_files(project_path: str) -> list[str]:
    """扫描 Android 项目中的所有源码文件，返回文件路径列表。"""
    files = []
    for root, dirs, filenames in os.walk(project_path):
        # 过滤目录
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith(".")]

        for f in filenames:
            ext = os.path.splitext(f)[1].lower()
            if ext in EXCLUDE_EXTENSIONS:
                continue
            if ext in SUPPORTED_EXTENSIONS:
                files.append(os.path.join(root, f))
    return files


# ============================================================
# 智能分块
# ============================================================

MAX_CHUNK_SIZE = 1500  # 字符
OVERLAP_CHARS = 200    # 重叠字符数


def _extract_package(content: str, lang: str) -> str:
    """从源码中提取包名。"""
    m = re.search(r'package\s+([\w.]+)', content)
    return m.group(1) if m else ""


def _extract_class_name(content: str, lang: str) -> str:
    """从 Java/Kotlin 源码中提取类名。"""
    pattern = r'(?:public\s+)?(?:abstract\s+)?(?:final\s+)?(?:open\s+)?(?:class|interface|object|enum\s+class)\s+(\w+)'
    m = re.search(pattern, content)
    return m.group(1) if m else ""


def _extract_module(file_path: str, project_path: str) -> str:
    """从文件路径提取模块名。"""
    rel = os.path.relpath(file_path, project_path)
    parts = rel.split(os.sep)
    if len(parts) > 0 and parts[0]:
        return parts[0]
    return "root"


def _extract_xml_component_type(file_path: str, content: str) -> str:
    """从 XML 中提取组件类型（仅 AndroidManifest 用）。"""
    if "AndroidManifest.xml" not in file_path:
        return ""
    types = []
    if "<activity" in content:
        types.append("activity")
    if "<service" in content:
        types.append("service")
    if "<receiver" in content:
        types.append("receiver")
    if "<provider" in content:
        types.append("provider")
    return ",".join(types[:2])


def _build_metadata(file_path: str, project_path: str, project_name: str,
                    lang: str, content: str, line_start: int, line_end: int,
                    class_name: str = "", method_name: str = "",
                    component_type: str = "") -> dict:
    """构建代码块的元数据。"""
    return {
        "file": os.path.relpath(file_path, project_path),
        "file_abs": file_path,
        "line_start": line_start,
        "line_end": line_end,
        "lang": lang,
        "class_name": class_name,
        "method_name": method_name,
        "module": _extract_module(file_path, project_path),
        "package": _extract_package(content, lang),
        "component_type": component_type,
        "project": project_name,
    }


def chunk_java_kotlin(content: str, file_path: str, project_path: str,
                       project_name: str) -> list[dict]:
    """Java/Kotlin 智能分块：按类边界切分，大类按方法拆分。"""
    chunks = []
    lines = content.split("\n")
    ext = os.path.splitext(file_path)[1].lower()
    lang = "kotlin" if ext == ".kt" else "java"

    class_name = _extract_class_name(content, lang)
    package = _extract_package(content, lang)

    # 尝试按类边界拆分: class/interface/object/enum
    class_pattern = re.compile(
        r'((?:public\s+|private\s+|protected\s+|internal\s+)?'
        r'(?:abstract\s+|open\s+|final\s+|sealed\s+|data\s+)?'
        r'(?:class|interface|object|enum\s+class)\s+\w+)'
    )

    class_starts = [0]  # 文件开头（import/package 区）
    for i, line in enumerate(lines):
        if class_pattern.search(line):
            class_starts.append(i)

    cls_name = class_name  # 初始化，避免未赋值错误
    for ci in range(len(class_starts)):
        start = class_starts[ci]
        end = class_starts[ci + 1] if ci + 1 < len(class_starts) else len(lines)
        class_section = "\n".join(lines[start:end])

        if start == 0 and class_name:
            # 文件头部区域（package + import），作为第一个类的 overlap
            pass
        else:
            cls_name = _extract_class_name(class_section, lang) or cls_name

        # 如果类块小于阈值，整体作为一个块
        if len(class_section) <= MAX_CHUNK_SIZE:
            chunks.append({
                "content": class_section,
                "metadata": _build_metadata(
                    file_path, project_path, project_name, lang,
                    class_section, start + 1, end, class_name=cls_name
                ),
            })
            continue

        # 大类按方法拆分
        method_pattern = re.compile(
            r'((?:public\s+|private\s+|protected\s+|internal\s+|override\s+|'
            r'abstract\s+|open\s+|final\s+|suspend\s+|inline\s+)*'
            r'(?:fun\s+\w+|(?:[\w<>[\],\s]+\s+)\w+\s*\())'
        )

        # 找方法边界
        method_starts = []
        for i in range(start, end):
            line = lines[i]
            if method_pattern.search(line):
                method_starts.append(i)

        if not method_starts:
            # 没有方法，直接按大小切分
            for i in range(0, len(class_section), MAX_CHUNK_SIZE - OVERLAP_CHARS):
                sub = class_section[i:i + MAX_CHUNK_SIZE]
                chunks.append({
                    "content": sub,
                    "metadata": _build_metadata(
                        file_path, project_path, project_name, lang,
                        sub, start + 1, end, class_name=cls_name
                    ),
                })
            continue

        # 按方法拆分，带 overlap
        for mi in range(len(method_starts)):
            m_start = method_starts[mi]
            # overlap：包含前面的类声明和字段
            overlap_start = max(start, m_start - 3)
            m_end = method_starts[mi + 1] if mi + 1 < len(method_starts) else end
            method_content = "\n".join(lines[overlap_start:m_end])

            m_name = ""
            m_match = re.search(r'(?:fun\s+)?(\w+)\s*[\(\{]', lines[m_start])
            if m_match:
                m_name = m_match.group(1)

            if len(method_content) > MAX_CHUNK_SIZE * 2:
                # 超大方法按 MAX_CHUNK_SIZE 再切
                for j in range(0, len(method_content), MAX_CHUNK_SIZE - OVERLAP_CHARS):
                    sub = method_content[j:j + MAX_CHUNK_SIZE]
                    chunks.append({
                        "content": sub,
                        "metadata": _build_metadata(
                            file_path, project_path, project_name, lang,
                            sub, m_start + 1, m_end, class_name=cls_name,
                            method_name=m_name
                        ),
                    })
            else:
                chunks.append({
                    "content": method_content,
                    "metadata": _build_metadata(
                        file_path, project_path, project_name, lang,
                        method_content, m_start + 1, m_end, class_name=cls_name,
                        method_name=m_name
                    ),
                })

    return chunks


def chunk_xml(content: str, file_path: str, project_path: str,
              project_name: str) -> list[dict]:
    """XML 文件分块：按 View 层级切分。"""
    chunks = []
    lines = content.split("\n")
    is_manifest = "AndroidManifest.xml" in file_path

    if is_manifest:
        return _chunk_manifest_xml(content, lines, file_path, project_path, project_name)

    # 布局文件：按第一层子 View 拆分
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        # XML 解析失败，按大小切分
        if len(content) <= MAX_CHUNK_SIZE:
            chunks.append({
                "content": content,
                "metadata": _build_metadata(
                    file_path, project_path, project_name, "xml",
                    content, 1, len(lines)
                ),
            })
            return chunks
        for i in range(0, len(content), MAX_CHUNK_SIZE - OVERLAP_CHARS):
            sub = content[i:i + MAX_CHUNK_SIZE]
            chunks.append({
                "content": sub,
                "metadata": _build_metadata(
                    file_path, project_path, project_name, "xml",
                    sub, 1, len(lines)
                ),
            })
        return chunks

    # 深度 ≤ 3 的 XML 整体作为一个块
    def _depth(el, d=1):
        if len(el) == 0:
            return d
        return max(_depth(c, d + 1) for c in el)

    if _depth(root) <= 3 and len(content) <= MAX_CHUNK_SIZE:
        chunks.append({
            "content": content,
            "metadata": _build_metadata(
                file_path, project_path, project_name, "xml",
                content, 1, len(lines)
            ),
        })
        return chunks

    # 按第一层子元素拆分
    for child in root:
        child_xml = ET.tostring(child, encoding="unicode")
        chunks.append({
            "content": child_xml,
            "metadata": _build_metadata(
                file_path, project_path, project_name, "xml",
                child_xml, 0, 0
            ),
        })

    return chunks


def _chunk_manifest_xml(content: str, lines: list, file_path: str,
                         project_path: str, project_name: str) -> list[dict]:
    """AndroidManifest.xml 专用分块：按组件拆分。"""
    chunks = []
    lang = "xml"

    # 提取 <application> 级别配置
    app_match = re.search(r'<application[^>]*>', content)
    if app_match:
        # application 标签本身的属性
        app_decl = app_match.group(0)
        chunks.append({
            "content": app_decl,
            "metadata": _build_metadata(
                file_path, project_path, project_name, lang,
                app_decl, 0, 0, component_type="application"
            ),
        })

    # 按 component 拆分
    component_tags = ["activity", "service", "receiver", "provider",
                       "activity-alias", "meta-data", "uses-permission",
                       "uses-feature", "intent-filter"]

    for tag in component_tags:
        pattern = re.compile(
            rf'(<{tag}(?:[^>]*?/?>|.*?</{tag}>))',
            re.DOTALL
        )
        for m in pattern.finditer(content):
            chunk_content = m.group(1)
            # 确定行号
            line_start = content[:m.start()].count("\n") + 1
            line_end = content[:m.end()].count("\n") + 1

            # 提取组件名称
            name_match = re.search(r'android:name="([^"]+)"', chunk_content)
            component_name = name_match.group(1) if name_match else ""

            chunks.append({
                "content": chunk_content,
                "metadata": _build_metadata(
                    file_path, project_path, project_name, lang,
                    chunk_content, line_start, line_end,
                    component_type=tag
                ),
            })

    # 如果拆得太碎（<2个），回退全文件
    if len(chunks) < 2 and len(content) <= MAX_CHUNK_SIZE:
        return [{
            "content": content,
            "metadata": _build_metadata(
                file_path, project_path, project_name, lang,
                content, 1, len(lines)
            ),
        }]

    return chunks


def chunk_gradle(content: str, file_path: str, project_path: str,
                 project_name: str) -> list[dict]:
    """Gradle 文件分块：按 task/block 边界切分。"""
    chunks = []
    lines = content.split("\n")
    lang = "gradle"

    # 尝试按大括号块拆分
    blocks = re.split(r'(\{[^}]*\})', content)
    current = ""
    for part in blocks:
        current += part
        if len(current) >= MAX_CHUNK_SIZE or part == blocks[-1]:
            chunks.append({
                "content": current.strip(),
                "metadata": _build_metadata(
                    file_path, project_path, project_name, lang,
                    current, 0, 0
                ),
            })
            current = ""

    if not current.strip() and not chunks:
        # 大括号块拆分失败，按大小切分
        for i in range(0, len(content), MAX_CHUNK_SIZE - OVERLAP_CHARS):
            sub = content[i:i + MAX_CHUNK_SIZE]
            chunks.append({
                "content": sub,
                "metadata": _build_metadata(
                    file_path, project_path, project_name, lang,
                    sub, 0, 0
                ),
            })

    return chunks


def chunk_text(content: str, file_path: str, project_path: str,
               project_name: str) -> list[dict]:
    """纯文本/Markdown 按段落切分。"""
    chunks = []
    lines = content.split("\n")
    lang = "markdown" if file_path.endswith(".md") else "text"

    # 按空行分隔段落
    paragraphs = re.split(r'\n\s*\n', content)
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(para) <= MAX_CHUNK_SIZE:
            chunks.append({
                "content": para,
                "metadata": _build_metadata(
                    file_path, project_path, project_name, lang,
                    para, 0, 0
                ),
            })
        else:
            for i in range(0, len(para), MAX_CHUNK_SIZE - OVERLAP_CHARS):
                sub = para[i:i + MAX_CHUNK_SIZE]
                chunks.append({
                    "content": sub,
                    "metadata": _build_metadata(
                        file_path, project_path, project_name, lang,
                        sub, 0, 0
                    ),
                })

    return chunks


def chunk_file(file_path: str, project_path: str, project_name: str) -> list[dict]:
    """根据文件类型分发到不同的分块器。"""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception:
        return []

    if not content.strip():
        return []

    ext = os.path.splitext(file_path)[1].lower()
    base = os.path.basename(file_path)

    if ext in (".java", ".kt"):
        return chunk_java_kotlin(content, file_path, project_path, project_name)
    elif base == "AndroidManifest.xml":
        return chunk_xml(content, file_path, project_path, project_name)
    elif ext == ".xml":
        return chunk_xml(content, file_path, project_path, project_name)
    elif ext in (".gradle", ".gradle.kts"):
        return chunk_gradle(content, file_path, project_path, project_name)
    else:
        # .md, .txt, .pro
        return chunk_text(content, file_path, project_path, project_name)


# ============================================================
# ChromaDB 客户端
# ============================================================

_chroma_client = None


def get_chroma_client() -> chromadb.PersistentClient:
    """获取全局 ChromaDB 客户端（懒初始化）。"""
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(
            path=CHROMA_PROJECTS_DIR,
            settings=Settings(
                anonymized_telemetry=False,
            ),
        )
    return _chroma_client


# ============================================================
# 索引构建
# ============================================================

def _sanitize_collection_name(name: str) -> str:
    """将项目名转为合法的 ChromaDB collection 名。"""
    # 转小写，保留字母数字和下划线
    sanitized = re.sub(r'[^a-z0-9_]', '_', name.lower())
    # 添加短 hash 避免冲突
    h = hashlib.md5(name.encode()).hexdigest()[:6]
    return f"project_{sanitized}_{h}"


def build_index(project_name: str, project_path: str,
                status_callback: Optional[Callable] = None) -> dict:
    """索引构建主函数（同步，建议在后台线程中调用）。

    Args:
        project_name: 用户指定的项目名称
        project_path: Android 项目路径
        status_callback: 进度回调函数，签名为 (step: str, progress: int, detail: dict)

    Returns:
        {"file_count": int, "chunk_count": int, "error": str|None}
    """
    collection_name = _sanitize_collection_name(project_name)

    try:
        # 1. 扫描文件
        if status_callback:
            status_callback("扫描中", 5, {"step": "scanning"})
        files = scan_files(project_path)
        if not files:
            return {"file_count": 0, "chunk_count": 0, "error": "未找到源码文件"}

        if status_callback:
            status_callback("扫描完成", 10, {"step": "scanning", "file_count": len(files)})

        # 2. 分块
        all_chunks = []
        total_files = len(files)

        for idx, file_path in enumerate(files):
            chunks = chunk_file(file_path, project_path, project_name)
            all_chunks.extend(chunks)

            if status_callback and idx % 5 == 0:
                progress = 10 + int((idx / total_files) * 50)
                status_callback("分块中", progress, {
                    "step": "chunking",
                    "current": idx + 1,
                    "total": total_files,
                    "chunk_count": len(all_chunks),
                })

        if not all_chunks:
            return {"file_count": len(files), "chunk_count": 0, "error": "未能从文件中提取代码块"}

        if status_callback:
            status_callback("分块完成", 60, {
                "step": "chunking",
                "file_count": total_files,
                "chunk_count": len(all_chunks),
            })

        # 3. 向量化并存入 ChromaDB
        if status_callback:
            status_callback("向量化中", 65, {"step": "embedding"})

        client = get_chroma_client()

        # 删除旧 collection（如果存在）
        try:
            client.delete_collection(collection_name)
        except Exception:
            pass

        collection = client.create_collection(
            name=collection_name,
            metadata={"project_name": project_name, "project_path": project_path},
        )

        # 分批添加
        batch_size = 100
        documents = []
        metadatas = []
        ids = []

        for i, chunk in enumerate(all_chunks):
            documents.append(chunk["content"])
            # ChromaDB metadata 只支持 str/int/float/bool
            meta = {}
            for k, v in chunk["metadata"].items():
                if isinstance(v, (str, int, float, bool)):
                    meta[k] = v
            metadatas.append(meta)
            ids.append(f"chunk_{i}")

            if len(documents) >= batch_size:
                collection.add(documents=documents, metadatas=metadatas, ids=ids)
                if status_callback:
                    progress = 65 + int((i / len(all_chunks)) * 30)
                    status_callback("向量化中", min(progress, 95), {
                        "step": "embedding",
                        "current": i + 1,
                        "total": len(all_chunks),
                    })
                documents = []
                metadatas = []
                ids = []

        # 最后一组
        if documents:
            collection.add(documents=documents, metadatas=metadatas, ids=ids)
            if status_callback:
                status_callback("向量化中", 95, {
                    "step": "embedding",
                    "current": len(all_chunks),
                    "total": len(all_chunks),
                })

        if status_callback:
            status_callback("索引完成", 100, {
                "step": "done",
                "file_count": total_files,
                "chunk_count": len(all_chunks),
            })

        return {
            "file_count": total_files,
            "chunk_count": len(all_chunks),
            "error": None,
        }

    except Exception as e:
        return {"file_count": 0, "chunk_count": 0, "error": str(e)}


# ============================================================
# 向量检索
# ============================================================

def retrieve(collection_name: str, query: str, file_filter: str = "",
             top_k: int = 5) -> list[dict]:
    """从指定 collection 中检索相关代码片段。

    Args:
        collection_name: ChromaDB collection 名称
        query: 自然语言查询
        file_filter: 可选文件名过滤
        top_k: 返回结果数量

    Returns:
        [{"content": str, "metadata": dict, "score": float}, ...]
    """
    try:
        client = get_chroma_client()
        collection = client.get_collection(collection_name)

        where_filter = None
        if file_filter:
            where_filter = {"file": {"$contains": file_filter}}

        results = collection.query(
            query_texts=[query],
            n_results=top_k,
            where=where_filter,
        )

        items = []
        if results["ids"] and results["ids"][0]:
            for i, chunk_id in enumerate(results["ids"][0]):
                items.append({
                    "content": results["documents"][0][i] if results["documents"] else "",
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    "score": (1.0 - results["distances"][0][i])
                    if results["distances"] else 0,
                })

        return items

    except Exception as e:
        return [{"content": f"检索失败: {str(e)}", "metadata": {}, "score": 0}]


# ============================================================
# RAGManager — 多项目生命周期管理
# ============================================================

class RAGManager:
    """管理多个 Android 项目的索引生命周期。

    持久化方式：JSON 文件（rag_projects.json）
    索引状态：indexing / ready / error
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._projects: dict = self._load()

    def _load(self) -> dict:
        """从 JSON 文件加载项目元数据。"""
        if os.path.exists(RAG_PROJECTS_FILE):
            try:
                with open(RAG_PROJECTS_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save(self):
        """持久化到 JSON 文件。"""
        os.makedirs(os.path.dirname(RAG_PROJECTS_FILE), exist_ok=True)
        with open(RAG_PROJECTS_FILE, "w", encoding="utf-8") as f:
            json.dump(self._projects, f, ensure_ascii=False, indent=2)

    def create_project(self, name: str, path: str) -> dict:
        """创建新项目并开始后台索引。

        Returns:
            {"name": str, "status": str, "message": str, "error": str|None}
        """
        with self._lock:
            # 校验
            if not name or len(name) > 50:
                return {"name": name, "status": "error", "message": "", "error": "项目名长度需在 1-50 字符之间"}
            if name in self._projects:
                existing = self._projects[name]
                if existing.get("status") == "indexing":
                    return {"name": name, "status": "error", "message": "", "error": "该项目正在索引中"}
                # 同名项目已存在，但不允许重复创建
                return {"name": name, "status": "error", "message": "", "error": "项目名已存在，请使用其他名称"}
            if not os.path.isdir(path):
                return {"name": name, "status": "error", "message": "", "error": "路径不存在"}

            collection_name = _sanitize_collection_name(name)

            project = {
                "name": name,
                "path": path,
                "collection_name": collection_name,
                "active": False,
                "status": "indexing",
                "progress": 0,
                "current_step": "扫描中",
                "current": 0,
                "total": 0,
                "file_count": 0,
                "chunk_count": 0,
                "indexed_at": None,
                "error": None,
            }
            self._projects[name] = project
            self._save()

            # 后台线程执行索引
            thread = threading.Thread(
                target=self._index_task,
                args=(name, path, collection_name),
                daemon=True,
            )
            thread.start()

            return {
                "name": name,
                "status": "indexing",
                "message": f"正在索引，请通过 GET /api/rag/projects/{name}/status 查看进度",
                "error": None,
            }

    def _index_task(self, name: str, path: str, collection_name: str):
        """后台索引任务。"""
        def status_callback(step: str, progress: int, detail: dict):
            with self._lock:
                if name in self._projects:
                    self._projects[name]["current_step"] = step
                    self._projects[name]["progress"] = progress
                    if "file_count" in detail:
                        self._projects[name]["file_count"] = detail["file_count"]
                    if "chunk_count" in detail:
                        self._projects[name]["chunk_count"] = detail["chunk_count"]
                    if "current" in detail and "total" in detail:
                        self._projects[name]["current"] = detail["current"]
                        self._projects[name]["total"] = detail["total"]
                    self._save()

        result = build_index(name, path, status_callback)

        with self._lock:
            if name in self._projects:
                if result["error"]:
                    self._projects[name]["status"] = "error"
                    self._projects[name]["error"] = result["error"]
                else:
                    self._projects[name]["status"] = "ready"
                    self._projects[name]["progress"] = 100
                    self._projects[name]["current_step"] = "索引完成"
                    self._projects[name]["file_count"] = result["file_count"]
                    self._projects[name]["chunk_count"] = result["chunk_count"]
                    self._projects[name]["indexed_at"] = datetime.now().isoformat()
                    # 自动激活
                    self._projects[name]["active"] = True
                    # 取消其他项目的激活
                    for pn, p in self._projects.items():
                        if pn != name:
                            p["active"] = False
                self._save()

    def delete_project(self, name: str) -> dict:
        """删除项目索引。"""
        with self._lock:
            if name not in self._projects:
                return {"error": "项目不存在"}

            project = self._projects[name]

            # 删除 ChromaDB collection
            try:
                client = get_chroma_client()
                client.delete_collection(project["collection_name"])
            except Exception:
                pass

            del self._projects[name]
            self._save()

            return {"message": f"项目 {name} 已删除", "error": None}

    def activate_project(self, name: str) -> dict:
        """切换激活项目。"""
        with self._lock:
            if name not in self._projects:
                return {"error": "项目不存在"}
            if self._projects[name]["status"] != "ready":
                return {"error": "项目未完成索引，无法激活"}

            for pn, p in self._projects.items():
                p["active"] = (pn == name)
            self._save()

            return {"message": f"已切换到项目 {name}", "error": None}

    def get_active_project(self) -> Optional[dict]:
        """获取当前激活项目的元数据。"""
        with self._lock:
            for p in self._projects.values():
                if p.get("active") and p.get("status") == "ready":
                    return dict(p)
        return None

    def list_projects(self) -> list[dict]:
        """列出所有已索引项目。"""
        with self._lock:
            return [dict(p) for p in self._projects.values()]

    def get_project_status(self, name: str) -> Optional[dict]:
        """获取单个项目的索引状态。"""
        with self._lock:
            if name in self._projects:
                return dict(self._projects[name])
        return None

    def reindex(self, name: str) -> dict:
        """全量重新索引项目。"""
        with self._lock:
            if name not in self._projects:
                return {"name": name, "status": "error", "message": "", "error": "项目不存在"}

            project = self._projects[name]
            if project.get("status") == "indexing":
                return {"name": name, "status": "error", "message": "", "error": "项目正在索引中，请等待完成"}

            # 标记为重新索引中
            project["status"] = "indexing"
            project["progress"] = 0
            project["current_step"] = "重新索引中"
            project["error"] = None
            self._save()

            thread = threading.Thread(
                target=self._reindex_task,
                args=(name,),
                daemon=True,
            )
            thread.start()

            return {
                "name": name,
                "status": "indexing",
                "message": f"正在重新索引，请通过 GET /api/rag/projects/{name}/status 查看进度",
            }

    def _reindex_task(self, name: str):
        """后台重新索引任务。"""
        with self._lock:
            project = self._projects.get(name)
        if not project:
            return

        self._index_task(name, project["path"], project["collection_name"])


# ============================================================
# 全局单例
# ============================================================

_rag_manager: Optional[RAGManager] = None


def get_rag_manager() -> RAGManager:
    """获取全局 RAGManager 单例。"""
    global _rag_manager
    if _rag_manager is None:
        _rag_manager = RAGManager()
    return _rag_manager
