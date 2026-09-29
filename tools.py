"""ライティングツールの定義（入力項目とプロンプト）。

ツールを追加したいときは、Tool を1つ定義して TOOLS に追加するだけでOK。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

BASE_SYSTEM = (
    "あなたは経験豊富なプロの日本語ライター兼編集者です。"
    "読み手にとって分かりやすく、自然で正確な日本語を書きます。"
    "前置きや「承知しました」などの返事は書かず、成果物だけを出力してください。"
    "出力はMarkdown形式で整形してください。"
)


@dataclass
class Field:
    key: str
    label: str
    kind: str = "text"  # text | textarea | select | number
    options: list[str] = field(default_factory=list)
    default: object = None
    placeholder: str = ""
    required: bool = False
    help: str | None = None
    height: int = 200
    min_value: int = 1
    max_value: int = 10


@dataclass
class Tool:
    id: str
    name: str
    icon: str
    description: str
    fields: list[Field]
    build_prompt: Callable[[dict], str]
    system: str = ""
    temperature: float = 0.7

    @property
    def label(self) -> str:
        return f"{self.icon} {self.name}"

    @property
    def system_prompt(self) -> str:
        return f"{BASE_SYSTEM}\n{self.system}".strip()


def _lines(*pairs: tuple[str, object]) -> str:
    """値が空の項目を除いて「- ラベル: 値」の箇条書きにする。"""
    return "\n".join(f"- {k}: {v}" for k, v in pairs if v not in (None, ""))


TONES = ["親しみやすい", "丁寧・フォーマル", "専門的", "カジュアル", "熱意がある"]


# ---------------------------------------------------------------- ブログ記事
def _blog(v: dict) -> str:
    return f"""以下の条件でブログ記事を執筆してください。

{_lines(
    ("テーマ", v["theme"]),
    ("含めたいキーワード", v["keywords"]),
    ("想定読者", v["audience"]),
    ("文字数の目安", f"約{v['length']}文字"),
    ("文体・トーン", v["tone"]),
    ("その他の要望", v["notes"]),
)}

# 構成
- 1行目に記事タイトル（# 見出し）
- 導入文 → 本文（## / ### 見出しで区切る）→ まとめ
- キーワードは自然に盛り込み、読者の疑問に答える内容にする
"""


# ---------------------------------------------------------------- メール返信
def _email_reply(v: dict) -> str:
    return f"""次の受信メールへの返信文を作成してください。

# 受信メール
{v["received"]}

# 返信の条件
{_lines(
    ("返信で伝えたい要点", v["points"] or "受信内容に対する適切な返答"),
    ("相手との関係", v["relation"]),
    ("トーン", v["tone"]),
    ("差出人名（署名）", v["signature"]),
)}

# 出力形式
**件名:** Re: 〜

（本文）

相手や状況に合った敬語を使い、要点が一目で分かるようにしてください。
"""


# ---------------------------------------------------------------- メール作成
def _email_new(v: dict) -> str:
    return f"""次の条件でメールを新規作成してください。

{_lines(
    ("宛先", v["to"]),
    ("メールの目的", v["purpose"]),
    ("伝えたい内容", v["points"]),
    ("トーン", v["tone"]),
    ("差出人名（署名）", v["signature"]),
)}

# 出力形式
**件名:** 〜

（本文）

件名は内容が一目で分かる簡潔なものにしてください。
"""


# ---------------------------------------------------------------- 要約
def _summary(v: dict) -> str:
    return f"""次の文章を要約してください。

# 要約の条件
{_lines(
    ("形式", v["style"]),
    ("長さ", v["length"]),
    ("特に注目してほしい観点", v["focus"]),
)}
- 原文にない情報は加えない

# 原文
{v["text"]}
"""


# ---------------------------------------------------------------- 校正
def _proofread(v: dict) -> str:
    return f"""次の文章を校正してください。

# 校正レベル
{v["level"]}

# 出力形式
## 修正後の文章
（修正後の全文）

## 修正箇所
| 修正前 | 修正後 | 理由 |
|---|---|---|

修正箇所がない場合は「修正箇所はありません」と書いてください。

# 原文
{v["text"]}
"""


# ---------------------------------------------------------------- リライト
def _rewrite(v: dict) -> str:
    return f"""次の文章を、指定の文体にリライトしてください。
意味や情報は変えずに、表現だけを変えてください。

{_lines(
    ("変換後の文体", v["style"]),
    ("その他の要望", v["notes"]),
)}

# 原文
{v["text"]}
"""


# ---------------------------------------------------------------- 翻訳
def _translate(v: dict) -> str:
    return f"""次の文章を{v["lang"]}に翻訳してください。

{_lines(
    ("訳し方", v["style"]),
    ("補足（用途・専門用語など）", v["notes"]),
)}
- 翻訳結果のみを出力する

# 原文
{v["text"]}
"""


# ---------------------------------------------------------------- SNS投稿
def _sns(v: dict) -> str:
    return f"""次の条件でSNS投稿文を{v["count"]}案作成してください。

