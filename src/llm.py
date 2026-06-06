"""
Gemini 接続の共通土台

設計（CLAUDE.md）どおり、2つのモデルを使い分ける:
  - Flash（安い・高頻度）: 自然言語→JSON変換、既知/未知の分類      ← パーサで使用
  - Pro  （高精度・低頻度）: ハンドラ生成・テスト生成・自信度評価   ← L2フローで使用

APIキーは .env の GEMINI_API_KEY から読む。
キーが無い場合は is_available() が False を返し、呼び出し側はスタブに切り替える。
"""

import os
from typing import Optional, Type, TypeVar

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


def generate_structured(
    prompt: str,
    schema: Type[T],
    model: str = FLASH_MODEL,
    temperature: float = 0.0,
) -> T:
    """
    プロンプトを投げ、Pydanticスキーマに沿った構造化JSONを受け取って返す。

    temperature=0 で決定的寄りに（JSON変換は揺れないほうが良い）。
    """
    from google.genai import types

    client = _get_client()
    resp = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=temperature,
            response_mime_type="application/json",
            response_schema=schema,
        ),
    )
    # SDK がパース済みインスタンスを返す場合はそれを使う
    if getattr(resp, "parsed", None) is not None:
        return resp.parsed  # type: ignore[return-value]
    # 念のためのフォールバック（テキストJSONを自前で検証）
    return schema.model_validate_json(resp.text)


def list_models() -> list[str]:
    """利用可能なモデル名の一覧（モデル名の確認・デバッグ用）。"""
    client = _get_client()
    names = []
    for m in client.models.list():
        name = getattr(m, "name", "")
        if name:
            names.append(name)
    return names
