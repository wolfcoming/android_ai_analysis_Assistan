# Android 项目 RAG — 需求与技术方案

> 版本: v0.2 | 更新日期: 2026-07-14

## 一、需求背景

安卓开发助手 Agent 目前能通过 ADB 工具采集设备运行时数据（内存、CPU、帧率、日志等），但无法回答**"这个 Android 项目的代码是怎么写的"**这类问题。

**目标**：将一个 Android 项目（Java/Kotlin/XML）作为 RAG 知识库，让 Agent 在回答时能检索项目源码，结合运行时数据和代码实现给出精准诊断。

**产品定位**：该项目作为完整产品提供给其他开发者使用，RAG 功能需要支持**动态关联不同 Android 项目**。

---

## 二、典型使用场景

| 场景 | 用户提问 | Agent 应答 |
|------|---------|-----------|
| **定位代码** | "Bitmap 在哪里分配的？" | 检索到 `ImageLoader.java:L45`，展示代码 + 给出建议 |
| **架构理解** | "项目的模块结构是什么？" | 检索到 `settings.gradle`、各模块入口类，展示架构图 |
| **内存泄漏** | "Agent 报 float[] 占 921MB，代码中哪里可能有问题？" | 检索到 `TextureManager.kt` 中的大数组分配，定位具体行 |
| **性能优化** | "主线程做了什么耗时操作？" | 检索到 `MainActivity.onCreate()` 中的同步 IO 调用 |
| **崩溃分析** | "logcat 显示 NPE 在 com.xxx.foo.Bar，帮我看看代码" | 检索到 `Bar.java` 对应行，展示上下文代码 |

---

## 三、交互方案：前端 UI 配置

### 3.1 设计原则

- **RAG 管理通过前端 UI 完成**（索引、切换、删除），不通过 Agent 对话
- **Agent 只负责检索**：对话时自动检索当前激活项目的代码
- **降低 Agent 复杂性**：不让 Agent 参与索引管理，只做代码查询

### 3.2 前端 UI 布局

在现有三栏布局的「实时性能」指标下方，新增「知识库」管理栏：

```
┌──────────────┬─────────────────────────┬──────────────────────┐
│  会话列表     │      对话面板            │     信息面板          │
│              │                         │                      │
│  + 新对话    │  消息1                   │  📊 实时性能指标      │
│  ──────────  │  消息2                   │  CPU / FPS / PSS     │
│  ● 会话A     │  消息3                   │                      │
│  ● 会话B     │  ...                     │  ────────────────    │
│              │                         │                      │
│              │                         │  📚 项目知识库 ← 新增 │
│              │                         │  ┌──────────────────┐ │
│              │                         │  │ Android 项目路径: │ │
│              │                         │  │ [/path/to/app  ] │ │
│              │                         │  │ [开始索引]        │ │
│              │                         │  │                  │ │
│              │                         │  │ 当前项目: my-app │ │
│              │                         │  │ 状态: ✅ 已激活   │ │
│              │                         │  │ 文件: 347        │ │
│              │                         │  │ 代码块: 1,234    │ │
│              │                         │  │ 索引时间: 15:30  │ │
│              │                         │  │                  │ │
│              │                         │  │ 已索引项目:       │ │
│              │                         │  │ ● my-app  [激活] │ │
│              │                         │  │   douyin  [切换] │ │
│              │                         │  │   wechat  [切换] │ │
│              │                         │  └──────────────────┘ │
│              │                         │                      │
│              │                         │  📈 历史趋势          │
│              │  输入框                  │  折线图               │
└──────────────┴─────────────────────────┴──────────────────────┘
```

### 3.3 UI 交互流程

#### 索引新项目
```
1. 用户填入项目名称（必填）和项目路径（必填）
2. 点击「开始索引」按钮
3. 前端每 2 秒轮询 GET /api/rag/projects/{name}/status
4. 显示进度条 + 状态文字（扫描中 → 分块中 → 向量化中）
5. 索引完成 → 自动激活为当前项目
6. 显示统计信息（文件数、代码块数）
```

**进度轮询方案**：
- 索引是耗时操作（30秒~2分钟），HTTP 请求会超时
- 采用轮询方案（每 2 秒 GET 状态），简单可靠
- 后端维护每个项目的索引进度状态（`indexing` / `ready` / `error`）

#### 切换项目
```
1. 在已索引项目列表中，点击其他项目的「切换」按钮
2. 调用 PUT /api/rag/projects/{name}/activate
3. 当前项目标记更新
4. Agent 后续检索自动使用新项目
```

#### 删除项目
```
1. 点击项目的「删除」按钮
2. 弹出确认对话框
3. 调用 DELETE /api/rag/projects/{name}
4. 如果项目正在索引中，先取消索引再删除
```

