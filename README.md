# 安卓开发助手 (Android Dev Assistant)

一个基于 LangChain + ADB 的智能安卓开发辅助工具，通过自然语言对话帮助开发者查询设备/应用信息、诊断卡顿和内存问题。

## 功能亮点

- **自然语言交互** — 用中文描述问题，Agent 自动执行诊断命令并解读结果
- **实时性能面板** — 右侧面板持续展示设备信息、应用状态、CPU/内存/FPS/掉帧实时指标
- **历史趋势图** — 5 张折线图（PSS / Java Heap / Native Heap / FPS / CPU）5 分钟时间窗口
- **流式推理可见** — LLM 思考过程和工具调用实时打印，非黑盒
- **一键内存诊断** — 对 debuggable 应用执行 heap dump 分析，输出 Top 类直方图
- **多 LLM 可切换** — `.env` 中改 `LLM_PROVIDER`，支持 DeepSeek / OpenAI 兼容接口（ollama、vLLM 等）

## 界面预览

```
┌─────────────────────┬────────────────────────────┐
│  对话面板 (左侧)      │  信息面板 (右侧)             │
│                     │                            │
│  ┌───────────────┐  │  设备概览: Xiaomi 2211333C  │
│  │ Agent: 你好!   │  │  Android 16, 8核, 8GB RAM │
│  │ 有什么可以帮你? │  │                            │
│  └───────────────┘  │  目标应用: com.tencent.mm   │
│                     │                            │
│  ┌───────────────┐  │  实时性能:                  │
│  │ User: 帮我看看 │  │  PSS 285MB | JavaHeap 45MB │
│  │ 微信内存占用   │  │  CPU 3% | FPS 60 | 掉帧 0  │
│  └───────────────┘  │                            │
│                     │  ┌─ PSS (MB) ────────────┐ │
│  ┌───────────────┐  │  │ ▁▂▃▄▅▆▇█▇▆▅▄▃▂▁    │ │
│  │ 💭 正在获取…   │  │  └──────────────────────┘ │
│  │ ⏳ get_app    │  │  ┌─ FPS ─────────────────┐ │
│  │     _memory   │  │  │ ████████████████████  │ │
│  └───────────────┘  │  └──────────────────────┘ │
│                     │                            │
│  [输入框]    [发送]  │  快捷操作: [一键内存诊断]   │
└─────────────────────┴────────────────────────────┘
```

## 技术栈

| 层 | 技术 |
|---|------|
| Agent 框架 | LangChain 1.0 + DeepSeek / OpenAI 兼容 |
| 后端 | FastAPI + Uvicorn + SSE 流式 |
| 前端 | Vue 3 CDN + Chart.js — 零构建工具 |
| 数据采集 | ADB (dumpsys / logcat / top / gfxinfo / heap dump) |
| 解析 | 自研 dumpsys / hprof 二进制解析器 |

## 快速开始

### 前置条件

- Python 3.10+
- Android SDK Platform Tools（`adb` 在 PATH 中，`hprof-conv` 用于 heap dump 分析）
- 一台通过 USB 连接的 Android 手机（已开启开发者模式 & USB 调试）
- DeepSeek API Key（或其他 OpenAI 兼容的 API Key）

### 1. 克隆并安装依赖

```bash
git clone <your-repo-url>
cd agent

python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入你的 API Key
```

`.env` 示例：

```bash
# LLM 提供商: deepseek / openai_compatible
LLM_PROVIDER=deepseek

# DeepSeek 配置
DEEPSEEK_API_KEY=sk-your-key-here
DEEPSEEK_MODEL=deepseek-chat

# OpenAI 兼容配置（可选，切换 LLM_PROVIDER=openai_compatible 后生效）
OPENAI_API_KEY=sk-your-key-here
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o
```

### 3. 连接手机

```bash
# 验证 ADB 连接
adb devices

# 应输出类似:
# List of devices attached
# 930e356e    device
```

### 4. 启动

```bash
source venv/bin/activate
python -m uvicorn server.main:app --host 0.0.0.0 --port 8765
```

浏览器打开 `http://localhost:8765`。

## 项目结构

```
agent/
├── agent/                      # Agent 核心
│   ├── agent.py                # Agent 创建 + 流式执行
│   ├── llm.py                  # 多模型切换
│   ├── parser/                 # dumpsys / logcat 解析器
│   │   ├── dumpsys.py
│   │   └── logcat.py
│   └── tools/                  # ADB 工具集
│       ├── adb_device.py       # 设备信息 + ADB 命令
│       ├── adb_app.py          # 应用信息 + 内存详情
│       ├── adb_perf.py         # 帧率分析 + CPU 占用
│       ├── adb_system.py       # 截图 + 崩溃日志 + ANR
│       ├── adb_dump.py         # Heap dump + 诊断流程
│       └── hprof_parser.py     # hprof 二进制解析器
├── server/                     # FastAPI 后端
│   ├── main.py                 # 入口 + 静态文件
│   ├── sse.py                  # SSE 实时推送 (2s)
│   ├── history.py              # 环形缓冲区（趋势数据）
│   └── routes/
│       ├── chat.py             # POST /api/chat (SSE 流式)
│       └── device.py           # GET /api/device/*
├── web/                        # Vue 3 前端
│   ├── index.html              # 主页面 + 样式
│   ├── app.js                  # Vue 应用 (ChatPanel + InfoPanel + TrendChart)
│   └── components/             # (已合并到 app.js)
├── my_agent.py                 # CLI 版 Agent（独立调试用）
├── requirements.txt
├── .gitignore
└── README.md
```

## Agent 工具清单

| 工具 | 功能 | 数据源 |
|------|------|--------|
| `get_device_info` | 设备型号、系统版本、CPU、内存、分辨率 | `adb shell getprop` |
| `get_app_info` | 应用包名、版本、进程、Activity | `adb shell dumpsys package` |
| `get_app_memory` | PSS / Java Heap / Native Heap 等内存详情 | `adb shell dumpsys meminfo` |
| `get_frame_info` | 帧率统计 (FPS) / 掉帧 (Jank) 分析 | `adb shell dumpsys gfxinfo` |
| `get_cpu_info` | 应用 CPU 占用率 | `adb shell top` |
| `get_crash_logs` | 崩溃堆栈提取 | `adb logcat` |
| `get_anr_info` | ANR 检测及 trace 提取 | `adb shell dumpsys activity` |
| `capture_screenshot` | 截取手机当前屏幕 | `adb shell screencap` |
| `memory_diagnosis` | 一键 heap dump → 类直方图分析 | `am dumpheap` + 自研 hprof 解析器 |
| `execute_adb_command` | 执行任意 ADB 命令（兜底） | 通用 ADB |
| `list_files` | 列出设备文件 | `adb shell ls` |

## 一键内存诊断

对 debuggable 应用执行完整的 heap dump → pull → 解析流程，返回 Top 50 内存大户：

```
| 类名 | 实例数 | 总大小 (MB) |
|------|--------|-------------|
| android.graphics.Bitmap | 245 | 98.5 |
| byte[] | 1024 | 45.2 |
| java.lang.String | 8300 | 18.7 |
```

**限制**：目标应用必须是 debuggable 的（debug 构建 / root 手机 / userdebug 镜像）。

## License

MIT
