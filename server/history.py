"""趋势数据缓存 - 环形缓冲区"""
from collections import deque
import time


class RingBuffer:
    """固定大小的环形缓冲区，用于存储时序数据"""

    def __init__(self, max_size: int = 150):
        """
        Args:
            max_size: 最大数据点数（5分钟 / 2秒 = 150个点）
        """
        self._buffer = deque(maxlen=max_size)

    def add(self, data: dict):
        """添加一条数据，自动附带时间戳"""
        data["_ts"] = time.time()
        self._buffer.append(data)

    def get_all(self) -> list:
        """获取所有数据"""
        return list(self._buffer)

    def get_recent(self, seconds: float = 300) -> list:
        """获取最近 N 秒的数据"""
        cutoff = time.time() - seconds
        return [d for d in self._buffer if d.get("_ts", 0) >= cutoff]

    def clear(self):
        """清空缓冲区"""
        self._buffer.clear()

    def __len__(self):
        return len(self._buffer)


# 全局趋势缓存实例
_trend_cache: RingBuffer = None


def get_trend_cache() -> RingBuffer:
    global _trend_cache
    if _trend_cache is None:
        _trend_cache = RingBuffer(max_size=150)
    return _trend_cache