#### 重新索引
```
1. 当前项目代码有更新时，点击「重新索引」
2. 调用 POST /api/rag/projects/{name}/reindex
3. 全量重新索引（第一版不做增量更新）
```

---

## 四、技术方案

### 4.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│  前端 (Vue 3)                                                   │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  知识库管理组件 (KnowledgePanel)                           │ │
│  │  - 项目路径输入框                                           │ │
│  │  - 索引按钮 + 进度条                                       │ │
│  │  - 已索引项目列表                                           │ │
│  │  - 当前激活项目状态                                         │ │
│  └────────────────────────────────────────────────────────────┘ │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTP API
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  后端 (FastAPI)                                                  │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────┐ │
│  │ RAG Manager  │  │ RAG Scanner  │  │ RAG Retriever          │ │
│  │              │  │              │  │                        │ │
│  │ 多项目管理    │  │ 文件扫描     │  │ 向量检索               │ │
│  │ Collection   │  │ 智能分块     │  │ 代码片段返回            │ │
│  │ 切换/删除    │  │ 元数据提取   │  │                        │ │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬─────────────┘ │
│         │                 │                      │               │
│         ▼                 ▼                      ▼               │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  ChromaDB (PersistentClient)                             │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐               │   │
│  │  │ my-app   │  │ douyin   │  │ wechat   │  ...          │   │
│  │  │(collection)│  │(collection)│  │(collection)│           │   │
│  │  └──────────┘  └──────────┘  └──────────┘               │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│  Agent (LangChain)                                               │
│                                                                  │
│  query_android_code 工具                                         │
│  → 自动检索当前激活项目的代码                                      │
│  → 返回相关代码片段给 LLM                                         │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 多项目隔离方案

采用 **Collection 级隔离**：每个 Android 项目对应 ChromaDB 中一个独立的 collection。

```
chroma_projects/           ← ChromaDB 持久化目录
├── chroma.sqlite3         ← 所有 collection 共享一个存储文件
└── ...

ChromaDB 内部:
├── collection "project_my-app"     ← 项目 A
├── collection "project_douyin"     ← 项目 B
└── collection "project_wechat"     ← 项目 C
```

**为什么选 Collection 级隔离（而非独立实例）**：
- ChromaDB 的 `PersistentClient` 天然支持多 collection
- 查询时指定 collection name 即可，互不干扰
- 管理简单，无需维护多个目录
- 满足项目数 < 100 的场景

### 4.3 项目标识

**项目名由用户指定（必填）**，避免从路径自动提取导致同名冲突（如多个项目都叫 `app`）：

```python
# 用户通过前端 UI 指定项目名称
project = {
    "name": "微信Android版",                     # 用户指定（必填，唯一）
    "path": "/Users/yangqing/project/wechat",    # 实际路径
    "collection_name": "project_微信android版",  # ChromaDB collection 名（自动转小写 + hash）
    "active": True,                              # 是否激活
    "indexed_at": "2026-07-14T15:30:00",         # 索引时间
    "file_count": 347,                           # 文件数
    "chunk_count": 1234,                         # 代码块数
}
```

**命名规则**：
- 名称不可重复（后端校验）
- 名称长度 1-50 字符
- Collection 名自动转小写，中文保留，避免特殊字符

### 4.4 Android 项目文件支持

| 文件类型 | 扩展名 | 分块策略 |
|---------|--------|---------|
| Java | `.java` | 按类/方法边界切分 |
| Kotlin | `.kt` | 按类/函数/companion object 边界切分 |
| XML 布局 | `.xml` | 按 View 层级切分（保持完整 View 块） |
| Gradle | `.gradle`, `.gradle.kts` | 按 task/block 边界切分 |
| Manifest | `AndroidManifest.xml` | 按 component（Activity/Service/Receiver）切分 |
| 资源文件 | `.xml`（res/） | 按资源类型分组 |
| ProGuard | `.pro` | 整文件（通常较小） |
| 说明文档 | `.md`, `.txt` | 按段落切分 |

**排除目录**：`build/`, `.gradle/`, `.idea/`, `.git/`, `node_modules/`, `.cxx/`

**排除文件**：`.class`, `.apk`, `.aar`, `.jar`, `.png`, `.jpg`, `.webp`, `.so`, `.dex`

### 4.5 智能分块策略

#### Java/Kotlin 类文件

```java
// 按方法/类边界切分，保留完整方法体
public class ImageLoader {           // ← 块起始（类声明 + 字段）
    private Bitmap loadBitmap() {    // ← 子块（方法1）
        ...
    }
    public void clear() {            // ← 子块（方法2）
        ...
    }
}                                    // ← 块结束
```

