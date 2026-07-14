"""趋势数据缓存 — 环形缓冲区

用于存储实时性能指标的时序数据，前端通过 /api/device/trends 获取。
"""

import time
from collections import deque

from server.config import TREND_BUFFER_SIZE


class RingBuffer:
    """
    固定大小的环形缓冲区，用于存储时序数据。

    特性:
        - 自动淘汰最旧数据（FIFO）
        - 每条数据自动附带时间戳
        - 支持按时间范围查询

    默认容量: 150 个数据点（5 分钟 / 2 秒 = 150 个点）
    """

    def __init__(self, max_size: int = TREND_BUFFER_SIZE):
        self._buffer = deque(maxlen=max_size)
        print(f"  📊 [趋势缓存] 初始化环形缓冲区, 容量={max_size}")

    def add(self, data: dict):
        """添加一条数据，自动附带时间戳"""
        data["_ts"] = time.time()
        self._buffer.append(data)

    def get_all(self) -> list:
        """获取所有数据"""
        return list(self._buffer)

    def get_recent(self, seconds: float = 300) -> list:
        """
        获取最近 N 秒的数据。

        Args:
            seconds: 时间窗口（秒），默认 5 分钟

        Returns:
            时间窗口内的数据列表
        """
        cutoff = time.time() - seconds
        return [d for d in self._buffer if d.get("_ts", 0) >= cutoff]

    def clear(self):
        """清空缓冲区"""
        self._buffer.clear()

    def __len__(self):
        return len(self._buffer)


# ============================================================
# 全局单例
# ============================================================

_trend_cache: RingBuffer = None


def get_trend_cache() -> RingBuffer:
    """获取全局趋势缓存实例（单例）"""
    global _trend_cache
    if _trend_cache is None:
        _trend_cache = RingBuffer(max_size=TREND_BUFFER_SIZE)
    return _trend_cache
