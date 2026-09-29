"""AIライティングツール（Streamlit + Gemini API）

起動: streamlit run app.py
"""

from __future__ import annotations

import os
from datetime import datetime

import streamlit as st
from dotenv import load_dotenv

from gemini_client import MAX_RETRIES, stream_text
from tools import TOOLS, TOOLS_BY_ID, Field, Tool

load_dotenv()

st.set_page_config(page_title="AIライティングツール", page_icon="✍️", layout="wide")

MODELS = ["gemini-3.8-flash"]
CUSTOM_MODEL = "その他（手入力）"
HISTORY_LIMIT = 30

REFINE_TEMPLATE = """以下は先ほどあなたが作成した文章です。
次の指示に従って修正し、修正後の全文だけを出力してください。

# 指示
{instruction}

# 文章
{text}
"""

ss = st.session_state
ss.setdefault("results", {})  # tool.id -> 最新の生成結果
ss.setdefault("history", [])  # 生成履歴（新しい順）


# ------------------------------------------------------------------ サイドバー
def render_sidebar() -> tuple[Tool, str, str, float]:
    with st.sidebar:
        st.title("✍️ AIライティング")
        tool_id = st.radio(
            "ツールを選択",
            [t.id for t in TOOLS],
            format_func=lambda i: TOOLS_BY_ID[i].label,
            key="tool_id",
        )
        tool = TOOLS_BY_ID[tool_id]

        st.divider()
        env_key = os.getenv("GEMINI_API_KEY", "")
        input_key = st.text_input(
            "🔑 Gemini APIキー",
            type="password",
            key="api_key",
            placeholder="AIza... を貼り付け",
            help="ここに入力したキーが優先されます。空欄なら .env の GEMINI_API_KEY を使います。",
        ).strip()
        api_key = input_key or env_key
        if input_key:
            st.caption("✅ 入力したAPIキーを使用中")
        elif env_key:
            st.caption("✅ .env のAPIキーを使用中")
        else:
            st.caption("⚠️ APIキーが未設定です（[取得はこちら](https://aistudio.google.com/apikey)）")

        with st.expander("⚙️ 詳細設定"):
            default_model = os.getenv("GEMINI_MODEL", MODELS[0])
            models = MODELS if default_model in MODELS else [default_model, *MODELS]
            model = st.selectbox("モデル", [*models, CUSTOM_MODEL], index=models.index(default_model))
            if model == CUSTOM_MODEL:
                model = st.text_input("モデル名", placeholder="例: gemini-3.8-flash").strip() or default_model
            temperature = st.slider(
                "創造性（temperature）",
                0.0,
                2.0,
                tool.temperature,
                0.1,
                key=f"temp_{tool.id}",
                help="低いほど正確・安定、高いほど自由で多様な文章になります",
            )
    return tool, api_key, model, temperature


# ------------------------------------------------------------------ 入力フォーム
def render_field(f: Field, tool_id: str):
    key = f"{tool_id}__{f.key}"
    if f.kind == "textarea":
        return st.text_area(f.label, placeholder=f.placeholder, height=f.height, key=key, help=f.help)
    if f.kind == "select":
        index = f.options.index(f.default) if f.default in f.options else 0
        return st.selectbox(
            f.label, f.options, index=index, key=key, help=f.help,
            format_func=lambda o: o or "指定なし",
        )
    if f.kind == "number":
        return st.number_input(
            f.label, f.min_value, f.max_value, value=f.default or f.min_value, step=1, key=key, help=f.help
        )
    return st.text_input(f.label, placeholder=f.placeholder, key=key, help=f.help)


def render_form(tool: Tool) -> dict | None:
    """フォームを表示し、送信されたら入力値を返す。"""
    with st.form(f"form_{tool.id}"):
        values = {}
        text_fields = [f for f in tool.fields if f.kind in ("text", "textarea")]
        option_fields = [f for f in tool.fields if f.kind in ("select", "number")]

        for f in text_fields:
            values[f.key] = render_field(f, tool.id)
        if option_fields:
            for col, f in zip(st.columns(len(option_fields)), option_fields):
                with col:
                    values[f.key] = render_field(f, tool.id)

        submitted = st.form_submit_button("✨ 生成する", type="primary", use_container_width=True)

    if not submitted:
        return None
    values = {k: v.strip() if isinstance(v, str) else v for k, v in values.items()}
    missing = [f.label for f in tool.fields if f.required and not values[f.key]]
    if missing:
        st.error(f"未入力の項目があります: {'、'.join(missing)}")
        return None
    return values


