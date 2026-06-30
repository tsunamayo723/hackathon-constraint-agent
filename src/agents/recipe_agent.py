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

import json

from pydantic import BaseModel

from src import llm
from src.models.admin_queue import PendingTypeRequest

from ._context import masters_context
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

    def generate(self, req: PendingTypeRequest, feedback: str = "") -> GeneratedRecipe:
        source_texts = "\n".join(f"- {t}" for t in req.source_texts)
        return self.run_structured(
            type_name=req.suggested_type_name,
            source_texts=source_texts,
            summary=req.summary or "（要約なし）",
            ai_assessment=req.ai_assessment or "（見解なし）",
            feedback=feedback.strip() or "（追加情報なし）",
            masters=masters_context(),  # 実在IDを渡し、存在しないポジションID捏造を防ぐ
        )


class RecipeUpdate(BaseModel):
    """まとめチャットでAIが「直す」と判断した1ルール分の更新（GeneratedRecipe と同形＋req_id）。"""

    req_id: str                          # どの承認待ちルールを直すか（一覧で渡したID）
    expressible: bool = True
    reject_category: str = ""
    recipe_template_json: str = ""
    example_recipe_json: str = ""
    fill_fields: list[str] = []
    explanation: str = ""
    confidence: float = 0.8
    concerns: list[str] = []


class RecipeChatTurn(BaseModel):
    """まとめチャット1ターンの結果。reply は常に画面へ、updates は直すルールだけ。"""

    reply: str = ""                      # 画面に出すAIの返答（日本語・常に）
    updates: list[RecipeUpdate] = []     # 直すと判断したルールだけ。無ければ空


class RecipeChatAgent(GeminiAgent):
    """生成済みルール群を1つの会話でまとめて仕上げるエージェント（Pro・履歴は毎回渡す）。"""

    model = llm.PRO_MODEL
    schema = RecipeChatTurn
    prompt_name = "recipe_chat"

    def chat(self, reqs: list[PendingTypeRequest], message: str,
             history: list[dict] | None = None) -> RecipeChatTurn:
        """生成済みルール一覧・会話履歴・新メッセージを渡し、返答＋直すルール群を返す。"""
        handlers = "\n".join(
            f"- req_id: {r.id} ／ type名: {r.suggested_type_name} ／ "
            f"要約: {r.summary or '（なし）'}\n"
            f"  現在のレシピ: {json.dumps(r.suggested_recipe, ensure_ascii=False)}"
            for r in reqs
        )
        return self.run_structured(
            handlers=handlers or "（生成済みルールなし）",
            message=message,
            history_json=json.dumps(history or [], ensure_ascii=False),
            masters=masters_context(),
        )
