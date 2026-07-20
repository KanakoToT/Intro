"""AIエージェントチーム(トレーナー・栄養士・励まし役)の定義とClaude API呼び出し。"""

import os

import anthropic

MODEL = "claude-opus-4-8"

# チーム全体をひとつのシステムプロンプトで定義し、
# 1回のAPI呼び出しで適切なメンバーが応答する構成にしている。
# (メンバーごとに別々のAPI呼び出しをするより速く、文脈も共有できる)
TEAM_SYSTEM_PROMPT = """\
あなたは、ユーザーのダイエットを支援する3人の専門家チームです。
ユーザーの目標は健康的に痩せること。特に「食べすぎてしまう」ことに悩んでいます。

チームメンバー:

🏋️ ケンジ(トレーナー)
- 運動・活動量の専門家。歩数や運動記録を見てアドバイスする
- 現実的で無理のない運動プランを提案する。根性論は使わない
- 口調: 頼れる兄貴分。simple・直球

🥗 ミドリ(管理栄養士)
- 食事内容を見てカロリーと栄養バランスを評価する
- 食べたものを報告されたら、おおよそのカロリーを推定して記録用に伝える
- 「食べてはダメ」ではなく「こうすればもっと良い」という提案型
- 口調: 落ち着いていて丁寧。科学的根拠を大切にする

🌸 サクラ(励まし役)
- ユーザーのメンタルサポート担当。自己肯定感を守る
- 食べすぎた日も責めずに「切り替え」を促す。小さな成功を必ず見つけて褒める
- 口調: 明るくあたたかい。絵文字を使う

応答のルール:
1. ユーザーのメッセージ内容に応じて、最も適切なメンバー(1〜3人)が発言する。
   全員が毎回話す必要はない。食事報告→ミドリ中心、運動の話→ケンジ中心、
   落ち込んでいる時→サクラ中心。
2. 各発言の冒頭に「🏋️ ケンジ:」のように名前を付ける。
3. 食べたものの報告があったら、ミドリが推定カロリーを必ず示す。
   その際、応答の最後に必ず次の形式の行を1行だけ追加する(記録システムが読み取る):
   [MEAL_LOG] 食品名 | 推定カロリー(数字のみ)
   例: [MEAL_LOG] カツ丼と味噌汁 | 950
   食事報告でない場合はこの行を出力しない。
4. 提供されるコンテキスト(最近の体重・歩数・食事記録)があれば積極的に参照する。
5. 応答は読みやすく簡潔に。長くても300字程度×発言者数まで。
6. 医療的な診断はしない。健康上の懸念があれば医師への相談を勧める。
"""

_client = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()  # ANTHROPIC_API_KEY を環境変数から読む
    return _client


def team_chat(history: list[dict], user_message: str, context: str) -> str:
    """会話履歴とコンテキストを添えてエージェントチームの応答を得る。

    history: [{"role": "user"|"assistant", "content": str}, ...]
    context: 体重・歩数・食事記録などの最新データ(テキスト整形済み)
    """
    messages = list(history)
    content = user_message
    if context:
        content = f"<最新データ>\n{context}\n</最新データ>\n\n{user_message}"
    messages.append({"role": "user", "content": content})

    response = get_client().messages.create(
        model=MODEL,
        max_tokens=4096,
        thinking={"type": "adaptive"},
        system=[
            {
                "type": "text",
                "text": TEAM_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=messages,
    )

    if response.stop_reason == "refusal":
        return "🌸 サクラ: ごめんなさい、その内容にはお答えできません。別の聞き方で試してみてくださいね。"

    return "".join(block.text for block in response.content if block.type == "text")


def parse_meal_log(reply: str) -> tuple[str, int] | None:
    """応答から [MEAL_LOG] 行を抽出する。見つからなければ None。"""
    for line in reply.splitlines():
        line = line.strip()
        if line.startswith("[MEAL_LOG]"):
            body = line.removeprefix("[MEAL_LOG]").strip()
            if "|" in body:
                name, _, cal = body.partition("|")
                digits = "".join(c for c in cal if c.isdigit())
                if digits:
                    return name.strip(), int(digits)
    return None
