"""
GeminiAgent 基底クラス ＋ プロンプト読み込み

各エージェントは GeminiAgent を継承し、3つを宣言するだけでよい:
  - model        : 使うモデル（llm.FLASH_MODEL / llm.PRO_MODEL）
  - schema       : 期待する構造化出力（Pydanticモデル）
  - prompt_name  : prompts/<name>.txt のファイル名

プロンプトは src/agents/prompts/ にテキストで置く（コードを触らず編集できる）。
穴埋めは $変数 形式（string.Template）。JSONの波括弧 { } と衝突しないため。
"""

import string
from pathlib import Path
from typing import Type, TypeVar

from pydantic import BaseModel

from src import llm

_PROMPT_DIR = Path(__file__).parent / "prompts"

T = TypeVar("T", bound=BaseModel)


def load_prompt(name: str, **variables: str) -> str:
    """prompts/<name>.txt を読み、$変数 を埋めて返す。"""
    text = (_PROMPT_DIR / f"{name}.txt").read_text(encoding="utf-8")
    # safe_substitute: 渡し忘れた変数があってもエラーにせず、そのまま残す
    return string.Template(text).safe_substitute(**variables)


class GeminiAgent:
    """役割を1つ担うエージェントの基底。"""

    model: str = llm.FLASH_MODEL      # 既定は安いFlash。Proを使う役割は上書きする
    schema: Type[BaseModel]           # サブクラスで必ず指定
    prompt_name: str                  # サブクラスで必ず指定
    thinking_budget: int | None = None  # 0で思考オフ（抽出タスク向け・コスト減）

    def build_prompt(self, **variables: str) -> str:
        return load_prompt(self.prompt_name, **variables)

    def run_structured(self, **variables: str):
        """プロンプトを組み立てて Gemini に投げ、schema 通りの構造化出力を返す。"""
        prompt = self.build_prompt(**variables)
        return llm.generate_structured(
            prompt, schema=self.schema, model=self.model,
            thinking_budget=self.thinking_budget,
        )
