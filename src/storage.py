"""
インメモリのモックストレージ（デモ・開発用）

本番では Supabase に置き換わるが、ハッカソンのフロー確認段階では
プロセス内辞書で十分。再起動するとデータは消える前提。
"""

from typing import Optional

from src.models import PendingTypeRequest

# id → リクエスト
_pending_queue: dict[str, PendingTypeRequest] = {}

# シフトID → 再計算が必要かのフラグ（簡易版）
_shift_status: dict[str, dict] = {}


def add_pending_request(req: PendingTypeRequest) -> None:
    _pending_queue[req.id] = req


def list_pending_requests(status: Optional[str] = None) -> list[PendingTypeRequest]:
    items = list(_pending_queue.values())
    if status:
        items = [r for r in items if r.status == status]
    return items


def get_pending_request(req_id: str) -> Optional[PendingTypeRequest]:
    return _pending_queue.get(req_id)


def update_pending_request(req: PendingTypeRequest) -> None:
    _pending_queue[req.id] = req


def mark_shift_for_recalc(shift_id: str, reason: str) -> None:
    _shift_status[shift_id] = {
        "recalculation_needed": True,
        "reason": reason,
    }


def get_shift_status(shift_id: str) -> dict:
    return _shift_status.get(shift_id, {"recalculation_needed": False})
