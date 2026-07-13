"""上下文压缩 — Token 计数 + 对话摘要压缩"""

import re
from typing import Optional


# 压缩阈值（Token 数），超过时触发摘要压缩
COMPRESS_THRESHOLD = 8000

# 保留的最近轮次数（不参与压缩）
KEEP_RECENT_TURNS = 6


def estimate_tokens(text: str) -> int:
    """
    估算文本的 token 数量（启发式算法）。
    中文 1 字符 ≈ 1.5 token，英文 1 词 ≈ 1 token。

    精确度足够用于触发压缩判断，不需要 tiktoken 依赖。
    """
    if not text:
        return 0

    # 统计中文/日文/韩文 字符
    cjk_chars = len(re.findall(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]', text))
    # 统计英文单词（连续的字母序列）
    english_words = len(re.findall(r'[a-zA-Z]+', text))
    # 其余字符（数字、符号、空格等）
    remaining = max(0, len(text) - cjk_chars - english_words * 5)  # 粗略估计英文单词平均5字符

    tokens = cjk_chars * 1.5 + english_words * 1.0 + remaining * 0.25
    return int(tokens)


def estimate_messages_tokens(messages: list[dict]) -> int:
    """估算消息列表的总 token 数"""
    total = 0
    for msg in messages:
        total += estimate_tokens(msg.get("content", "")) + 4  # role 开销约 4 token
    return total


def needs_compression(messages: list[dict], threshold: int = COMPRESS_THRESHOLD) -> bool:
    """判断消息列表是否需要压缩"""
    return estimate_messages_tokens(messages) > threshold


def build_compressible_blocks(messages: list[dict], keep_turns: int = KEEP_RECENT_TURNS) -> tuple:
    """
    将消息列表拆分为「待压缩」和「保留」两部分。

    Args:
        messages: 完整的消息列表
        keep_turns: 保留最近 N 轮对话（每轮 = user + assistant 各 1 条）

    Returns:
        (older_messages, recent_messages, older_ids)
        - older_messages: 需要压缩的旧消息列表
        - recent_messages: 最近保留的完整消息
        - older_ids: 旧消息的数据库 ID 列表（用于标记已压缩）
    """
    if len(messages) <= keep_turns * 2:
        return [], messages, []

    # 按 user/assistant 成对计算轮次
    split_idx = 0
    turn_count = 0
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if msg.get("role") in ("user", "assistant", "human", "ai"):
            if msg.get("role") in ("assistant", "ai"):
                turn_count += 1
            if turn_count >= keep_turns:
                split_idx = i
                break

    older = messages[:split_idx]
    recent = messages[split_idx:]
    older_ids = [m.get("id") for m in older if m.get("id")]

    return older, recent, older_ids


def build_summary_prompt(older_messages: list[dict]) -> str:
    """
    构建摘要提示词 — 让 LLM 把旧对话压缩为一段简洁摘要。
    """
    lines = []
    for msg in older_messages:
        role = "用户" if msg.get("role") in ("user", "human") else "助手"
        content = msg.get("content", "")
        # 截断过长的消息
        if len(content) > 200:
            content = content[:200] + "..."
        lines.append(f"{role}: {content}")

    conversation_text = "\n".join(lines)

    return f"""请将以下对话历史总结为一段简短的摘要（不超过 200 字），保留关键信息（用户问题、执行的诊断操作、重要结论）。

{conversation_text}

摘要："""


async def compress_messages(
    messages: list[dict],
    summarize_fn,
    keep_turns: int = KEEP_RECENT_TURNS,
) -> tuple[Optional[str], list[int]]:
    """
    执行对话压缩。

    Args:
        messages: 完整消息列表
        summarize_fn: async 函数，接收 prompt 字符串，返回 LLM 摘要结果
        keep_turns: 保留最近 N 轮

    Returns:
        (summary_text, compressed_ids)
        - summary_text: 压缩后的摘要文本，若无需压缩则返回 None
        - compressed_ids: 被压缩消息的数据库 ID 列表
    """
    if not needs_compression(messages):
        return None, []

    older, _, older_ids = build_compressible_blocks(messages, keep_turns)

    if not older:
        return None, []

    prompt = build_summary_prompt(older)
    summary = await summarize_fn(prompt)

    return summary, older_ids
