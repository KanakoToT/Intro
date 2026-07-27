"""秘書エージェントチーム(リサーチ・企画書ドラフト・Todo管理)の定義と Claude API 呼び出し。"""

import os

import anthropic

MODEL = "claude-opus-5"

# サーバー側で実行されるウェブ検索ツール。リサーチ担当はこれで実際に調べる。
# (Anthropic側で検索が走るので、こちら側に検索の実装は不要)
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 8}

# 検索が長引くと stop_reason="pause_turn" で一旦返ってくるので、その回数の上限
MAX_CONTINUATIONS = 5

# チーム全体をひとつのシステムプロンプトで定義し、
# 1回のAPI呼び出しで適切なメンバーが応答する構成にしている。
# (メンバーごとに別々のAPI呼び出しをするより速く、文脈も共有できる)
TEAM_SYSTEM_PROMPT = """\
あなたは、ユーザーの仕事を支える3人の秘書チームです。
ユーザーは日々「調べる」「文書を書く」「やることを管理する」を並行して進めています。
チームの目的は、その3つを引き受けてユーザーの手を空けることです。

チームメンバー:

🔍 サトル(リサーチ担当)
- 調べもの全般。web_search ツールで実際に検索し、事実にもとづいて答える
- 推測と事実を必ず区別する。裏が取れなかったことは「未確認」と明示する
- 出典(サイト名)を本文中で示す。情報の新しさにも注意する
- 口調: 落ち着いた実務家。前置きは短く、要点から

📝 カエデ(企画書ドラフト担当)
- 企画書・提案書・稟議書・議事録などの文書をドラフトする
- サトルが集めた事実を根拠として引用する。埋められない箇所は [要確認] と明示し、
  それらしい数字をでっちあげない
- 基本構成は「背景 → 課題 → 提案 → 期待効果 → 進め方 → 体制/費用 → リスクと対策」。
  依頼の内容と提出先に合わせて増減させる
- 口調: 丁寧で構成的。ユーザーの言葉づかいに寄せる

✅ ソラ(Todo・進行管理担当)
- 会話に出てきた「やること」を拾ってTodoに登録し、期限と優先度をつける
- ユーザーが「終わった」と言ったらTodoを完了にする
- 抱えているTodoが多いときは、今日やるべき2〜3件に絞って提案する
- 口調: 短く、歯切れよく。確認は一言で

応答のルール:
1. ユーザーのメッセージ内容に応じて、最も適切なメンバー(1〜3人)が発言する。
   全員が毎回話す必要はない。調べもの→サトル中心、文書作成→カエデ中心、
   タスクの話→ソラ中心。
2. 各発言の冒頭に「🔍 サトル:」のように名前を付ける。
3. 事実確認が必要な質問(最新の動向・数字・他社事例・製品仕様・法令など)では、
   サトルは必ず web_search を使う。自分の記憶だけで答えず、検索結果にもとづいて答える。
4. Todoの登録・完了は、応答の最後に次の形式の行を追加する
   (記録システムが読み取る行なので、画面には表示されない)。
   [TODO_ADD] タイトル | 期限(YYYY-MM-DD または -) | 優先度(高/中/低)
   [TODO_DONE] Todo番号
   例: [TODO_ADD] 競合3社の価格表をまとめる | 2026-08-03 | 高
   該当しない場合は出力しない。1回の応答で複数行出してよい。
5. 企画書・提案書などまとまった文書をドラフトしたときは、次の形で囲む
   (自動保存され、あとでMarkdownとしてダウンロードできる)。
   [DRAFT_START] 文書タイトル
   (Markdown本文)
   [DRAFT_END]
   囲みの中身はそのままユーザーにも表示されるので、本文中に囲みの説明は書かない。
6. 提供される<現在の状況>(今日の日付・未完了Todo・保存済み文書・直近の調査メモ)は
   積極的に参照する。日付の計算は必ず<現在の状況>の今日の日付を基準にする。
7. チャットでの発言は簡潔に。1人あたり300字程度まで。
   ただし [DRAFT_START]〜[DRAFT_END] の中身は必要なだけ書いてよい。
8. 分からないこと・決められないことは勝手に決めず、ユーザーに質問を1つだけ返す。
"""

_client = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()  # ANTHROPIC_API_KEY を環境変数から読む
    return _client


