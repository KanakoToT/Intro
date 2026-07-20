# 🏋️🥗🌸 ダイエット応援AIエージェントチーム

トレーナー(ケンジ)・管理栄養士(ミドリ)・励まし役(サクラ)の3人のAIエージェントが、
チャットであなたのダイエットをサポートするアプリです。

## できること

- **チャットで相談** — 内容に応じて適切なメンバーが応答します
- **食事の自動記録** — 「カツ丼食べました」と報告すると、ミドリがカロリーを推定して自動でDBに記録
- **Google Health連携** — 体重(Renpho体重計→Google Healthアプリ経由)と歩数を取得し、チームがデータを見てアドバイス
- **食べすぎ対策** — 責めずに切り替えを促すコーチング方針

## 構成

| ファイル | 役割 |
|---|---|
| `app.py` | FastAPIサーバー本体(チャット・記録・同期のAPI) |
| `agents.py` | 3人のエージェントチームの定義とClaude API呼び出し |
| `google_health.py` | Google OAuth 2.0 と Google Health API クライアント |
| `db.py` | SQLite(食事・体重・歩数・会話履歴) |
| `static/index.html` | チャット画面 |

## セットアップ

### 1. 依存パッケージのインストール

```bash
cd diet-agent
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. APIキーの設定

```bash
cp .env.example .env
```

`.env` を開いて設定します:

- **ANTHROPIC_API_KEY** — [platform.claude.com](https://platform.claude.com) で取得
- **GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET** — [Google Cloud Console](https://console.cloud.google.com) で:
  1. プロジェクトを作成
  2. 「APIとサービス → ライブラリ」で **Google Health API** を有効化
  3. 「OAuth同意画面」を設定(テストユーザーに自分のGmailを追加)
  4. 「認証情報 → OAuthクライアントID → ウェブアプリケーション」を作成
  5. リダイレクトURIに `http://localhost:8000/auth/callback` を登録

### 3. 起動

```bash
uvicorn app:app --reload
```

ブラウザで http://localhost:8000 を開きます。

### 4. Google Health接続(任意)

画面右上の「Google Health接続」→ Googleでログイン・同意 → 「データ同期」ボタンで
体重・歩数が取り込まれます。接続しなくてもチャットと食事記録は使えます。

## ⚠️ 知っておくべきこと

- **Fitbit → Google Health への移行**: 2026年5月19日にFitbitアプリはGoogle Healthアプリに
  リブランドされ、開発者向けAPIも「Google Health API」に刷新されました。
  旧Fitbit Web APIは **2026年9月に廃止** されるため、このアプリは新APIを対象にしています。
- **API仕様の確認が必要**: Google Health APIは新しいAPIのため、`google_health.py` 内の
  ベースURL・スコープ名・レスポンス形式は
  [developers.google.com/health](https://developers.google.com/health) の
  Endpoints / Scopes ページで正式な値を確認し、`.env` で調整してください
  (開発環境からドキュメントに接続できなかったため仮の値になっています)。
- **食事データについて**: 新しいGoogle Health APIには栄養(食事)データタイプが
  まだ実装されていないため、食事記録はこのアプリ内のSQLiteで管理します。
- **Renpho体重計**: Renphoには公開APIがないため、Renphoアプリ → Google Healthアプリに
  同期されたデータを Google Health API 経由で取得する流れになります。
  Renphoアプリ側でGoogle Healthへの連携を有効にしておいてください。
- **医療上の注意**: このアプリのアドバイスは一般的な情報です。健康上の懸念がある場合は
  医師・管理栄養士に相談してください。
