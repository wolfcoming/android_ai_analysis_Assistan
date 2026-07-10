"""SQLite 数据库管理 — 会话与消息持久化"""

import sqlite3
import os
import uuid
from datetime import datetime
from typing import Optional

# 数据库文件路径（项目根目录）
DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assistant.db"
)


def get_connection() -> sqlite3.Connection:
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """初始化数据库表结构"""
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


# ---- 会话操作 ----


def create_session(title: str = "新对话") -> dict:
    session_id = str(uuid.uuid4())[:8]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    conn.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (session_id, title, now, now),
    )
    conn.commit()
    conn.close()
    return {"id": session_id, "title": title, "created_at": now, "updated_at": now}


def list_sessions() -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, title, created_at, updated_at FROM sessions ORDER BY updated_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_session(session_id: str) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_session_title(session_id: str, title: str):
    conn = get_connection()
    conn.execute("UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
                 (title, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), session_id))
    conn.commit()
    conn.close()


def touch_session(session_id: str):
    """更新会话的 updated_at 时间戳"""
    conn = get_connection()
    conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?",
                 (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), session_id))
    conn.commit()
    conn.close()


def delete_session(session_id: str):
    conn = get_connection()
    conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()


# ---- 消息操作 ----


def add_message(session_id: str, role: str, content: str, token_count: int = 0) -> dict:
    conn = get_connection()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor = conn.execute(
        "INSERT INTO messages (session_id, role, content, token_count, created_at) VALUES (?, ?, ?, ?, ?)",
        (session_id, role, content, token_count, now),
    )
    msg_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {"id": msg_id, "session_id": session_id, "role": role, "content": content, "created_at": now}


def get_messages(session_id: str, include_compressed: bool = False) -> list[dict]:
    """获取会话的所有消息，按时间排序"""
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
    """标记消息为已压缩"""
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


def get_message_count(session_id: str) -> int:
    conn = get_connection()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM messages WHERE session_id = ? AND compressed = 0",
        (session_id,),
    ).fetchone()
    conn.close()
    return row["cnt"] if row else 0


def get_latest_summary(session_id: str) -> Optional[dict]:
    """获取最新的压缩摘要"""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM messages WHERE session_id = ? AND role = 'summary' ORDER BY id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None
