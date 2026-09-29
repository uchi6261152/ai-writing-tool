# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## コミュニケーション

- **回答・説明はすべて日本語で行う。**
- ユーザーはチュートリアルとして学習しながら開発している。変更内容は「何を・なぜ変えたか」を簡潔に説明する。
- 大きな変更（ファイル構成の変更、ライブラリ追加、既存機能の削除）は、作業前に方針を伝えて確認をとる。

## Overview

個人用のAIライティングツール（ブログ執筆・メール返信・要約・校正・翻訳など）。
技術スタックは **Python + Streamlit + Gemini API（`google-genai` SDK）** に限定。
個人用のため **データベース・認証は不要**（ユーザー方針）。状態はすべて `st.session_state` に保持し、再読み込みで消える前提。
UI文言・プロンプトはすべて日本語。

## Commands

```powershell
pip install -r requirements.txt
streamlit run app.py
```

テスト・リンターは未導入。コード変更後の最低限の確認は構文チェック:

```powershell
python -m py_compile app.py tools.py gemini_client.py
```

## 開発環境の注意

- Windows + PowerShell。プロジェクトのパスに**日本語とスペース**（`デスクトップ\...\python apri`）を含むため、コマンドでパスを扱うときは必ずクォートする。
- OneDrive 同期フォルダ内にある。`.venv` などの大きなフォルダを作る場合は同期負荷に注意。
- ライブラリを追加したら `requirements.txt` も更新する。
- Streamlit は起動中に `app.py` 以外のモジュール（`tools.py` / `gemini_client.py`）の変更を反映しないことがある（`ImportError` などが出る）。これらを変更したら、ユーザーに Streamlit の再起動（`Ctrl + C` → `streamlit run app.py`）を案内する。

## Configuration

- APIキーはサイドバーの入力欄が最優先、空欄なら `.env` の `GEMINI_API_KEY` にフォールバック（`app.py` の `render_sidebar`）。
- モデルは `.env` の `GEMINI_MODEL`（任意）。未知のモデル名は `MODELS` リストの先頭に追加されて選択肢になる。

## Architecture

3ファイル構成で、**ツールはデータ駆動**:

- `tools.py` — 各ライティングツールを `Tool`（入力項目 `Field` のリスト + `build_prompt(values) -> str` + ツール固有の system 文 + 既定 temperature）として定義し、`TOOLS` に並べる。**新しいツールの追加は `Tool` を `TOOLS` に1つ足すだけ**で、サイドバー・フォーム・結果表示・履歴に自動で反映される。
  - `Field.kind` は `text | textarea | select | number`。`build_prompt` には `Field.key` をキーにした dict が渡る（文字列は strip 済み）。
  - 共通の system prompt は `BASE_SYSTEM`（成果物のみ・Markdown出力）で、`Tool.system_prompt` がツール固有文と連結する。
  - `_lines()` は空値の項目を除外して箇条書き化するヘルパー。任意項目は必ずこれを通す。
- `gemini_client.py` — `stream_text()` が Gemini のストリーミング応答をテキストチャンクのジェネレータとして返す。クライアントは `st.cache_resource` でAPIキーごとにキャッシュ。
- `app.py` — Streamlit UI。フォーム描画は `Field.kind` で分岐し、`text/textarea` を上に全幅、`select/number` を下に横並びで表示する（`tools.py` の定義順とは別）。

### 生成フローと session_state

- `ss.results[tool.id]` にツールごとの最新結果、`ss.history` に全ツール共通の履歴（新しい順、`HISTORY_LIMIT` 件）。
- 結果は `st.empty()` のプレースホルダーに `st.write_stream` でストリーミング表示し、完了後に同じプレースホルダーを `markdown` で上書きする。
- 「追加指示で修正」は、前回結果と指示を `REFINE_TEMPLATE` に埋めて同じ `generate()` を再実行し、結果を置き換える（会話履歴は持たない単発呼び出し）。
- ウィジェットの key は `f"{tool_id}__{field.key}"` 形式。

## ツールを追加・変更するときのチェックポイント

- `Tool.id` は一意にする（`ss.results` のキー、フォーム・ウィジェット key、保存ファイル名に使われる）。
- `build_prompt` で参照する `v["..."]` は、すべて `fields` に同じ `key` で定義されていること（不一致は実行時に `KeyError`）。
- 任意項目の `select` で「指定なし」を許す場合は、`options` の先頭に `""` を入れる（`format_func` が「指定なし」と表示する）。
- temperature の目安: 要約・校正・翻訳など正確さ重視は 0.2〜0.3、メールは 0.5、記事は 0.7〜0.8、アイデア出しは 0.9〜1.0。
- プロンプトは「条件（`_lines`）→ 出力形式の指定 → 原文」の順で書く。原文は末尾に置き、指示と混ざらないよう `# 原文` などの見出しで区切る。

## Gemini API の注意

- SDK は新しい **`google-genai`**（`from google import genai`）を使う。旧 `google-generativeai`（`import google.generativeai`）のコード例と混同しない。
- モデル名は更新・廃止されることがある。`404` / `model not found` 系のエラーはまずモデル名を疑う。
- `429`（レート制限）・`503`（混雑）は頻発する。`stream_text()` が出力開始前に限り指数バックオフで自動再試行し（`RETRY_CODES` / `MAX_RETRIES`）、最終的な失敗は `app.py` の `friendly_error()` で日本語化して `st.error` 表示する。アプリは落ちない設計を維持する。
- APIキーは `.env`（`.gitignore` 済み）かサイドバー入力のみ。コードやログに出力しない。