{_lines(
    ("プラットフォーム", v["platform"]),
    ("投稿の内容・伝えたいこと", v["topic"]),
    ("トーン", v["tone"]),
    ("ハッシュタグ", v["hashtags"]),
)}
- プラットフォームの文字数制限や文化に合わせる（Xは140字以内など）
- 案ごとに「## 案1」のように見出しを付ける
"""


# ---------------------------------------------------------------- タイトル・コピー
def _titles(v: dict) -> str:
    return f"""次の内容に合う{v["kind"]}を{v["count"]}個提案してください。

{_lines(
    ("内容", v["content"]),
    ("ターゲット", v["audience"]),
    ("方向性", v["tone"]),
)}

# 出力形式
番号付きリストで、各案の後ろに（ ）で狙い・ポイントを一言添えてください。
"""


# ---------------------------------------------------------------- 構成案
def _outline(v: dict) -> str:
    return f"""次の条件で文章の構成案（アウトライン）を作成してください。

{_lines(
    ("種類", v["kind"]),
    ("テーマ", v["theme"]),
    ("想定読者", v["audience"]),
    ("目的・ゴール", v["goal"]),
)}

# 出力形式
- 見出し（H2/H3）の階層構造
- 各見出しの下に、書くべき内容の要点を箇条書きで2〜3個
- 最後に「この構成のポイント」を簡潔に
"""


# ---------------------------------------------------------------- メモから文章化
def _memo(v: dict) -> str:
    return f"""次のメモ・箇条書きをもとに、まとまった文章に仕上げてください。

{_lines(
    ("用途", v["purpose"]),
    ("文体", v["style"]),
    ("文字数の目安", f"約{v['length']}文字" if v["length"] else ""),
)}
- メモの情報はすべて活かし、事実を勝手に追加しない
- 自然な接続で読みやすい流れにする

