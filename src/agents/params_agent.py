"""
ParamsAgent — 承認された新タイプの「原文 → params」変換（Flash・思考オフ）

L2ループの「材料供給」役。
承認時、新タイプのハンドラ関数は登録されるが、各人の要望を表す
**params（材料）** がまだ無い。このエージェントが、ハンドラ生成時に作られた
**example_params（見本）と同じ形式**に合わせて、各人の原文を params dict に変換する。

「見本に形式を合わせる」のが肝。ハンドラ生成側と同じ見本を参照することで、
ハンドラが期待するキー・値の形（例: weekday を "wednesday" か 3 か）に必ず揃う。

同じタイプの全 occurrence を1回のバッチ呼び出しで変換する（コスト最小）。

入力: type_name, param_schema_json, example_params_json,
      occurrences=[{index, person_id, date, source_text}, ...]
出力: [ParamItem(index, params_json), ...]
"""

import json

from pydantic import BaseModel

from src import llm

from .base import GeminiAgent

# 1回のGemini呼び出しで変換する件数（同typeの人数は通常少ないので大きめでも安定）
CHUNK_SIZE = 40


class ParamItem(BaseModel):
    index: int
    params_json: str   # その occurrence の params（JSONオブジェクトの文字列）


class _ParamBatch(BaseModel):
    items: list[ParamItem]


class ParamsAgent(GeminiAgent):
    """原文を、ハンドラが期待する params に変換するエージェント（Flash・思考オフ）。"""

    model = llm.FLASH_MODEL
    schema = _ParamBatch
    prompt_name = "params"
    thinking_budget = 0

    def convert(
        self,
        type_name: str,
        param_schema_json: str,
        example_params_json: str,
        occurrences: list[dict],
    ) -> list[ParamItem]:
        """occurrence のリストを受け、params化結果を返す（内部でチャンク分割して呼ぶ）。"""
        results: list[ParamItem] = []
        for start in range(0, len(occurrences), CHUNK_SIZE):
            chunk = occurrences[start:start + CHUNK_SIZE]
            batch: _ParamBatch = self.run_structured(
                type_name=type_name,
                param_schema_json=param_schema_json,
                example_params_json=example_params_json,
                occurrences_json=json.dumps(chunk, ensure_ascii=False),
            )
            results.extend(batch.items)
        return results
