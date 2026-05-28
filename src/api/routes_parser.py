"""
パーサ関連のエンドポイント
"""

from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Body

from src.models import (
    ParserInput,
    ParserOutput,
    PendingTypeRequest,
)
from src.parser_stub import parse
from src.storage import add_pending_request

router = APIRouter(prefix="/parser", tags=["パーサ"])


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
        "※ 現状はGemini未接続のスタブ実装です（キーワードマッチで判定）"
    ),
)
def parse_input(body: dict = Body(openapi_examples=_parser_examples)) -> ParserOutput:
    input_data = ParserInput.model_validate(body)
    output = parse(input_data)

    # 未翻訳項目を管理者キューに登録
    for untrans in output.untranslated:
        req_id = f"req_{uuid4().hex[:8]}"
        untrans.pending_request_id = req_id

        add_pending_request(PendingTypeRequest(
            id=req_id,
            suggested_type_name=untrans.suggested_type_name or "unknown",
            source_texts=[untrans.source_text],
            occurrence_count=1,
            confidence=0.0,  # AI生成前なので0
            created_at=datetime.now(),
        ))

    return output
