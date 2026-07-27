"""SQLiteによるTodo・企画書ドラフト・調査メモ・会話履歴の保存。"""

import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

DB_PATH = Path(__file__).parent / "secretary.db"
TZ = ZoneInfo(os.getenv("TIMEZONE", "Asia/Tokyo"))

PRIORITY_ORDER = {"高": 0, "中": 1, "低": 2}


def now() -> datetime:
    return datetime.now(TZ)


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS todos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                due TEXT,
                priority TEXT NOT NULL DEFAULT '中',
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL,
                done_at TEXT
            );
            CREATE TABLE IF NOT EXISTS drafts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                summary TEXT NOT NULL,
                sources TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )


# ---------- Todo ----------

def add_todo(title: str, due: str | None = None, priority: str = "中") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO todos (title, due, priority, created_at) VALUES (?, ?, ?, ?)",
            (title, due, priority, now().isoformat(timespec="seconds")),
        )
        return cur.lastrowid


def list_todos(status: str = "open") -> list[sqlite3.Row]:
    query = "SELECT * FROM todos"
    params: tuple = ()
    if status != "all":
        query += " WHERE status = ?"
        params = (status,)
    query += " ORDER BY (due IS NULL), due, CASE priority WHEN '高' THEN 0 WHEN '中' THEN 1 ELSE 2 END, id"
    with get_conn() as conn:
        return conn.execute(query, params).fetchall()


def set_todo_status(todo_id: int, status: str) -> bool:
    done_at = now().isoformat(timespec="seconds") if status == "done" else None
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE todos SET status = ?, done_at = ? WHERE id = ?", (status, done_at, todo_id)
        )
        return cur.rowcount > 0


def delete_todo(todo_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
        return cur.rowcount > 0


# ---------- 企画書ドラフト ----------

def save_draft(title: str, content: str) -> int:
    """同じタイトルの文書があれば上書きし、なければ新規作成する。"""
    stamp = now().isoformat(timespec="seconds")
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM drafts WHERE title = ?", (title,)).fetchone()
        if row:
            conn.execute(
                "UPDATE drafts SET content = ?, updated_at = ? WHERE id = ?",
                (content, stamp, row["id"]),
            )
            return row["id"]
        cur = conn.execute(
            "INSERT INTO drafts (title, content, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (title, content, stamp, stamp),
        )
        return cur.lastrowid


def list_drafts() -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT id, title, created_at, updated_at FROM drafts ORDER BY updated_at DESC"
        ).fetchall()


def get_draft(draft_id: int) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()


def delete_draft(draft_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM drafts WHERE id = ?", (draft_id,))
        return cur.rowcount > 0


# ---------- 調査メモ ----------

def add_note(topic: str, summary: str, sources: list[dict]) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO notes (topic, summary, sources, created_at) VALUES (?, ?, ?, ?)",
            (
                topic,
                summary,
                json.dumps(sources, ensure_ascii=False),
                now().isoformat(timespec="seconds"),
            ),
        )
        return cur.lastrowid


def recent_notes(limit: int = 20) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM notes ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [
        {
            "id": r["id"],
            "topic": r["topic"],
            "summary": r["summary"],
            "sources": json.loads(r["sources"]),
            "created_at": r["created_at"],
        }
        for r in rows
    ]


# ---------- 会話履歴 ----------

def add_message(role: str, content: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO messages (role, content, created_at) VALUES (?, ?, ?)",
            (role, content, now().isoformat(timespec="seconds")),
        )


def recent_messages(limit: int = 20) -> list[dict]:
    """Claude APIに渡す形式 [{"role":..., "content":...}] で古い順に返す。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


# ---------- エージェントに渡すコンテキスト ----------

def build_context() -> str:
    """エージェントに渡す「現在の状況」のテキストを組み立てる。"""
    today = now().date()
    lines = [f"■ 今日の日付: {today.isoformat()} ({'月火水木金土日'[today.weekday()]}曜日)"]

    todos = list_todos("open")
    if todos:
        lines.append(f"■ 未完了のTodo({len(todos)}件)")
        for t in todos[:20]:
            due = "期限なし"
            if t["due"]:
                try:
                    days = (datetime.fromisoformat(t["due"]).date() - today).days
                    if days < 0:
                        due = f"{t['due']}(期限切れ {abs(days)}日)"
                    elif days == 0:
                        due = f"{t['due']}(今日)"
                    else:
                        due = f"{t['due']}(あと{days}日)"
                except ValueError:
                    due = t["due"]
            lines.append(f"  #{t['id']} [{t['priority']}] {t['title']} — {due}")
    else:
        lines.append("■ 未完了のTodo: なし")

    drafts = list_drafts()
    if drafts:
        lines.append("■ 保存済みの文書")
        for d in drafts[:10]:
            lines.append(f"  「{d['title']}」(最終更新 {d['updated_at'][:10]})")

    notes = recent_notes(5)
    if notes:
        lines.append("■ 直近の調査メモ")
        for n in notes:
            lines.append(f"  {n['created_at'][:10]}: {n['topic']}")

    return "\n".join(lines)