规则：
- 每个类作为独立块（如果类 < 1500 字符）
- 大类按方法拆分，每个方法为一个块
- 块头包含：文件路径、类名、方法签名、行号范围
- 块之间保留 200 字符 overlap（包含 import 和字段声明）

#### XML 布局文件

```xml
<!-- 按 View 层级切分，保持完整 View 块 -->
<LinearLayout>                      <!-- ← 块1：外层容器 -->
    <TextView ... />                 <!-- ← 块2：文本组件 -->
    <RecyclerView ... />             <!-- ← 块3：列表组件 -->
</LinearLayout>
```

规则：
- 深度 ≤ 3 的 XML 直接作为整体块
- 深度 > 3 的按第一层子 View 拆分
- 每个块包含完整属性信息

#### AndroidManifest.xml
- 按 `<activity>`, `<service>`, `<receiver>`, `<provider>` 拆分
- `<application>` 级别配置单独成块

### 4.6 元数据设计

每个代码块携带丰富的元数据，支持精确过滤：

```python
{
    "file": "app/src/main/java/com/example/ImageLoader.java",
    "line_start": 45,
    "line_end": 89,
    "lang": "java",                    # java/kotlin/xml/gradle
    "class_name": "ImageLoader",       # 类名（Java/Kotlin）
    "method_name": "loadBitmap",       # 方法名（可选）
    "module": "app",                   # 所属模块（从路径提取）
    "package": "com.example",          # 包名（从路径提取）
    "component_type": "",              # 组件类型（AndroidManifest 用）
    "project": "my-app",              # 所属项目
}
```

### 4.7 Embedding 方案

两级方案（去掉无语义的哈希 Embedding，避免上线后检索质量差）：

```
1. ChromaDB Default (all-MiniLM-L6-v2)          ← 首选，本地模型，零配置
2. OpenAI Embedding (text-embedding-3-small)     ← 可选，精度更高，需 API Key
```

**为什么首选 ChromaDB Default**：
- 安装 chromadb 即自带，无需额外配置
- 本地运行，无 API 调用费用
- 对中文代码的语义匹配效果足够好
- 如果需要更高精度，可切换到 OpenAI Embedding

### 4.8 Agent 工具设计

Agent 新增 `query_android_code` 工具，**只做检索，不做索引管理**。

**参数设计原则**：简化为 2 个参数，避免 LLM 同时填多个参数导致调用失败。类名、模块等过滤条件由 LLM 自然语言表达在 query 中：

```python
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
    active_project = get_active_project()
    if not active_project:
        return "[无激活项目] 请先在前端「知识库」面板中索引 Android 项目"
    results = retrieve(active_project["collection_name"], query, file_filter)
    return results
```

**为什么只保留 2 个参数**：
- LLM 容易填错 5 个参数，导致检索失败
- 类名、模块等信息 LLM 完全可以自然语言表达在 query 中（如 "ImageLoader 类的 Bitmap 加载逻辑"）
- 向量检索本身能处理自然语言查询，不需要精确过滤

### 4.9 检索方案

#### 第一版：纯向量检索（足够满足 80% 场景）
- 使用 ChromaDB 的 `collection.query()` 进行语义相似度匹配
- 支持按 `where` 条件过滤（如 file_filter）
- 返回 Top-K 相关代码片段

#### 第二版（后续扩展）：向量 + 关键词混合
- **向量检索**：语义相似度匹配（"Bitmap 泄漏" 能匹配到 "图片未回收"）
- **关键词检索**：精确匹配类名、方法名（用户输入完整类名时直接定位）
- 两者结果融合，去重后返回 Top-K

**为什么第一版不做混合检索**：
- 关键词检索需要额外实现倒排索引，ChromaDB 原生不支持
- 向量检索对自然语言查询效果已经很好
- 如果用户输入完整类名，向量检索也能匹配到（只是精度略低）
- 先上线验证效果，需要时再加混合检索

---

## 五、API 设计

### 5.1 RAG 管理 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/rag/projects` | GET | 列出所有已索引项目 |
| `/api/rag/projects` | POST | 创建新项目并开始索引 |
| `/api/rag/projects/{name}` | DELETE | 删除项目索引 |
| `/api/rag/projects/{name}/activate` | PUT | 切换激活项目 |
| `/api/rag/projects/{name}/reindex` | POST | 重新索引项目 |
| `/api/rag/projects/{name}/status` | GET | 获取索引状态/进度 |
| `/api/rag/active` | GET | 获取当前激活项目信息 |

### 5.2 RAG 查询 API（调试用）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/rag/query` | GET | 检索测试（`?q=xxx&top_k=5`） |

### 5.3 请求/响应示例

