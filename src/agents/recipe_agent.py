"""
RecipeAgent — 未知タイプを「レシピ（操作×選択子）」として設計させる（Proモデル）

旧HandlerAgent（Pythonコード生成）の置き換え。AIに生のPythonを書かせず、
安全な部品（操作＋選択子）の**組み合わせ＝レシピ（データ）**を出させる。
これでAPI誤用バグが構造的に発生せず、AIコードのexecも不要になる。

出力:
  recipe_template_json … このtypeの操作＋固定の選択子（per-occで変わる値はプレースホルダでも可）
  example_recipe_json  … 完成レシピの具体例（検証用・person_id="p1"等）
  fill_fields          … 各人ごとに埋める選択子（例 ["person_id","weekday"]）
  explanation/confidence/concerns
"""

from pydantic import BaseModel

from src import llm
from src.models.admin_queue import PendingTypeRequest

from .base import GeminiAgent


class GeneratedRecipe(BaseModel):
    expressible: bool = True      # 現在の操作・選択子で表現できるか（分かったフリをしない）
    reject_category: str = ""     # 表現できない理由カテゴリ（expressible=false時）
    recipe_template_json: str     # 操作＋選択子（JSON文字列）
    example_recipe_json: str      # 完成例（JSON文字列）
    fill_fields: list[str]        # per-occurrenceで埋める選択子
    explanation: str              # 日本語の短い説明
    confidence: float             # 0.0〜1.0
    concerns: list[str]           # 懸念点（表現できない疑い等）


class RecipeAgent(GeminiAgent):
    """未知タイプをレシピとして設計するエージェント（Pro）。"""

    model = llm.PRO_MODEL
    schema = GeneratedRecipe
    prompt_name = "recipe_gen"

    def generate(self, req: PendingTypeRequest) -> GeneratedRecipe:
        source_texts = "\n".join(f"- {t}" for t in req.source_texts)
        return self.run_structured(
            type_name=req.suggested_type_name,
            source_texts=source_texts,
            summary=req.summary or "（要約なし）",
            ai_assessment=req.ai_assessment or "（見解なし）",
        )
