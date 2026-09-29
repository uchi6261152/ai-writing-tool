"""Gemini API の呼び出しをまとめたモジュール。"""

from __future__ import annotations

import time
from typing import Callable, Iterator

import streamlit as st
from google import genai
from google.genai import errors, types

# 一時的なエラー（レート制限・サーバー混雑）は自動で再試行する
RETRY_CODES = {429, 500, 503}
MAX_RETRIES = 3
# 応答が返ってこないときに待ち続けないよう、通信の制限時間を設ける（ミリ秒）
TIMEOUT_MS = 60_000


@st.cache_resource(show_spinner=False)
def get_client(api_key: str) -> genai.Client:
    return genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=TIMEOUT_MS))


def stream_text(
    api_key: str,
    model: str,
    system: str,
    prompt: str,
    temperature: float,
    on_retry: Callable[[int, int], None] | None = None,
) -> Iterator[str]:
    """Gemini の応答をストリーミングで1チャンクずつ返す。

    出力が始まる前に一時的なエラーが起きた場合は、待ち時間を 2→4→8 秒と
    伸ばしながら再試行する。on_retry(試行回数, 待ち秒数) で通知できる。
    """
    client = get_client(api_key)
    config = types.GenerateContentConfig(
        system_instruction=system,
        temperature=temperature,
    )
    for attempt in range(MAX_RETRIES + 1):
        started = False
        try:
            for chunk in client.models.generate_content_stream(
                model=model, contents=prompt, config=config
            ):
                if chunk.text:
                    started = True
                    yield chunk.text
            return
        except errors.APIError as e:
            # 途中まで出力済みなら、やり直すと文章が重複するので諦める
            if started or e.code not in RETRY_CODES or attempt == MAX_RETRIES:
                raise
            wait = 2 ** (attempt + 1)
            if on_retry:
                on_retry(attempt + 1, wait)
            time.sleep(wait)
