"""
サイト管理者向けエンドポイント

未知タイプの承認キュー管理。
本番ではここに認可（管理者ロールチェック）を追加する。
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from src.models import PendingTypeRequest
from src.storage import (
    get_pending_request,
    list_pending_requests,
    mark_shift_for_recalc,
    update_pending_request,
)

router = APIRouter(prefix="/admin", tags=["管理者承認"])


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
