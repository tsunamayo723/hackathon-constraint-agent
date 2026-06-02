"""
インメモリのモックストレージ（デモ・開発用）

本番では Supabase に置き換わるが、ハッカソンのフロー確認段階では
プロセス内辞書で十分。再起動するとデータは消える前提。
"""

from typing import Optional

from src.models import Frame, Masters, PendingTypeRequest

# id → リクエスト
_pending_queue: dict[str, PendingTypeRequest] = {}

# シフトID → 再計算が必要かのフラグ（簡易版）
_shift_status: dict[str, dict] = {}

# セットアップ済みのマスタ・営業情報（デモでは単一店舗想定なので1件のみ保持）
_masters: Optional[Masters] = None
_frame: Optional[Frame] = None


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


# ── マスタ（人/役職/ポジション/スキル） ─────────────────────────────

def save_masters(masters: Masters) -> None:
    global _masters
    _masters = masters


def get_masters() -> Optional[Masters]:
    return _masters


# ── 営業情報（frame: 期間・営業時間・ポリシー） ─────────────────────

def save_frame(frame: Frame) -> None:
    global _frame
    _frame = frame


def get_frame() -> Optional[Frame]:
    return _frame
