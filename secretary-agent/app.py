"""仕事の秘書AIエージェント — FastAPIアプリ本体。

起動: uvicorn app:app --reload
"""

from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv

load_dotenv()  # .env を読み込む(import より先に実行)

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse, Response  # noqa: E402
from pydantic import BaseModel  # noqa: E402

import agents  # noqa: E402
import db  # noqa: E402

app = FastAPI(title="Work Secretary Agent Team")
db.init_db()

STATIC_DIR = Path(__file__).parent / "static"


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


# ---------- チャット ----------

class ChatRequest(BaseModel):
    message: str


@app.post("/api/chat")
def chat(req: ChatRequest):
    message = req.message.strip()
    if not message:
        raise HTTPException(400, "メッセージを入力してください")

    history = db.recent_messages(limit=20)
    context = db.build_context()

    reply, sources = agents.team_chat(history, message, context)

    # エージェントが指示したTodoの登録・完了を反映する
    added = [db.add_todo(**todo) for todo in agents.parse_todo_adds(reply)]
    completed = [tid for tid in agents.parse_todo_dones(reply) if db.set_todo_status(tid, "done")]

    # ドラフトされた文書を保存する
    saved_drafts = [
        {"id": db.save_draft(title, content), "title": title}
        for title, content in agents.parse_drafts(reply)
        if content
    ]

    visible = agents.strip_markers(reply)

    # 検索を使った応答は調査メモとして残す
    if sources:
        db.add_note(topic=message[:120], summary=visible[:1000], sources=sources)

    db.add_message("user", message)
    db.add_message("assistant", visible)

    return {
        "reply": visible,
        "sources": sources,
        "todos_added": len(added),
        "todos_completed": completed,
        "drafts": saved_drafts,
    }


@app.get("/api/messages")
def list_messages(limit: int = 40):
    return db.recent_messages(limit=limit)


# ---------- Todo ----------

class TodoRequest(BaseModel):
    title: str
    due: str | None = None
    priority: str = "中"


@app.get("/api/todos")
def list_todos(status: str = "open"):
    if status not in ("open", "done", "all"):
        raise HTTPException(400, "status は open / done / all のいずれかです")
    return [dict(r) for r in db.list_todos(status)]


@app.post("/api/todos")
def create_todo(req: TodoRequest):
    title = req.title.strip()
    if not title:
        raise HTTPException(400, "タイトルを入力してください")
    priority = req.priority if req.priority in ("高", "中", "低") else "中"
    return {"id": db.add_todo(title, req.due or None, priority)}


@app.post("/api/todos/{todo_id}/done")
def complete_todo(todo_id: int):
    if not db.set_todo_status(todo_id, "done"):
        raise HTTPException(404, "そのTodoは見つかりません")
    return {"ok": True}


@app.post("/api/todos/{todo_id}/reopen")
def reopen_todo(todo_id: int):
    if not db.set_todo_status(todo_id, "open"):
        raise HTTPException(404, "そのTodoは見つかりません")
    return {"ok": True}


@app.delete("/api/todos/{todo_id}")
def remove_todo(todo_id: int):
    if not db.delete_todo(todo_id):
        raise HTTPException(404, "そのTodoは見つかりません")
    return {"ok": True}


# ---------- 企画書ドラフト ----------

@app.get("/api/drafts")
def list_drafts():
    return [dict(r) for r in db.list_drafts()]


@app.get("/api/drafts/{draft_id}")
def read_draft(draft_id: int):
    draft = db.get_draft(draft_id)
    if not draft:
        raise HTTPException(404, "その文書は見つかりません")
    return dict(draft)


@app.get("/api/drafts/{draft_id}/download")
def download_draft(draft_id: int):
    draft = db.get_draft(draft_id)
    if not draft:
        raise HTTPException(404, "その文書は見つかりません")
    filename = f"{draft['title']}.md".replace("/", "_").replace("\\", "_")
    return Response(
        content=draft["content"],
        media_type="text/markdown; charset=utf-8",
        headers={
            # 日本語ファイル名のため RFC 5987 形式で指定する
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"
        },
    )


@app.delete("/api/drafts/{draft_id}")
def remove_draft(draft_id: int):
    if not db.delete_draft(draft_id):
        raise HTTPException(404, "その文書は見つかりません")
    return {"ok": True}


# ---------- 調査メモ ----------

@app.get("/api/notes")
def list_notes(limit: int = 20):
    return db.recent_notes(limit=limit)