#### 创建项目并索引
```
POST /api/rag/projects
{
    "path": "/Users/yangqing/project/my-app"
}
→ 202 Accepted
{
    "name": "my-app",
    "status": "indexing",
    "message": "正在索引，请通过 GET /api/rag/projects/my-app/status 查看进度"
}
```

#### 查看索引进度
```
GET /api/rag/projects/my-app/status
→ 200 OK
{
    "name": "my-app",
    "status": "indexing",        # indexing / ready / error
    "progress": 65,              # 百分比
    "current_step": "向量化中",   # 当前步骤
    "file_count": 347,
    "chunk_count": 1234
}
```

#### 列出所有项目
```
GET /api/rag/projects
→ 200 OK
{
    "projects": [
        {
            "name": "my-app",
            "path": "/Users/yangqing/project/my-app",
            "status": "ready",
            "active": true,
            "file_count": 347,
            "chunk_count": 1234,
            "indexed_at": "2026-07-14T15:30:00"
        },
        {
            "name": "douyin",
            "path": "/Users/yangqing/project/douyin",
            "status": "ready",
            "active": false,
            "file_count": 567,
            "chunk_count": 2345,
            "indexed_at": "2026-07-13T10:00:00"
        }
    ],
    "active_project": "my-app"
}
```

---

## 六、目录结构

```
server/
├── rag_android.py        # 新增：Android 项目 RAG 核心
│   ├── scan_files()      #   文件扫描（Java/Kotlin/XML/Gradle）
│   ├── chunk_file()      #   智能分块（按类/方法/布局边界）
│   ├── build_index()     #   向量化 + 存入 ChromaDB
│   ├── retrieve()        #   向量检索
│   └── RAGManager        #   多项目生命周期管理
├── routes/
│   └── rag.py            # 新增：RAG 管理 API 路由
└── rag.py                # 已有：Agent 自身代码 RAG（保留）

web/
├── app.js                # 修改：新增 KnowledgePanel 组件
└── index.html            # 修改：新增知识库管理 X-Template

agent/
├── config.py             # 修改：注册 query_android_code 工具
└── tools/
    └── android_rag.py    # 新增：query_android_code 工具定义
```

---

## 七、依赖

```
chromadb>=0.4.0          # 向量数据库（已有）
openai                   # Embedding API（已有）
```

无需额外依赖。分块逻辑纯 Python 实现（正则 + XML 解析用内置 `xml.etree.ElementTree`）。

---

## 八、性能预估

| 指标 | 预估值 |
|------|--------|
| 中型 Android 项目（300 文件） | 索引约 30 秒 |
| 大型 Android 项目（1000 文件） | 索引约 2 分钟 |
| 单次检索延迟 | < 200ms |
| ChromaDB 存储占用 | 约 50MB（300 文件项目） |
| Embedding API 费用 | 约 ¥0.01（300 文件） |

---

## 九、错误处理与边界场景

### 9.1 索引阶段错误

| 场景 | 处理方式 |
|------|----------|
| 项目路径不存在 | 返回 400 错误，提示"路径不存在" |
| 项目目录为空（无源码文件） | 返回 400 错误，提示"未找到源码文件" |
| 项目名称已存在 | 返回 409 冲突，提示"项目名已存在，请使用其他名称" |
| ChromaDB 启动失败 | 返回 500 错误，日志记录详细错误，不影响其他功能 |
| Embedding API 调用失败 | 重试 3 次，超时后降级到 ChromaDB Default |
| 索引过程中用户点击「删除」 | 先取消索引任务，再删除数据 |

### 9.2 检索阶段错误

| 场景 | 处理方式 |
|------|----------|
| 无激活项目 | 返回提示"请先在前端「知识库」面板中索引 Android 项目" |
| 检索无结果 | 返回"未找到相关代码，请尝试换个查询词" |
| ChromaDB 连接失败 | 返回"知识库服务不可用，请重启服务" |

### 9.3 并发控制

| 场景 | 处理方式 |
|------|----------|
| 同时索引两个大项目 | 排队处理，第二个请求返回"已有索引任务进行中，请等待" |
| 索引过程中服务重启 | 索引状态标记为 `error`，用户需手动重新索引 |

---

## 十、后续扩展

1. **增量索引**：监听文件变化（watchdog），自动更新变更文件的索引
2. **运行时关联**：ADB 报告中的类名自动关联到代码块
3. **调用链分析**：检索时自动展开上下游调用
4. **可视化依赖图**：生成模块/类之间的调用关系图
5. **代码搜索面板**：前端新增代码搜索结果展示（代码高亮 + 文件跳转）
6. **混合检索**：向量 + 关键词混合检索，提升精确匹配场景的召回率
