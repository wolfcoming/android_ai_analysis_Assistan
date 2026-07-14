"""Agent 工具 — query_android_code：检索当前激活 Android 项目的源码"""

from langchain_core.tools import tool

from server.rag_android import get_rag_manager, retrieve


@tool
def query_android_code(query: str, file_filter: str = "") -> str:
    """检索当前激活的 Android 项目源码。
    当用户询问项目代码实现、类/方法位置、XML 布局结构、
    AndroidManifest 配置、Gradle 依赖等时使用。
    需要用户先在前端「知识库」面板中索引 Android 项目。

    Args:
        query: 查询内容，如 "Bitmap 加载逻辑"、"ImageLoader 类的实现"
        file_filter: 可选，按文件名过滤，如 "ImageLoader.java"
    """
    mgr = get_rag_manager()
    active_project = mgr.get_active_project()

    if not active_project:
        return "[无激活项目] 请先在前端「知识库」面板中索引 Android 项目"

    results = retrieve(
        collection_name=active_project["collection_name"],
        query=query,
        file_filter=file_filter,
        top_k=5,
    )

    if not results or (len(results) == 1 and "检索失败" in results[0].get("content", "")):
        return "未找到相关代码，请尝试换个查询词"

    # 格式化结果
    output_parts = []
    for i, r in enumerate(results):
        meta = r.get("metadata", {})
        file_path = meta.get("file", "unknown")
        line_start = meta.get("line_start", "?")
        line_end = meta.get("line_end", "?")
        lang = meta.get("lang", "")
        class_name = meta.get("class_name", "")
        method_name = meta.get("method_name", "")
        score = r.get("score", 0)

        header = f"### 结果 {i + 1} (相关性: {score:.0%})"
        if class_name:
            header += f" - {class_name}"
            if method_name:
                header += f".{method_name}"

        location = f"`{file_path}:{line_start}-{line_end}`"
        code_block = f"```{lang}\n{r['content'].strip()}\n```"

        output_parts.append(f"{header}\n{location}\n{code_block}")

    header = f"检索到 {len(results)} 个相关代码片段（项目: {active_project['name']}）：\n\n"
    return header + "\n\n".join(output_parts)
