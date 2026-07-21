"""Google Health API (旧Fitbit Web API) との連携。

Google OAuth 2.0 で認可を取得し、体重・歩数などのデータを取得する。

注意:
- Google Health APIは2026年に公開された新しいAPIで、旧Fitbit Web APIの後継。
  旧APIは2026年9月に廃止予定のため、このモジュールは新APIを対象にしている。
- APIのベースURLとスコープ名は developers.google.com/health の
  「Endpoints」「Scopes」ページで最新のものを確認し、.env で上書きすること。
- 栄養(食事)データタイプは執筆時点で新APIに未実装のため、
  食事記録はこのアプリ内(SQLite)で管理する。
"""

import json
import os
import secrets
import time
from pathlib import Path

import httpx

TOKEN_PATH = Path(__file__).parent / "token.json"

# Google OAuth 2.0 の標準エンドポイント(安定・共通)
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"

# ↓ 要確認: developers.google.com/health/endpoints に記載の正式なベースURLを
#   .env の GOOGLE_HEALTH_API_BASE に設定する(このデフォルト値は仮置き)。
API_BASE = os.environ.get(
    "GOOGLE_HEALTH_API_BASE", "https://googlehealth.googleapis.com/v4"
)

# ↓ 要確認: developers.google.com/health/scopes に記載の正式なスコープ名。
#   形式は https://www.googleapis.com/auth/googlehealth.{scope}
SCOPES = os.environ.get(
    "GOOGLE_HEALTH_SCOPES",
    " ".join(
        [
            "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly",
            "https://www.googleapis.com/auth/googlehealth.body_measurements.readonly",
        ]
    ),
)

CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/callback")

_pending_state: str | None = None


def is_configured() -> bool:
    return bool(CLIENT_ID and CLIENT_SECRET)


def is_connected() -> bool:
    return TOKEN_PATH.exists()


def build_auth_url() -> str:
    """Google の同意画面へのURLを組み立てる。"""
    global _pending_state
    _pending_state = secrets.token_urlsafe(16)
    params = httpx.QueryParams(
        {
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": SCOPES,
            "access_type": "offline",  # refresh_token を受け取る
            "prompt": "consent",
            "state": _pending_state,
        }
    )
    return f"{AUTH_URL}?{params}"


def exchange_code(code: str, state: str) -> None:
    """認可コードをトークンに交換して保存する。"""
    if state != _pending_state:
        raise ValueError("stateが一致しません(CSRFの可能性)")
    resp = httpx.post(
        TOKEN_URL,
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
        },
        timeout=30,
    )
    resp.raise_for_status()
    tokens = resp.json()
    tokens["expires_at"] = time.time() + tokens.get("expires_in", 3600)
    TOKEN_PATH.write_text(json.dumps(tokens, indent=2))


def _get_access_token() -> str:
    tokens = json.loads(TOKEN_PATH.read_text())
    if time.time() > tokens.get("expires_at", 0) - 60:
        resp = httpx.post(
            TOKEN_URL,
            data={
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "refresh_token": tokens["refresh_token"],
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        resp.raise_for_status()
        new = resp.json()
        tokens["access_token"] = new["access_token"]
        tokens["expires_at"] = time.time() + new.get("expires_in", 3600)
        TOKEN_PATH.write_text(json.dumps(tokens, indent=2))
    return tokens["access_token"]


def fetch(path: str, params: dict | None = None) -> dict:
    """Google Health API への認証付きGETリクエスト。

    path 例: "users/me/dataTypes/weight/dataPoints"
    エンドポイントの正確なパスは公式ドキュメントの Endpoints ページを参照。
    """
    resp = httpx.get(
        f"{API_BASE}/{path.lstrip('/')}",
        params=params,
        headers={"Authorization": f"Bearer {_get_access_token()}"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_weight(start_date: str, end_date: str) -> dict:
    """体重データを取得する(日次)。"""
    return fetch(
        "users/me/dataTypes/weight/dataPoints:dailyRollUp",
        params={"startDate": start_date, "endDate": end_date},
    )


def fetch_steps(start_date: str, end_date: str) -> dict:
    """歩数データを取得する(日次)。"""
    return fetch(
        "users/me/dataTypes/steps/dataPoints:dailyRollUp",
        params={"startDate": start_date, "endDate": end_date},
    )
