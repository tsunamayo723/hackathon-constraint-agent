"""
Gemini 接続の共通土台

設計（CLAUDE.md）どおり、2つのモデルを使い分ける:
  - Flash（安い・高頻度）: 自然言語→JSON変換、既知/未知の分類      ← パーサで使用
  - Pro  （高精度・低頻度）: ハンドラ生成・テスト生成・自信度評価   ← L2フローで使用

APIキーは .env の GEMINI_API_KEY から読む。
キーが無い場合は is_available() が False を返し、呼び出し側はスタブに切り替える。
"""

import logging
import os
import time
from typing import Type, TypeVar

from dotenv import load_dotenv
from pydantic import BaseModel

# プロジェクト直下の .env を読み込む（無くてもエラーにしない）
load_dotenv()

# モデル名は環境変数で差し替え可能（API側で名称が変わっても .env だけ直せばよい）
FLASH_MODEL = os.environ.get("GEMINI_FLASH_MODEL", "gemini-2.5-flash")
PRO_MODEL = os.environ.get("GEMINI_PRO_MODEL", "gemini-2.5-pro")

def _load_api_key() -> str:
    """有効そうなAPIキーだけを返す。未設定・プレースホルダ・全角混じりは無効扱い。"""
    raw = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
    # .env のプレースホルダや、日本語など非ASCIIが混じる値は「未設定」とみなす
    if not raw or not raw.isascii() or raw == "ここにキーを貼る":
        return ""
    return raw


_API_KEY = _load_api_key()

T = TypeVar("T", bound=BaseModel)

# クライアントは初回利用時に1回だけ作る
_client = None


def is_available() -> bool:
    """Gemini が使える状態か（有効そうなAPIキーが設定済みか）。"""
    return bool(_API_KEY)


def _get_client():
    """google-genai のクライアントを返す（遅延生成）。"""
    global _client
    if _client is None:
        if not _API_KEY:
            raise RuntimeError(
                "GEMINI_API_KEY が設定されていません。プロジェクト直下の .env に記載してください。"
            )
        from google import genai
        _client = genai.Client(api_key=_API_KEY)
    return _client


# Google側の一時的な障害（混雑等）を表すサイン。これらは自動リトライする。
# 429（枠切れ）は待っても回復しないことが多いのでリトライしない（即エラーにする）。
_TRANSIENT_SIGNS = ("UNAVAILABLE", "503", "500", "502", "504", "overloaded",
                    "high demand", "INTERNAL", "deadline")

_MAX_RETRIES = 3  # 初回 + リトライ。待ち時間は 1秒 → 2秒（指数バックオフ）


def _is_transient(exc: Exception) -> bool:
    """Google側の一時的なエラー（リトライで回復しうる）か判定する。"""
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if code in (500, 502, 503, 504):
        return True
    msg = str(exc)
    if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
        return False  # 枠切れはリトライ対象外
    return any(sign in msg for sign in _TRANSIENT_SIGNS)


def generate_structured(
    prompt: str,
    schema: Type[T],
    model: str = FLASH_MODEL,
    temperature: float = 0.0,
    thinking_budget: int | None = None,
) -> T:
    """
    プロンプトを投げ、Pydanticスキーマに沿った構造化JSONを受け取って返す。

    temperature=0 で決定的寄りに（JSON変換は揺れないほうが良い）。
    503など**一時的なエラーは自動リトライ**（指数バックオフ）。429は即エラー。

    thinking_budget=0 で「思考(thinking)」を無効化できる（Flashの抽出タスク向け）。
    思考トークンは出力料金で課金されるため、不要なら0にするとコストが大きく下がる。
    """
    from google.genai import types

    client = _get_client()
    config = types.GenerateContentConfig(
        temperature=temperature,
        response_mime_type="application/json",
        response_schema=schema,
        thinking_config=(
            types.ThinkingConfig(thinking_budget=thinking_budget)
            if thinking_budget is not None else None
        ),
    )

    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            resp = client.models.generate_content(model=model, contents=prompt, config=config)
            _record_usage(model, resp)
            # SDK がパース済みインスタンスを返す場合はそれを使う
            if getattr(resp, "parsed", None) is not None:
                return resp.parsed  # type: ignore[return-value]
            # 念のためのフォールバック（テキストJSONを自前で検証）
            return schema.model_validate_json(resp.text)
        except Exception as exc:
            last_exc = exc
            # 一時的なエラーかつ残り試行があるなら、少し待って再試行
            if _is_transient(exc) and attempt < _MAX_RETRIES - 1:
                time.sleep(2 ** attempt)  # 1秒, 2秒, ...
                continue
            raise

    # ここには通常到達しないが、保険
    raise last_exc  # type: ignore[misc]


def _record_usage(model: str, resp) -> None:
    """レスポンスの usage_metadata からトークン数を読み、利用量を記録・ログ出力する。"""
    meta = getattr(resp, "usage_metadata", None)
    if meta is None:
        return
    in_tok = getattr(meta, "prompt_token_count", 0) or 0
    # 出力＝回答トークン＋思考(thinking)トークン。思考も出力料金で課金されるため必ず加算する。
    out_tok = (getattr(meta, "candidates_token_count", 0) or 0) + (getattr(meta, "thoughts_token_count", 0) or 0)
    try:
        from src import usage
        rec = usage.record(model, in_tok, out_tok)
        logging.getLogger("uvicorn.error").info(
            "Gemini[%s] tokens in=%d out=%d total=%d 概算 ¥%.3f",
            model, rec["input_tokens"], rec["output_tokens"],
            rec["total_tokens"], rec["jpy"],
        )
    except Exception:
        pass  # 計測は失敗しても本処理は止めない


def list_models() -> list[str]:
    """利用可能なモデル名の一覧（モデル名の確認・デバッグ用）。"""
    client = _get_client()
    names = []
    for m in client.models.list():
        name = getattr(m, "name", "")
        if name:
            names.append(name)
    return names
