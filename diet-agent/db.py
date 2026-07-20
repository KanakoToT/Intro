"""SQLiteによる食事・体重・会話履歴の保存。"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / "diet.db"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS meals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                eaten_at TEXT NOT NULL,
                description TEXT NOT NULL,
                calories INTEGER
            );
            CREATE TABLE IF NOT EXISTS weights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                measured_at TEXT NOT NULL UNIQUE,
                weight_kg REAL NOT NULL,
                body_fat REAL,
                source TEXT DEFAULT 'manual'
            );
            CREATE TABLE IF NOT EXISTS steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL UNIQUE,
                count INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )


def add_meal(description: str, calories: int | None) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO meals (eaten_at, description, calories) VALUES (?, ?, ?)",
            (datetime.now().isoformat(timespec="minutes"), description, calories),
        )


def recent_meals(days: int = 3) -> list[sqlite3.Row]:
    since = (datetime.now() - timedelta(days=days)).isoformat()
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM meals WHERE eaten_at >= ? ORDER BY eaten_at DESC", (since,)
        ).fetchall()


def upsert_weight(measured_at: str, weight_kg: float, body_fat: float | None, source: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO weights (measured_at, weight_kg, body_fat, source)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(measured_at) DO UPDATE
            SET weight_kg = excluded.weight_kg, body_fat = excluded.body_fat
            """,
            (measured_at, weight_kg, body_fat, source),
        )


def recent_weights(days: int = 14) -> list[sqlite3.Row]:
    since = (datetime.now() - timedelta(days=days)).isoformat()
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM weights WHERE measured_at >= ? ORDER BY measured_at DESC", (since,)
        ).fetchall()


def upsert_steps(date: str, count: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO steps (date, count) VALUES (?, ?) "
            "ON CONFLICT(date) DO UPDATE SET count = excluded.count",
            (date, count),
        )


def recent_steps(days: int = 7) -> list[sqlite3.Row]:
    since = (datetime.now() - timedelta(days=days)).date().isoformat()
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM steps WHERE date >= ? ORDER BY date DESC", (since,)
        ).fetchall()


def add_message(role: str, content: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO messages (role, content, created_at) VALUES (?, ?, ?)",
            (role, content, datetime.now().isoformat(timespec="seconds")),
        )


def recent_messages(limit: int = 20) -> list[dict]:
    """Claude APIに渡す形式 [{"role":..., "content":...}] で古い順に返す。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def build_context() -> str:
    """エージェントに渡す最新データのテキストを組み立てる。"""
    lines = []

    weights = recent_weights()
    if weights:
        lines.append("■ 体重(直近14日)")
        for w in weights[:7]:
            fat = f" / 体脂肪 {w['body_fat']}%" if w["body_fat"] else ""
            lines.append(f"  {w['measured_at'][:10]}: {w['weight_kg']}kg{fat}")

    steps = recent_steps()
    if steps:
        lines.append("■ 歩数(直近7日)")
        for s in steps:
            lines.append(f"  {s['date']}: {s['count']}歩")

    meals = recent_meals()
    if meals:
        lines.append("■ 食事記録(直近3日)")
        total_today = 0
        today = datetime.now().date().isoformat()
        for m in meals:
            cal = f" ({m['calories']}kcal)" if m["calories"] else ""
            lines.append(f"  {m['eaten_at'][5:16]}: {m['description']}{cal}")
            if m["eaten_at"].startswith(today) and m["calories"]:
                total_today += m["calories"]
        if total_today:
            lines.append(f"  → 今日の合計: 約{total_today}kcal")

    return "\n".join(lines)