# メモ
{v["memo"]}
"""


TOOLS: list[Tool] = [
    Tool(
        id="blog",
        name="ブログ記事執筆",
        icon="📝",
        description="テーマとキーワードから、見出し付きのブログ記事を丸ごと書きます。",
        system="SEOを意識しつつ、読者にとって価値のある記事を書きます。",
        temperature=0.8,
        fields=[
            Field("theme", "テーマ", required=True, placeholder="例: 在宅ワークの集中力を上げる方法"),
            Field("keywords", "キーワード（任意）", placeholder="例: 在宅ワーク, 集中力, ポモドーロ"),
            Field("audience", "想定読者（任意）", placeholder="例: 在宅勤務を始めたばかりの会社員"),
            Field("notes", "その他の要望（任意）", kind="textarea", height=100,
                  placeholder="例: 体験談風に / 具体例を多めに"),
            Field("length", "文字数の目安", kind="select",
                  options=["1000", "2000", "3000", "5000"], default="2000"),
            Field("tone", "トーン", kind="select", options=TONES),
        ],
        build_prompt=_blog,
    ),
    Tool(
        id="email_reply",
        name="メール返信",
        icon="↩️",
        description="受信したメールを貼り付けると、状況に合った返信文を作ります。",
        temperature=0.5,
        fields=[
            Field("received", "受信したメール", kind="textarea", required=True,
                  placeholder="返信したいメールの本文を貼り付けてください"),
            Field("points", "返信で伝えたいこと（任意）", kind="textarea", height=100,
                  placeholder="例: 日程はOK。ただし開始を30分遅らせてほしい"),
            Field("signature", "署名（任意）", placeholder="例: 山田太郎"),
            Field("relation", "相手との関係", kind="select",
                  options=["社外（取引先・顧客）", "上司", "同僚", "部下", "友人・知人"]),
            Field("tone", "トーン", kind="select", options=["丁寧", "標準", "カジュアル"]),
        ],
        build_prompt=_email_reply,
    ),
    Tool(
        id="email_new",
        name="メール作成",
        icon="✉️",
        description="目的と要点を伝えるだけで、件名付きのメールを新規作成します。",
        temperature=0.5,
        fields=[
            Field("to", "宛先", required=True, placeholder="例: 取引先の担当者 佐藤様"),
            Field("purpose", "メールの目的", required=True, placeholder="例: 打ち合わせ日程の調整依頼"),
            Field("points", "伝えたい内容（任意）", kind="textarea", height=120,
                  placeholder="例: 候補日は10/3午後、10/5終日。オンライン希望"),
            Field("signature", "署名（任意）", placeholder="例: 株式会社〇〇 山田太郎"),
            Field("tone", "トーン", kind="select", options=["丁寧", "標準", "カジュアル"]),
        ],
        build_prompt=_email_new,
    ),
    Tool(
        id="summary",
        name="文章要約",
        icon="📋",
        description="長い文章・記事・議事録などを、指定の形式で要約します。",
        temperature=0.3,
        fields=[
            Field("text", "要約したい文章", kind="textarea", required=True, height=300),
            Field("focus", "注目してほしい観点（任意）", placeholder="例: 決定事項とToDo"),
            Field("style", "形式", kind="select",
                  options=["箇条書き", "文章（段落）", "3行要約", "見出し付きレポート"]),
            Field("length", "長さ", kind="select", options=["短め", "標準", "詳しめ"], default="標準"),
        ],
        build_prompt=_summary,
    ),
    Tool(
        id="proofread",
        name="校正・推敲",
        icon="🔍",
        description="誤字脱字・文法・表現をチェックし、修正箇所を一覧で示します。",
        temperature=0.2,
        fields=[
            Field("text", "校正したい文章", kind="textarea", required=True, height=300),
            Field("level", "校正レベル", kind="select",
                  options=["誤字脱字・文法ミスのみ修正", "読みやすさも改善", "大胆に推敲して磨き上げる"]),
        ],
        build_prompt=_proofread,
    ),
    Tool(
        id="rewrite",
        name="リライト・文体変換",
        icon="🔄",
        description="意味はそのままに、文体やトーンを変えて書き直します。",
        temperature=0.6,
        fields=[
            Field("text", "元の文章", kind="textarea", required=True, height=250),
            Field("notes", "その他の要望（任意）", placeholder="例: もう少し短く"),
            Field("style", "変換後の文体", kind="select",
                  options=["です・ます調", "だ・である調", "ビジネス向け", "カジュアル",
                           "やさしい日本語（小学生にも分かるように）", "説得力のある文章", "簡潔に短く"]),
        ],
        build_prompt=_rewrite,
    ),
    Tool(
        id="translate",
        name="翻訳",
        icon="🌐",
        description="自然な表現で多言語に翻訳します。",
        temperature=0.3,
        fields=[
            Field("text", "翻訳したい文章", kind="textarea", required=True, height=250),
            Field("notes", "補足（任意）", placeholder="例: 海外の取引先へのメール"),
            Field("lang", "翻訳先", kind="select",
                  options=["英語", "日本語", "中国語（簡体字）", "韓国語", "スペイン語", "フランス語", "ドイツ語"]),
            Field("style", "訳し方", kind="select", options=["自然な意訳", "原文に忠実な直訳", "ビジネス向け", "カジュアル"]),
        ],
        build_prompt=_translate,
    ),
    Tool(
        id="sns",
        name="SNS投稿作成",
        icon="📱",
        description="X・Instagramなど、媒体に合わせた投稿文を複数案作ります。",
        temperature=0.9,
        fields=[
            Field("topic", "投稿の内容", kind="textarea", required=True, height=120,
                  placeholder="例: 新しいブログ記事を公開した告知"),
            Field("platform", "プラットフォーム", kind="select",
                  options=["X (Twitter)", "Instagram", "Threads", "Facebook", "LinkedIn", "note"]),
            Field("tone", "トーン", kind="select", options=TONES),
            Field("hashtags", "ハッシュタグ", kind="select", options=["付ける", "付けない"]),
            Field("count", "案の数", kind="number", default=3, max_value=5),
        ],
        build_prompt=_sns,
    ),
    Tool(
        id="titles",
        name="タイトル・キャッチコピー",
        icon="💡",
        description="記事タイトル、キャッチコピー、メール件名などのアイデアを量産します。",
        temperature=1.0,
        fields=[
            Field("content", "内容・概要", kind="textarea", required=True, height=120),
            Field("audience", "ターゲット（任意）", placeholder="例: 20代の社会人"),
            Field("kind", "種類", kind="select",
                  options=["ブログ記事タイトル", "キャッチコピー", "メール件名", "YouTube動画タイトル", "商品名・サービス名"]),
            Field("tone", "方向性", kind="select", options=["興味を引く", "信頼感", "シンプル", "インパクト重視", "SEO重視"]),
            Field("count", "案の数", kind="number", default=10, max_value=20),
        ],
        build_prompt=_titles,
    ),
    Tool(
        id="outline",
        name="構成案作成",
        icon="🗂️",
        description="記事・資料・スピーチなどの見出し構成を考えます。",
        temperature=0.7,
        fields=[
            Field("theme", "テーマ", required=True),
            Field("audience", "想定読者（任意）"),
            Field("goal", "目的・ゴール（任意）", placeholder="例: 読者に〇〇を始めてもらう"),
            Field("kind", "種類", kind="select",
                  options=["ブログ記事", "プレゼン資料", "レポート", "スピーチ", "YouTube台本"]),
        ],
        build_prompt=_outline,
    ),
    Tool(
        id="memo",
        name="メモから文章化",
        icon="🧩",
        description="箇条書きや走り書きのメモを、まとまった文章に仕上げます。",
        temperature=0.6,
        fields=[
            Field("memo", "メモ・箇条書き", kind="textarea", required=True, height=250,
                  placeholder="- 今日の会議で新企画が承認\n- 開始は来月\n- 担当は田中さん"),
            Field("purpose", "用途（任意）", placeholder="例: 社内報告 / 日報 / ブログ"),
            Field("style", "文体", kind="select", options=["です・ます調", "だ・である調", "カジュアル"]),
            Field("length", "文字数の目安（任意）", kind="select",
                  options=["", "200", "400", "800", "1500"]),
        ],
        build_prompt=_memo,
    ),
]

TOOLS_BY_ID = {t.id: t for t in TOOLS}