# ------------------------------------------------------------------ 生成
def friendly_error(e: Exception) -> str:
    """APIエラーを日本語の分かりやすいメッセージにする。"""
    code = getattr(e, "code", None)
    if code == 503:
        return "Gemini が混み合っています。自動で再試行しましたが接続できませんでした。少し時間をおいて再度お試しください。"
    if code == 429:
        return "利用回数の上限に達しました（無料枠のレート制限）。1分ほど待ってから再度お試しください。"
    if code == 404:
        return "モデルが見つかりません。サイドバーの「詳細設定」でモデル名を確認してください。"
    if code in (401, 403) or "API key" in str(e):
        return "APIキーが正しくない可能性があります。サイドバーのAPIキーを確認してください。"
    if "Timeout" in type(e).__name__:
        return "Gemini から応答がありませんでした（60秒でタイムアウト）。通信環境を確認し、少し時間をおいて再度お試しください。"
    return "予期しないエラーが発生しました。詳細を確認してください。"


def generate(placeholder, tool: Tool, prompt: str, api_key: str, model: str, temperature: float) -> None:
    if not api_key:
        st.error("Gemini APIキーを設定してください（サイドバー または .env）")
        return
    def on_retry(attempt: int, wait: int) -> None:
        st.toast(f"Gemini が混み合っています。{wait}秒後に再試行します（{attempt}/{MAX_RETRIES}回目）", icon="⏳")

    try:
        with placeholder.container(border=True):
            text = st.write_stream(
                stream_text(api_key, model, tool.system_prompt, prompt, temperature, on_retry=on_retry)
            )
    except Exception as e:  # APIキー誤り・レート制限・通信エラーなど
        placeholder.empty()
        st.error(f"生成に失敗しました: {friendly_error(e)}")
        with st.expander("エラーの詳細"):
            st.code(str(e), language=None, wrap_lines=True)
        return
    if not text:
        st.warning("応答が空でした。入力内容を変えて再度お試しください。")
        return

    ss.results[tool.id] = text
    ss.history.insert(0, {"time": datetime.now().strftime("%m/%d %H:%M"), "tool": tool.label, "text": text})
    del ss.history[HISTORY_LIMIT:]


def render_result(tool: Tool, placeholder, api_key: str, model: str, temperature: float) -> None:
    result = ss.results.get(tool.id)
    if not result:
        return
    placeholder.container(border=True).markdown(result)

    with st.form(f"refine_{tool.id}", clear_on_submit=True, border=False):
        c1, c2 = st.columns([5, 1])
        instruction = c1.text_input(
            "追加指示",
            placeholder="追加指示で修正（例: もっと短く / 具体例を足して / もっとくだけた感じに）",
            label_visibility="collapsed",
        )
        refine = c2.form_submit_button("🔁 修正する", use_container_width=True)
    if refine and instruction.strip():
        prompt = REFINE_TEMPLATE.format(instruction=instruction.strip(), text=result)
        generate(placeholder, tool, prompt, api_key, model, temperature)
        result = ss.results[tool.id]
        placeholder.container(border=True).markdown(result)

    st.caption(f"{len(result):,} 文字")
    c1, c2, _ = st.columns([1, 1, 3])
    c1.download_button(
        "⬇️ 保存 (.md)",
        result,
        file_name=f"{tool.id}_{datetime.now():%Y%m%d_%H%M%S}.md",
        mime="text/markdown",
        use_container_width=True,
    )
    if c2.button("🗑️ クリア", use_container_width=True):
        del ss.results[tool.id]
        st.rerun()
    with st.expander("📋 コピー用テキスト（右上のボタンでコピー）"):
        st.code(result, language=None, wrap_lines=True)


def render_history() -> None:
    if not ss.history:
        st.info("まだ履歴はありません。生成した文章はここに残ります（ページを再読み込みすると消えます）。")
        return
    for i, h in enumerate(ss.history):
        with st.expander(f"{h['time']}　{h['tool']}　— {h['text'][:40].replace(chr(10), ' ')}…"):
            st.markdown(h["text"])
            st.code(h["text"], language=None, wrap_lines=True)


# ------------------------------------------------------------------ メイン
def main() -> None:
    tool, api_key, model, temperature = render_sidebar()

    st.header(tool.label)
    st.caption(tool.description)

    tab_write, tab_history = st.tabs(["✏️ 作成", "🕘 履歴"])
    with tab_write:
        values = render_form(tool)
        placeholder = st.empty()
        if values is not None:
            generate(placeholder, tool, tool.build_prompt(values), api_key, model, temperature)
        render_result(tool, placeholder, api_key, model, temperature)
    with tab_history:
        render_history()


main()
