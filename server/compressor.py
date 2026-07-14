"""上下文压缩 — Token 计数 + 对话摘要压缩

核心流程:
    1. 估算消息总 token 数                  → estimate_messages_tokens()
    2. 判断是否需要压缩                      → needs_compression()
    3. 拆分消息为「压缩块」和「保留块」       → build_compressible_blocks()
    4. 构建摘要提示词                       → build_summary_prompt()
    5. 调用 LLM 生成摘要                    → compress_messages()
    6. 标记旧消息为已压缩                    → mark_compressed() (by caller)
"""

import re
from typing import Optional

from server.config import COMPRESS_THRESHOLD, KEEP_RECENT_TURNS


def estimate_tokens(text: str) -> int:
    """
    估算文本的 token 数量（启发式算法）。

    不依赖 tiktoken 等外部库，使用简单规则估算：
    - 中文/日文/韩文: 1 字符 ≈ 1.5 token
    - 英文单词:        1 词 ≈ 1.0 token
    - 其余字符:        1 字符 ≈ 0.25 token

    精确度足够用于触发压缩判断，不需要 tiktoken 依赖。
    """
    if not text:
        return 0

    # 统计 CJK 字符（Unicode 范围）
    cjk_chars = len(re.findall(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]', text))
    # 统计英文单词（连续字母）
    english_words = len(re.findall(r'[a-zA-Z]+', text))
    # 其余字符（数字、符号、空格等）
    remaining = max(0, len(text) - cjk_chars - english_words * 5)

    tokens = cjk_chars * 1.5 + english_words * 1.0 + remaining * 0.25
    return int(tokens)


def estimate_messages_tokens(messages: list[dict]) -> int:
    """估算消息列表的总 token 数（含 role 开销约 4 token/条）"""
    total = 0
    for msg in messages:
        total += estimate_tokens(msg.get("content", "")) + 4
    return total


def needs_compression(messages: list[dict], threshold: int = COMPRESS_THRESHOLD) -> bool:
    """判断消息列表是否需要压缩"""
    return estimate_messages_tokens(messages) > threshold


def build_compressible_blocks(messages: list[dict], keep_turns: int = KEEP_RECENT_TURNS) -> tuple:
    """
    将消息列表拆分为「待压缩」和「保留」两部分。

    保留策略: 从后往前数 keep_turns 轮完整对话（user + assistant 各 1 条 = 1 轮），
             更早的消息全部纳入压缩范围。

    Args:
        messages: 完整的消息列表（按时间升序）
        keep_turns: 保留最近 N 轮对话

    Returns:
        (older_messages, recent_messages, older_ids)
        - older_messages: 需要压缩的旧消息列表
        - recent_messages: 保留的最近消息（不参与压缩）
        - older_ids: 旧消息的数据库 ID 列表（用于标记 compressed=1）
    """
    if len(messages) <= keep_turns * 2:
        # 消息太少，不需要压缩
        return [], messages, []

    # 从消息末尾反向扫描，计算轮次
    split_idx = 0
    turn_count = 0
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        role = msg.get("role", "")
        if role in ("user", "assistant", "human", "ai"):
            if role in ("assistant", "ai"):
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

    每条消息内容过长时截断到 200 字，避免摘要 prompt 过长。
    """
    lines = []
    for msg in older_messages:
        role = "用户" if msg.get("role") in ("user", "human") else "助手"
        content = msg.get("content", "")
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

    完整流程:
        1. 判断是否需要压缩 (token > threshold)
        2. 拆分消息为 old + recent
        3. 用 old 构建摘要 prompt
        4. 调用 summarize_fn (LLM) 生成摘要
        5. 返回摘要文本和需要标记为已压缩的消息 ID 列表

    Args:
        messages:    完整消息列表
        summarize_fn: async 摘要函数，接收 prompt 字符串，返回 LLM 摘要
        keep_turns:  保留最近 N 轮

    Returns:
        (summary_text, compressed_ids)
        - summary_text: 压缩后的摘要文本，若无需压缩返回 None
        - compressed_ids: 被压缩消息的 DB ID 列表
    """
    print(f"  🗜️  [压缩检查] 消息数={len(messages)} token≈{estimate_messages_tokens(messages)} 阈值={COMPRESS_THRESHOLD}")

    if not needs_compression(messages):
        print(f"  📏 [压缩] 未触发压缩 (token 未超阈值)")
        return None, []

    older, _, older_ids = build_compressible_blocks(messages, keep_turns)

    if not older:
        print(f"  📏 [压缩] 待压缩消息为空")
        return None, []

    print(f"  🗜️  [压缩] 开始生成摘要: {len(older)}条→保留{keep_turns}轮")
    prompt = build_summary_prompt(older)
    summary = await summarize_fn(prompt)

    if summary:
        print(f"  ✅ [压缩] 摘要生成完成: {len(summary)}字")
    else:
        print(f"  ⚠️  [压缩] 摘要生成返回空")

    return summary, older_ids
