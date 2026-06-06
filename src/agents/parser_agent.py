"""
ParserAgent — 自然言語 → 制約JSON 変換（Flashモデル）

役割（CLAUDE.md ①パーサ）:
  - 入力文を「既知16タイプ」に翻訳できるか判定
  - 翻訳できたもの   → translated（type + params）
  - 翻訳できないもの → untranslated（元の文言・推定type名・理由を保持）

信頼性のための工夫:
  - Geminiには「ゆるい中間フォーマット」で出させ、params の厳密検証は
    Python 側（Pydantic Constraint）で行う。AIの細かなJSONブレを吸収する。
  - 確信度が低い項目は untranslated 扱い（分かったフリをしない）。

プロンプトは prompts/parser.txt（テキストで編集可能）。
"""

import json
from datetime import datetime

from pydantic import BaseModel, TypeAdapter, ValidationError

from src import llm
from src.models import (
    Constraint,
    KNOWN_TYPES,
    ParserInput,
    ParserOutput,
    TranslatedConstraint,
    UntranslatedConstraint,
)

from .base import GeminiAgent

# 確信度がこれ未満なら「翻訳できなかった」扱いにする（分かったフリ防止）
_MIN_CONFIDENCE = 0.5

_constraint_adapter = TypeAdapter(Constraint)


# ── Geminiに出させる中間フォーマット（ゆるめ） ─────────────────────


class _ParsedItem(BaseModel):
    source_text: str          # この項目の元になった入力の一部
    is_known: bool            # 既知16タイプに当てはまるか
    type_name: str            # 既知ならtype名 / 未知なら推定の新type名
    params_json: str          # 既知のときの params をJSON文字列で（未知なら ""）
    confidence: float         # 0.0〜1.0
    reason: str               # 未知の理由 / 既知なら補足（空でも可）


class _ParseResult(BaseModel):
    items: list[_ParsedItem]


class ParserAgent(GeminiAgent):
    """自然言語の要望を既知/未知に振り分けるエージェント（Flash）。"""

    model = llm.FLASH_MODEL
    schema = _ParseResult
    prompt_name = "parser"

    def parse(self, input_data: ParserInput) -> ParserOutput:
        result: _ParseResult = self.run_structured(
            input_text=input_data.input_text,
            person_id=input_data.person_id or "（指定なし）",
        )

        translated: list[TranslatedConstraint] = []
        untranslated: list[UntranslatedConstraint] = []

        for item in result.items:
            # ① 確信度が低い → 翻訳できなかった扱い
            if item.confidence < _MIN_CONFIDENCE:
                untranslated.append(UntranslatedConstraint(
                    source_text=item.source_text,
                    suggested_type_name=item.type_name or None,
                    reason=item.reason or "確信度が低いため、管理者が確認します",
                ))
                continue

            # ② 既知タイプ → params を厳密検証してから採用
            if item.is_known and item.type_name in KNOWN_TYPES:
                constraint = _try_build_constraint(item.type_name, item.params_json)
                if constraint is not None:
                    translated.append(TranslatedConstraint(
                        constraint=constraint,
                        source_text=item.source_text,
                        confidence=item.confidence,
                    ))
                    continue
                untranslated.append(UntranslatedConstraint(
                    source_text=item.source_text,
                    suggested_type_name=item.type_name,
                    reason="ルールの形式が不完全だったため、管理者が確認します",
                ))
                continue

            # ③ 未知タイプ
            untranslated.append(UntranslatedConstraint(
                source_text=item.source_text,
                suggested_type_name=item.type_name or None,
                reason=item.reason or "未対応のルールのため、管理者が対応を準備します",
            ))

        return ParserOutput(
            input_text=input_data.input_text,
            translated=translated,
            untranslated=untranslated,
            parsed_at=datetime.now(),
        )


def _try_build_constraint(type_name: str, params_json: str):
    """type名 + params(JSON文字列) を Pydantic で検証し、成功すれば Constraint を返す。"""
    try:
        params = json.loads(params_json) if params_json else {}
    except json.JSONDecodeError:
        return None
    try:
        return _constraint_adapter.validate_python({"type": type_name, "params": params})
    except ValidationError:
        return None


# 既定エージェントのシングルトンと、関数版の入口（呼ぶ側はこれだけ知ればよい）
_default_agent = ParserAgent()


def parse(input_data: ParserInput) -> ParserOutput:
    return _default_agent.parse(input_data)
