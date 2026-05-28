"""
パーサのスタブ実装

本番では Gemini Flash を呼ぶが、現段階ではフロー確認用に
単純なキーワードマッチで「既知/未知」を振り分ける。

将来 Gemini に差し替えるときも、入出力スキーマ（ParserInput/ParserOutput）は
変えない設計。
"""

from datetime import datetime

from src.models import (
    HeadcountRequirement,
    ParserInput,
    ParserOutput,
    TranslatedConstraint,
    UntranslatedConstraint,
)


def parse(input_data: ParserInput) -> ParserOutput:
    """
    自然言語入力を翻訳済み/未翻訳に振り分ける。

    現状はスタブ:
      - 「ランチ」「ホール」「4人」を含む文 → headcount_requirement に翻訳
      - 「毎週」「曜日名」を含む文 → 未知タイプ（recurring_day_off候補）
      - 「22時以降」「月3回」を含む文 → 未知タイプ（max_late_shift_count候補）
      - 「試験期間」を含む文 → 未知タイプ（exam_period候補）
      - それ以外で句点で区切られた文 → 未知タイプ（type不明）
    """
    text = input_data.input_text
    sentences = [s.strip() for s in text.replace("。", "。|").split("|") if s.strip()]

    translated: list[TranslatedConstraint] = []
    untranslated: list[UntranslatedConstraint] = []

    for sentence in sentences:
        # ── 既知タイプの簡易検出 ──────────────────────────────
        if "ランチ" in sentence and ("人" in sentence or "名" in sentence):
            # 例: "ランチに4人入れて"
            count = _extract_count(sentence)
            translated.append(TranslatedConstraint(
                constraint=HeadcountRequirement(params={
                    "slot_label": "ランチ",
                    "time_start": "11:00",
                    "time_end": "14:00",
                    "position_id": "pos_hall",
                    "count": count or 4,
                }),
                source_text=sentence,
                confidence=0.85,
            ))
            continue

        # ── 未知タイプの簡易検出（デモシナリオ3種） ────────
        if "毎週" in sentence or "毎日" in sentence:
            untranslated.append(UntranslatedConstraint(
                source_text=sentence,
                suggested_type_name="recurring_day_off",
                reason="毎週○曜日のような繰り返しパターンは現在AIが対応ルールを準備中です",
            ))
            continue

        if "22時" in sentence or "深夜" in sentence or "月" in sentence and "回" in sentence:
            untranslated.append(UntranslatedConstraint(
                source_text=sentence,
                suggested_type_name="max_late_shift_count",
                reason="月単位の回数上限ルールは現在AIが対応ルールを準備中です",
            ))
            continue

        if "試験" in sentence or "テスト期間" in sentence:
            untranslated.append(UntranslatedConstraint(
                source_text=sentence,
                suggested_type_name="exam_period",
                reason="期間指定の出勤最小化ルールは現在AIが対応ルールを準備中です",
            ))
            continue

        # ── どれでもないが文として意味がありそうなもの ──────
        if len(sentence) >= 5:
            untranslated.append(UntranslatedConstraint(
                source_text=sentence,
                suggested_type_name=None,
                reason="この要望はAIが解釈できませんでした。管理者が内容を確認します",
            ))

    return ParserOutput(
        input_text=text,
        translated=translated,
        untranslated=untranslated,
        parsed_at=datetime.now(),
    )


def _extract_count(text: str) -> int | None:
    """文中の数字を1つ抽出"""
    import re
    m = re.search(r"(\d+)", text)
    return int(m.group(1)) if m else None
