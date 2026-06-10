"""
NoteAgent — 出勤希望の「日ごと備考(note)」をバッチ解釈（Flash・思考オフ）

コスト対策で **まとめて数回の呼び出し** で処理する（1件ずつ呼ばない）。
各備考を3つに分類する:
  A: その日の時間補正（new_start/new_end で出勤可能枠を狭める）
  B: 新しいルール候補（毎週○曜NG等。is_new_type=true → 管理者の承認キューへ）
  C: どちらでもない（申し送りとして可視化）

入力: [{index, person_id, date, current_start, current_end, note}, ...]
出力: [{index, interpretable, new_start, new_end, is_new_type, suggested_type_name, note_summary}, ...]
"""

import json

from pydantic import BaseModel

from src import llm

from .base import GeminiAgent

# 1回のGemini呼び出しで処理する件数（多すぎると不安定・出力が長くなるため分割）
CHUNK_SIZE = 40


class NoteResult(BaseModel):
    index: int
    interpretable: bool
    new_start: str | None = None   # "HH:MM" or null（変更なし）
    new_end: str | None = None
    is_new_type: bool = False              # 「仕組みとしてのルール」＝新タイプ候補か
    suggested_type_name: str | None = None  # 新タイプ名の提案（例: recurring_day_off）
    note_summary: str = ""


class _NoteBatch(BaseModel):
    items: list[NoteResult]


class NoteAgent(GeminiAgent):
    """備考をバッチ解釈するエージェント（Flash・思考オフ）。"""

    model = llm.FLASH_MODEL
    schema = _NoteBatch
    prompt_name = "note"
    thinking_budget = 0

    def interpret(self, items: list[dict]) -> list[NoteResult]:
        """note付き行のリストを受け、解釈結果を返す（内部でチャンク分割して呼ぶ）。"""
        results: list[NoteResult] = []
        for start in range(0, len(items), CHUNK_SIZE):
            chunk = items[start:start + CHUNK_SIZE]
            batch: _NoteBatch = self.run_structured(
                items_json=json.dumps(chunk, ensure_ascii=False)
            )
            results.extend(batch.items)
        return results
