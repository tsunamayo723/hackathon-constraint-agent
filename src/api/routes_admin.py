"""
サイト管理者向けエンドポイント

未知タイプの承認キュー管理。
本番ではここに認可（管理者ロールチェック）を追加する。
"""

import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from src import llm
from src.agents import HandlerAgent
from src.models import PendingTypeRequest
from src.models.admin_queue import TestResult
from src.sandbox import run_handler_test
from src.storage import (
    get_pending_request,
    list_pending_requests,
    mark_shift_for_recalc,
    update_pending_request,
)

router = APIRouter(prefix="/admin", tags=["管理者承認"])

logger = logging.getLogger("uvicorn.error")


@router.get(
    "/pending-types",
    summary="承認待ちの未知タイプ一覧",
    description="サイト管理者が見る承認キュー。statusで絞り込みできます。",
)
def list_pending(
    status: Optional[str] = Query(
        default=None,
        description="絞り込み: pending / approved / rejected",
    ),
) -> list[PendingTypeRequest]:
    return list_pending_requests(status=status)


@router.get(
    "/pending-types/{req_id}",
    summary="承認待ちの詳細",
)
def get_pending(req_id: str) -> PendingTypeRequest:
    req = get_pending_request(req_id)
    if not req:
        raise HTTPException(status_code=404, detail=f"見つかりません: {req_id}")
    return req


@router.post(
    "/pending-types/{req_id}/generate",
    summary="AIにハンドラを生成させてテストする（L2フローの主役）",
    description=(
        "未知タイプに対し、Gemini Pro が\n"
        "- paramsスキーマ / ハンドラ関数コード / 例params / 自信度 / 懸念点\n"
        "を生成し、サンドボックス（別プロセス＋タイムアウト）でテストします。\n\n"
        "結果（生成コード・テスト合否）はこのリクエストに格納され、承認画面で確認できます。"
    ),
)
def generate_handler(req_id: str):
    req = get_pending_request(req_id)
    if not req:
        raise HTTPException(status_code=404, detail=f"見つかりません: {req_id}")
    if not llm.is_available():
        raise HTTPException(
            status_code=400,
            detail="Gemini未設定のため生成できません（.env の GEMINI_API_KEY を設定してください）。",
        )

    # ① Pro でハンドラ一式を生成
    try:
        gen = HandlerAgent().generate(req)
    except Exception as exc:
        logger.exception("ハンドラ生成に失敗")
        raise HTTPException(status_code=502, detail=f"ハンドラ生成に失敗しました: {exc}")

    # ② 例paramsを取り出してサンドボックスでテスト
    try:
        example_params = json.loads(gen.example_params_json) if gen.example_params_json else {}
    except json.JSONDecodeError:
        example_params = {}
    test = run_handler_test(gen.handler_code, example_params)

    # ③ 生成結果とテスト結果をリクエストに格納
    req.suggested_handler_code = gen.handler_code
    try:
        req.suggested_schema = json.loads(gen.param_schema_json) if gen.param_schema_json else None
    except json.JSONDecodeError:
        req.suggested_schema = {"raw": gen.param_schema_json}
    req.confidence = max(0.0, min(1.0, gen.confidence))
    req.concerns = gen.concerns
    req.tested_params = example_params
    req.test_results = TestResult(
        passed=bool(test.get("passed")),
        total=1,
        passed_count=1 if test.get("passed") else 0,
        failed_cases=[] if test.get("passed") else [test.get("message", "テスト失敗")],
        detail=test.get("message", ""),
    )
    update_pending_request(req)

    return {
        "結果": "生成・テスト完了",
        "タイプ名": req.suggested_type_name,
        "説明": gen.explanation,
        "テスト": "合格" if req.test_results.passed else f"不合格（{test.get('message','')}）",
        "自信度": req.confidence,
        "懸念点": req.concerns,
        "例params": example_params,
    }


@router.post(
    "/pending-types/{req_id}/approve",
    summary="承認: 新タイプを登録し、影響シフトを再計算キューへ",
    description=(
        "未知タイプを承認します。承認後は:\n\n"
        "1. 新typeをハンドラ辞書に永続登録（実装予定）\n"
        "2. `affected_shift_ids` に登録されているシフトを再計算キューに入れる\n"
        "3. ユーザーに「保留中だった要望が反映されました」と通知（実装予定）"
    ),
)
def approve_pending(req_id: str, reviewer_id: str = "admin", comment: str = ""):
    req = get_pending_request(req_id)
    if not req:
        raise HTTPException(status_code=404, detail=f"見つかりません: {req_id}")
    if req.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"このリクエストは既に処理済みです（現在: {req.status}）",
        )

    req.status = "approved"
    req.reviewed_at = datetime.now()
    req.reviewer_id = reviewer_id
    req.review_comment = comment
    update_pending_request(req)

    # 影響シフトを再計算キューへ
    for shift_id in req.affected_shift_ids:
        mark_shift_for_recalc(
            shift_id=shift_id,
            reason=f"未知タイプ '{req.suggested_type_name}' が承認されたため",
        )

    return {
        "結果": "承認しました",
        "タイプ名": req.suggested_type_name,
        "再計算キューに入れたシフト数": len(req.affected_shift_ids),
    }


@router.post(
    "/pending-types/{req_id}/reject",
    summary="却下: このタイプは対応しないことを記録",
)
def reject_pending(req_id: str, reviewer_id: str = "admin", comment: str = ""):
    req = get_pending_request(req_id)
    if not req:
        raise HTTPException(status_code=404, detail=f"見つかりません: {req_id}")
    if req.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"このリクエストは既に処理済みです（現在: {req.status}）",
        )

    req.status = "rejected"
    req.reviewed_at = datetime.now()
    req.reviewer_id = reviewer_id
    req.review_comment = comment
    update_pending_request(req)

    return {
        "結果": "却下しました",
        "タイプ名": req.suggested_type_name,
        "メッセージ": "ユーザーに「対応できません」と通知します（実装予定）",
    }
