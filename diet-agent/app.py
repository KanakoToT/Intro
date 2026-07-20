"""ダイエット管理AIエージェント — FastAPIアプリ本体。

起動: uvicorn app:app --reload
"""

from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # .env を読み込む(import より先に実行)

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse, RedirectResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

import agents  # noqa: E402
import db  # noqa: E402
import google_health as gh  # noqa: E402

app = FastAPI(title="Diet Agent Team")
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
    history = db.recent_messages(limit=20)
    context = db.build_context()
    reply = agents.team_chat(history, req.message, context)

    db.add_message("user", req.message)
    db.add_message("assistant", reply)

    # 栄養士が食事を認識したら自動で記録する
    meal = agents.parse_meal_log(reply)
    if meal:
        db.add_meal(meal[0], meal[1])

    # [MEAL_LOG] 行は内部用なので画面には出さない
    visible = "\n".join(
        line for line in reply.splitlines() if not line.strip().startswith("[MEAL_LOG]")
    ).strip()
    return {"reply": visible, "meal_logged": bool(meal)}


# ---------- 食事記録 ----------

class MealRequest(BaseModel):
    description: str
    calories: int | None = None


@app.get("/api/meals")
def list_meals(days: int = 7):
    return [dict(r) for r in db.recent_meals(days)]


@app.post("/api/meals")
def create_meal(req: MealRequest):
    db.add_meal(req.description, req.calories)
    return {"ok": True}


# ---------- 体重・歩数 ----------

@app.get("/api/weights")
def list_weights(days: int = 30):
    return [dict(r) for r in db.recent_weights(days)]


class WeightRequest(BaseModel):
    weight_kg: float
    body_fat: float | None = None


@app.post("/api/weights")
def create_weight(req: WeightRequest):
    db.upsert_weight(date.today().isoformat(), req.weight_kg, req.body_fat, "manual")
    return {"ok": True}


# ---------- Google Health 連携 ----------

@app.get("/api/health-status")
def health_status():
    return {"configured": gh.is_configured(), "connected": gh.is_connected()}


@app.get("/auth/login")
def auth_login():
    if not gh.is_configured():
        raise HTTPException(400, "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET が未設定です")
    return RedirectResponse(gh.build_auth_url())


@app.get("/auth/callback")
def auth_callback(code: str, state: str):
    gh.exchange_code(code, state)
    return RedirectResponse("/?connected=1")


@app.post("/api/sync")
def sync_from_google_health():
    """Google Health APIから体重・歩数を取得してDBに保存する。"""
    if not gh.is_connected():
        raise HTTPException(400, "Google Healthが未接続です。先に /auth/login で接続してください")

    end = date.today()
    start = end - timedelta(days=14)
    synced = {"weights": 0, "steps": 0, "errors": []}

    try:
        data = gh.fetch_weight(start.isoformat(), end.isoformat())
        for point in data.get("dataPoints", []):
            day = point.get("date") or point.get("startTime", "")[:10]
            value = point.get("value")
            if day and value is not None:
                db.upsert_weight(day, float(value), point.get("bodyFat"), "google_health")
                synced["weights"] += 1
    except Exception as e:  # APIの正式仕様確認前なのでエラーは画面に返して調整する
        synced["errors"].append(f"体重の取得に失敗: {e}")

    try:
        data = gh.fetch_steps(start.isoformat(), end.isoformat())
        for point in data.get("dataPoints", []):
            day = point.get("date") or point.get("startTime", "")[:10]
            value = point.get("value")
            if day and value is not None:
                db.upsert_steps(day, int(value))
                synced["steps"] += 1
    except Exception as e:
        synced["errors"].append(f"歩数の取得に失敗: {e}")

    return synced
