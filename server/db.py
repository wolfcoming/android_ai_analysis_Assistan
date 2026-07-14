"""SQLite 数据库管理 — 会话与消息持久化

表结构:
    sessions (id, title, created_at, updated_at)
    messages  (id, session_id, role, content, token_count, compressed, created_at)

所有 CRUD 操作均打印操作日志，方便调试数据流。
"""

import sqlite3
import uuid
from datetime import datetime
from typing import Optional

from server.config import DB_PATH


def get_connection() -> sqlite3.Connection:
    """
    获取数据库连接。

    连接配置:
        - row_factory = sqlite3.Row (支持字典式访问)
        - WAL 模式 (读写并发性能更好)
        - 外键约束开启
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """
    初始化数据库表结构。

    在应用启动时调用一次，幂等操作（CREATE TABLE IF NOT EXISTS）。
    """
    print(f"  🗄️  数据库初始化: {DB_PATH}")
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            title TEXT DEFAULT '新对话',
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            token_count INTEGER DEFAULT 0,
            compressed INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_messages_session
            ON messages(session_id, id);
    """)
    conn.commit()
    conn.close()
    print(f"  ✅ 数据库就绪")


# ============================================================
# 会话 CRUD
# ============================================================


def create_session(title: str = "新对话") -> dict:
    """创建新会话，返回会话字典"""
    session_id = str(uuid.uuid4())[:8]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    conn.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (session_id, title, now, now),
    )
    conn.commit()
    conn.close()
    print(f"  💾 [DB] 创建会话: {session_id} ({title})")
    return {"id": session_id, "title": title, "created_at": now, "updated_at": now}


def list_sessions() -> list[dict]:
    """获取所有会话列表，按最近更新时间降序"""
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, title, created_at, updated_at FROM sessions ORDER BY updated_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_session(session_id: str) -> Optional[dict]:
    """获取单个会话详情"""
    conn = get_connection()
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_session_title(session_id: str, title: str):
    """更新会话标题"""
    conn = get_connection()
    conn.execute("UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
                 (title, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), session_id))
    conn.commit()
    conn.close()
    print(f"  💾 [DB] 更新标题: {session_id} → {title}")


def touch_session(session_id: str):
    """更新会话的 updated_at 时间戳（表示有活动）"""
    conn = get_connection()
    conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?",
                 (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), session_id))
    conn.commit()
    conn.close()


def delete_session(session_id: str):
    """删除会话及其所有消息（CASCADE）"""
    conn = get_connection()
    conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()
    print(f"  💾 [DB] 删除会话: {session_id}")


# ============================================================
# 消息 CRUD
# ============================================================


def add_message(session_id: str, role: str, content: str, token_count: int = 0) -> dict:
    """
    添加一条消息到指定会话。

    Args:
        session_id: 会话 ID
        role: 消息角色 (user / assistant / summary / tool)
        content: 消息内容
        token_count: token 数量估算（可选）
    """
    conn = get_connection()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor = conn.execute(
        "INSERT INTO messages (session_id, role, content, token_count, created_at) VALUES (?, ?, ?, ?, ?)",
        (session_id, role, content, token_count, now),
    )
    msg_id = cursor.lastrowid
    conn.commit()
    conn.close()
    print(f"  💾 [DB] 添加消息: id={msg_id} role={role} len={len(content)} session={session_id[:8]}")
    return {"id": msg_id, "session_id": session_id, "role": role, "content": content, "created_at": now}


def get_messages(session_id: str, include_compressed: bool = False) -> list[dict]:
    """
    获取会话的所有消息，按时间升序。

    Args:
        session_id: 会话 ID
        include_compressed: 是否包含已压缩的旧消息（默认不包含）
    """
    conn = get_connection()
    if include_compressed:
        rows = conn.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM messages WHERE session_id = ? AND compressed = 0 ORDER BY id ASC",
            (session_id,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_compressed(msg_ids: list[int]):
    """标记消息为已压缩（压缩后的消息不再参与后续压缩和历史加载）"""
    if not msg_ids:
        return
    conn = get_connection()
    placeholders = ",".join("?" * len(msg_ids))
    conn.execute(
        f"UPDATE messages SET compressed = 1 WHERE id IN ({placeholders})",
        msg_ids,
    )
    conn.commit()
    conn.close()
    print(f"  💾 [DB] 标记压缩: {len(msg_ids)} 条消息")


def get_message_count(session_id: str) -> int:
    """获取会话的未压缩消息数量"""
    conn = get_connection()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM messages WHERE session_id = ? AND compressed = 0",
        (session_id,),
    ).fetchone()
    conn.close()
    return row["cnt"] if row else 0


def get_latest_summary(session_id: str) -> Optional[dict]:
    """获取该会话最新的压缩摘要"""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM messages WHERE session_id = ? AND role = 'summary' ORDER BY id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None
