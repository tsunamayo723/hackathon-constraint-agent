"""
HandlerAgent — 未知タイプのハンドラを自動生成（Proモデル）

役割（CLAUDE.md ⑥AIエージェント / L2フロー）:
  未知タイプ1件に対し、Gemini Pro が
    - paramsスキーマ
    - ハンドラ関数コード（def handle(params, ctx)）
    - 例params
    - 自信度・懸念点
  を生成する。生成後は sandbox でテストして承認材料にする。

正確さが要るので **Pro** を使う（CLAUDE.mdの使い分け）。プロンプトは prompts/handler.txt。
"""

from pydantic import BaseModel

from src import llm
from src.models.admin_queue import PendingTypeRequest

from .base import GeminiAgent


class GeneratedHandler(BaseModel):
    """Proが生成したハンドラ一式（中間フォーマット）。"""
    handler_code: str             # def handle(params, ctx): ...
    param_schema_json: str        # paramsの構造（JSON文字列）
    example_params_json: str      # paramsの具体例（JSON文字列）
    explanation: str              # 何をするハンドラかの日本語説明
    confidence: float             # 0.0〜1.0
    concerns: list[str]           # 懸念点


class HandlerAgent(GeminiAgent):
    """未知タイプのハンドラを生成するエージェント（Pro）。"""

    model = llm.PRO_MODEL
    schema = GeneratedHandler
    prompt_name = "handler"

    def generate(self, req: PendingTypeRequest) -> GeneratedHandler:
        source_texts = "\n".join(f"- {t}" for t in req.source_texts)
        return self.run_structured(
            type_name=req.suggested_type_name,
            source_texts=source_texts,
            summary=req.summary or "（要約なし）",
            ai_assessment=req.ai_assessment or "（見解なし）",
        )
