"""
パーサ関連のエンドポイント
"""

from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Body, HTTPException

from src import llm
from src.models import (
    ParserInput,
    ParserOutput,
    PendingTypeRequest,
)
from src.parser_stub import parse as parse_stub
from src.agents import parse as parse_gemini
from src.storage import (
    add_pending_request,
    add_policy_constraints,
    find_pending_by_type,
    update_pending_request,
)

router = APIRouter(prefix="/parser", tags=["パーサ"])


# サーバーログに出す（uvicornのロガーに乗せると同じ場所に表示される）
import logging

logger = logging.getLogger("uvicorn.error")


def _run_parse(input_data: ParserInput) -> ParserOutput:
    """APIキーがあれば本物のGemini、無ければスタブで解析する。"""
    if not llm.is_available():
        return parse_stub(input_data)

    try:
        return parse_gemini(input_data)
    except Exception as exc:  # Gemini呼び出し失敗は握りつぶさず、ログ＋分かりやすいメッセージで返す
        # 完全なトレースバックをサーバーログに出力（原因調査用）
        logger.exception("Geminiパースに失敗しました")
        msg = str(exc)
        if "RESOURCE_EXHAUSTED" in msg or "429" in msg:
            detail = (
                "Geminiの利用枠／クレジットが不足しています（429）。"
                "Google AI Studio で請求・クレジットを確認してください。"
                "（クレジットが復活するまではキーを外せばスタブで動作します）"
            )
        elif "PERMISSION_DENIED" in msg or "API_KEY" in msg or "401" in msg or "403" in msg:
            detail = "APIキーが無効か権限がありません。.env の GEMINI_API_KEY を確認してください。"
        else:
            detail = f"Geminiでの解析に失敗しました: {exc}"
        raise HTTPException(status_code=502, detail=detail)


_parser_examples = {
    "① 既知タイプのみ": {
        "summary": "「ランチに4人」だけ → translatedに1件、untranslatedは空",
        "value": {"input_text": "ランチに4人入れて。"},
    },
    "② 既知 + 未知の混在（デモの主役）": {
        "summary": "「10時から入れます。毎週水曜は習い事で休みです。」",
        "value": {
            "input_text": "ランチに4人入れて。毎週水曜は習い事で休みです。",
            "person_id": "p1",
        },
    },
    "③ 3種類の未知タイプを一度に": {
        "summary": "デモシナリオ3つを1リクエストで",
        "value": {
            "input_text": (
                "毎週水曜は習い事があって入れません。"
                "22時以降のシフトは月3回までにしてください。"
                "12/10〜20が試験期間なので極力入れないで。"
            ),
            "person_id": "p1",
        },
    },
}


@router.post(
    "/parse",
    summary="自然言語をパースして既知/未知に振り分ける",
    description=(
        "スタッフが入力した自然言語を解析し、以下の2つに振り分けて返します。\n\n"
        "- **translated**: 既知16タイプに翻訳できた制約一覧\n"
        "- **untranslated**: 翻訳できなかった文言（元の自然言語のまま保持）\n\n"
        "未翻訳項目は自動的に**サイト管理者の承認キューに登録**されます。\n"
        "ユーザー画面では「✅ 反映済み」「⏳ 確認中」として両方を表示する設計です。\n\n"
        "※ GEMINI_API_KEY を設定すると Gemini Flash で解析します。"
        "未設定の場合はキーワードマッチのスタブにフォールバックします。"
    ),
)
def parse_input(body: dict = Body(openapi_examples=_parser_examples)) -> ParserOutput:
    input_data = ParserInput.model_validate(body)
    output = _run_parse(input_data)

    # 翻訳できた制約はシフト計算用に蓄積（⑤で出勤希望と合算して解く）
    add_policy_constraints([
        {"type": t.constraint.type, "params": t.constraint.params.model_dump(mode="json")}
        for t in output.translated
    ])

    # 未翻訳項目を管理者キューに登録（同じ未知type名はクラスタリングして1件に集約）
    for untrans in output.untranslated:
        type_name = untrans.suggested_type_name or "unknown"

        # 出どころの構造化記録（承認後のparams化=T2で「誰の要望か」を引くため）
        occurrence = {
            "person_id": input_data.person_id, "date": None,
            "source_text": untrans.source_text, "origin": "policy",
        }

        # type名が具体的なら、既存の承認待ちにまとめる（"unknown"はまとめない）
        existing = find_pending_by_type(type_name) if type_name != "unknown" else None

        if existing is not None:
            existing.source_texts.append(untrans.source_text)
            existing.occurrence_count += 1
            existing.occurrences.append(occurrence)
            # 見解類はまだ空なら補完（最初に付いたものを尊重）
            if not existing.summary and untrans.summary:
                existing.summary = untrans.summary
                existing.ai_assessment = untrans.ai_assessment
                existing.review_points = untrans.review_points
            update_pending_request(existing)
            untrans.pending_request_id = existing.id
        else:
            req_id = f"req_{uuid4().hex[:8]}"
            untrans.pending_request_id = req_id
            add_pending_request(PendingTypeRequest(
                id=req_id,
                suggested_type_name=type_name,
                source_texts=[untrans.source_text],
                occurrence_count=1,
                occurrences=[occurrence],
                summary=untrans.summary,
                ai_assessment=untrans.ai_assessment,
                review_points=untrans.review_points,
                confidence=0.0,  # AI生成前なので0
                created_at=datetime.now(),
            ))

    return output