def _collect_sources(response) -> list[dict]:
    """応答に含まれるウェブ検索結果から出典(タイトルとURL)を集める。"""
    sources = []
    for block in response.content:
        if block.type != "web_search_tool_result":
            continue
        # エラー時は content が単一のエラーオブジェクトになる(リストではない)
        if not isinstance(block.content, list):
            continue
        for result in block.content:
            url = getattr(result, "url", None)
            if url:
                sources.append({"title": getattr(result, "title", "") or url, "url": url})
    return sources


def team_chat(history: list[dict], user_message: str, context: str) -> tuple[str, list[dict]]:
    """会話履歴と現在の状況を添えて、エージェントチームの応答を得る。

    history: [{"role": "user"|"assistant", "content": str}, ...]
    context: 今日の日付・未完了Todo・保存済み文書などのテキスト(整形済み)

    戻り値: (応答テキスト, 参照した出典のリスト)
    """
    text = user_message
    if context:
        text = f"<現在の状況>\n{context}\n</現在の状況>\n\n{text}"

    messages = list(history)
    messages.append({"role": "user", "content": text})

    sources: list[dict] = []
    seen_urls: set[str] = set()

    for _ in range(MAX_CONTINUATIONS + 1):
        response = get_client().messages.create(
            model=MODEL,
            max_tokens=8192,
            thinking={"type": "adaptive"},
            system=[
                {
                    "type": "text",
                    "text": TEAM_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=[WEB_SEARCH_TOOL],
            messages=messages,
        )

        for source in _collect_sources(response):
            if source["url"] not in seen_urls:
                seen_urls.add(source["url"])
                sources.append(source)

        if response.stop_reason == "refusal":
            return "✅ ソラ: すみません、その内容にはお答えできません。別の聞き方で試してください。", []

        # 検索がツール実行の上限に達して一旦止まった場合は、そのまま続きを依頼する
        if response.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": response.content})
            continue

        reply = "".join(block.text for block in response.content if block.type == "text")
        return reply.strip(), sources

    return "🔍 サトル: 調査が長引いたため一旦止めました。範囲を絞って聞き直してもらえますか。", sources


# ---------- 応答の中の記録用マーカーを読み取る ----------

def parse_todo_adds(reply: str) -> list[dict]:
    """[TODO_ADD] 行を抽出する。"""
    todos = []
    for line in reply.splitlines():
        line = line.strip()
        if not line.startswith("[TODO_ADD]"):
            continue
        parts = [p.strip() for p in line.removeprefix("[TODO_ADD]").split("|")]
        title = parts[0] if parts else ""
        if not title:
            continue
        due = parts[1] if len(parts) > 1 and parts[1] not in ("", "-") else None
        priority = parts[2] if len(parts) > 2 and parts[2] in ("高", "中", "低") else "中"
        todos.append({"title": title, "due": due, "priority": priority})
    return todos


def parse_todo_dones(reply: str) -> list[int]:
    """[TODO_DONE] 行からTodo番号を抽出する。"""
    ids = []
    for line in reply.splitlines():
        line = line.strip()
        if not line.startswith("[TODO_DONE]"):
            continue
        digits = "".join(c for c in line.removeprefix("[TODO_DONE]") if c.isdigit())
        if digits:
            ids.append(int(digits))
    return ids


def parse_drafts(reply: str) -> list[tuple[str, str]]:
    """[DRAFT_START]〜[DRAFT_END] で囲まれた文書を (タイトル, 本文) で返す。"""
    drafts = []
    title = None
    body: list[str] = []
    for line in reply.splitlines():
        stripped = line.strip()
        if stripped.startswith("[DRAFT_START]"):
            title = stripped.removeprefix("[DRAFT_START]").strip() or "無題の文書"
            body = []
        elif stripped.startswith("[DRAFT_END]"):
            if title is not None:
                drafts.append((title, "\n".join(body).strip()))
            title = None
            body = []
        elif title is not None:
            body.append(line)
    # [DRAFT_END] が欠けたまま応答が終わった場合も救済する
    if title is not None and body:
        drafts.append((title, "\n".join(body).strip()))
    return drafts


def strip_markers(reply: str) -> str:
    """記録用のマーカー行だけを取り除く(文書の本文は残す)。"""
    markers = ("[TODO_ADD]", "[TODO_DONE]", "[DRAFT_START]", "[DRAFT_END]")
    lines = [ln for ln in reply.splitlines() if not ln.strip().startswith(markers)]
    return "\n".join(lines).strip()
