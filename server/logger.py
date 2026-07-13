"""Agent 运行日志 — 追踪完整的请求-推理-工具调用-响应流程

设计原则：
- 纯 print + ANSI 颜色，零依赖
- 用 emoji 区分不同事件类型，一眼能看懂
- 用缩进展示层级关系
- 每个关键步骤打印耗时
"""

import sys
import time
from typing import Optional

# ===== ANSI 颜色 =====
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
RED = "\033[31m"
BLUE = "\033[34m"
RESET = "\033[0m"


def _now() -> str:
    """返回当前时间字符串 HH:MM:SS"""
    return time.strftime("%H:%M:%S")


def _elapsed(start: float) -> str:
    """返回带颜色的耗时"""
    sec = time.time() - start
    if sec < 0.5:
        return f"{GREEN}{sec:.2f}s{RESET}"
    elif sec < 2:
        return f"{YELLOW}{sec:.2f}s{RESET}"
    else:
        return f"{RED}{sec:.2f}s{RESET}"


# ===== 全局计数器（Agent 循环轮次）=====
_round_counter = 0


def reset_round_counter():
    global _round_counter
    _round_counter = 0


def _next_round():
    global _round_counter
    _round_counter += 1
    return _round_counter


# ===== 顶层日志函数 =====


def log_request(session_id: str, message: str):
    """打印请求进入"""
    brief = message[:60] + ("..." if len(message) > 60 else "")
    print(f"\n{CYAN}{BOLD}╔══════════════════════════════════════════════════════════════╗{RESET}")
    print(f"{CYAN}{BOLD}║{RESET}  {YELLOW}📨 收到请求{RESET}  {DIM}{_now()}{RESET}")
    print(f"{CYAN}{BOLD}║{RESET}  会话: {session_id}")
    print(f"{CYAN}{BOLD}║{RESET}  消息: {BLUE}{brief}{RESET}")
    print(f"{CYAN}{BOLD}╚══════════════════════════════════════════════════════════════╝{RESET}")


def log_session_loaded(msg_count: int, session_title: str):
    """打印会话加载信息"""
    print(f"  💾 加载历史: {GREEN}{msg_count}{RESET} 条消息 | 会话: {session_title}")


def log_compression_decision(total_tokens: int, threshold: int, to_compress: int, to_keep: int):
    """打印压缩决策"""
    if total_tokens > threshold:
        print(f"  🗜️  触发压缩: {total_tokens} tokens > 阈值 {threshold}")
        print(f"      待压缩 {YELLOW}{to_compress}{RESET} 条 → 保留最近 {GREEN}{to_keep}{RESET} 条")
    else:
        print(f"  📏 Token 检查: {total_tokens} / {threshold} (未触发压缩)")


def log_compression_done(summary_len: int, elapsed_s: float):
    """打印压缩完成"""
    print(f"  ✅ 压缩完成: 摘要 {summary_len} 字 ({elapsed_s:.1f}s)")


def log_agent_start(message: str, has_history: bool, has_summary: bool):
    """打印 Agent 开始运行"""
    print(f"\n  {MAGENTA}{BOLD}┌─ 🤖 Agent 开始推理 ─────────────────────────────┐{RESET}")
    print(f"  {MAGENTA}│{RESET}  输入: {BLUE}{message[:80]}{'...' if len(message)>80 else ''}{RESET}")
    print(f"  {MAGENTA}│{RESET}  历史: {'有' if has_history else '无'} | 摘要: {'有' if has_summary else '无'}")
    print(f"  {MAGENTA}│{RESET}")
    reset_round_counter()


def log_agent_end(output_len: int, total_time: float):
    """打印 Agent 运行结束"""
    print(f"  {MAGENTA}│{RESET}")
    print(f"  {MAGENTA}│{RESET}  💬 最终回复: {output_len} 字 | 总耗时 {_elapsed(time.time() - total_time)}")
    print(f"  {MAGENTA}└────────────────────────────────────────────────┘{RESET}")


def log_response_saved(msg_len: int):
    """打印响应保存"""
    print(f"\n  💾 响应已保存到 DB: {msg_len} 字\n")


def log_error(step: str, error: str):
    """打印错误"""
    print(f"  {RED}❌ [{step}] {error}{RESET}")


# ===== Agent 循环日志 =====


def log_agent_thinking(thought: str):
    """打印 LLM 推理过程（Agent 每次决定下一步之前都会输出推理）"""
    r = _next_round()
    # 截取前 150 字
    brief = thought[:150].replace("\n", " ") + ("..." if len(thought) > 150 else "")
    print(f"  {MAGENTA}│{RESET}  {BOLD}{r}️⃣  🧠 推理{RESET}: {DIM}{brief}{RESET}")


def log_tool_call(tool_name: str, tool_input: str, round_num: Optional[int] = None):
    """打印工具调用"""
    r = round_num or _round_counter
    brief_input = tool_input[:80] + ("..." if len(tool_input) > 80 else "")
    print(f"  {MAGENTA}│{RESET}     📞 调用 {CYAN}{tool_name}{RESET}({DIM}{brief_input}{RESET})")


def log_tool_result(tool_name: str, output: str, elapsed_s: float):
    """打印工具返回结果"""
    brief = output[:100].replace("\n", " ") + ("..." if len(output) > 100 else "")
    print(f"  {MAGENTA}│{RESET}     ✅ {tool_name} 返回 ({_elapsed(time.time() - elapsed_s)})")
    print(f"  {MAGENTA}│{RESET}        {DIM}{brief}{RESET}")


def log_tool_error(tool_name: str, error: str):
    """打印工具错误"""
    brief = error[:100].replace("\n", " ")
    print(f"  {MAGENTA}│{RESET}     {RED}❌ {tool_name} 出错: {brief}{RESET}")


def log_agent_final_answer(thought: str):
    """打印 Agent 最终决策（给出回复而非调用工具）"""
    brief = thought[:150].replace("\n", " ") + ("..." if len(thought) > 150 else "")
    print(f"  {MAGENTA}│{RESET}  {BOLD}🏁 给出答案{RESET}: {DIM}{brief}{RESET}")
