"""
ChatAgent — 提出者/管理者の要望を会話で確認し、複数のルールに整理する（Flash・思考オフ）

②（本人の希望）と③（店全体の要望）で**同じUI・同じAI**を使う。
ユーザーが書いた要望（複数可・日ごとメモ含む）を読み、曖昧なら1つずつ聞き返し、
はっきりしたら **要望ごとに** queue/memo/reject に分類して返す。

設計（ユーザー指定）:
  - 会話整理は Flash（Proは使わない）・ステートレス（履歴は毎回渡す）。
  - **新ルール（毎週○曜・前日遅番なら翌日休み 等）は queue → 管理者の承認(④)へ**。
    即適用はせず、④でPro生成→承認してから反映する（L2の流れ）。

入力: requirements（要望の原文・複数行可）/ scope（"person" 本人 | "store" 店舗）/ history
出力: ChatTurn（reply＋needs_clarification＋確定したrules[]）
"""

import json
from typing import Literal

from pydantic import BaseModel

from src import llm

from ._context import masters_context
from .base import GeminiAgent


class ChatRule(BaseModel):
    """会話で整理できた要望1件。"""

    source_text: str = ""          # 元の言い回し（どの要望か）
    summary: str = ""              # 一文要約（日本語）
    decision: Literal["queue", "memo", "reject", "ask_manager"] = "memo"
    suggested_type_name: str = ""  # queue: ルールのtype名（例 recurring_day_off / rest_after_late）
    recipe_json: str = ""          # queue: レシピのヒント / ask_manager: 「はい」のとき適用するレシピ
    reject_category: str = ""      # reject: 表現できない理由カテゴリ
    question: str = ""             # ask_manager: 実行前に責任者へ確認する質問


class ChatTurn(BaseModel):
    """対話1ターンの結果。reply は常に画面へ、rules は確定時のみ。"""

    reply: str = ""                    # 画面に出すAIの返答（質問 or まとめ）
    needs_clarification: bool = False  # さらに回答が必要か（true=会話継続）
    rules: list[ChatRule] = []         # 確定した要望群（needs_clarification=false のとき）


class ChatAgent(GeminiAgent):
    """要望を会話で確認し複数ルールに整理する（Flash・思考オフ）。"""

    model = llm.FLASH_MODEL
    schema = ChatTurn
    prompt_name = "chat_clarify"
    thinking_budget = 0

    def respond(self, requirements: str, scope: str = "person",
                history: list[dict] | None = None) -> ChatTurn:
        """要望・スコープ・これまでの会話を渡し、次の返答（質問 or 確定rules）を返す。"""
        return self.run_structured(
            requirements=requirements,
            scope="店舗全体" if scope == "store" else "本人",
            masters=masters_context(),
            history_json=json.dumps(history or [], ensure_ascii=False),
        )
