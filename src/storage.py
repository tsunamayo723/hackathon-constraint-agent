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


def find_pending_by_type(type_name: str) -> Optional[PendingTypeRequest]:
    """承認待ち（pending）の中から、同じ未知type名のリクエストを探す（クラスタリング用）。"""
    for r in _pending_queue.values():
        if r.status == "pending" and r.suggested_type_name == type_name:
            return r
    return None


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


# ── 制約の蓄積（シフト計算用） ──────────────────────────────────────
# ②の方針（翻訳済み制約）と ③の出勤希望（availability）を貯め、⑤で合算して解く。
# どちらも {"type": ..., "params": {...}} の dict 形式で保持する。

_policy_constraints: list[dict] = []   # ②由来（headcount/separate 等）。追記。
_availability: list[dict] = []         # ③由来（出勤希望CSV）。アップロードで置き換え。


def add_policy_constraints(items: list[dict]) -> None:
    """②の翻訳済み制約を追記する。"""
    _policy_constraints.extend(items)


def get_policy_constraints() -> list[dict]:
    return list(_policy_constraints)


def clear_policy_constraints() -> None:
    _policy_constraints.clear()


def save_availability(items: list[dict]) -> None:
    """③の出勤希望（availability制約）を置き換え保存する。"""
    global _availability
    _availability = list(items)


def get_availability() -> list[dict]:
    return list(_availability)


def clear_availability() -> None:
    global _availability
    _availability = []
