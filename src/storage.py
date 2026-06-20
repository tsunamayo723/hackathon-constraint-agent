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


def clear_pending_requests() -> None:
    """承認キューを空にする（デモデータ投入時のリセット用）。"""
    _pending_queue.clear()


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
_base_headcounts: list[dict] = []      # ①由来（必要人数フォーム）。送信で置き換え。


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


def save_base_headcounts(items: list[dict]) -> None:
    """①の必要人数（headcount制約）を置き換え保存する。"""
    global _base_headcounts
    _base_headcounts = list(items)


def get_base_headcounts() -> list[dict]:
    return list(_base_headcounts)


# ── 動的タイプの制約インスタンス（承認された新typeの「材料」） ───────
# 承認時、ParamsAgent が各人の原文を params化したものを貯める。
# 各要素: {"type", "params": {...}, "source": {person_id, date, source_text}}
# run-stored がこれをソルバーに渡す（②方針・③希望と並ぶ第4の制約源）。
_dynamic_constraints: list[dict] = []


def save_dynamic_constraints(items: list[dict]) -> None:
    """承認された新typeの制約インスタンスを追記する。"""
    _dynamic_constraints.extend(items)


def get_dynamic_constraints() -> list[dict]:
    return list(_dynamic_constraints)


def clear_dynamic_constraints() -> None:
    _dynamic_constraints.clear()


# ── 備考(note)の解釈結果（✅適用 / ⚠️未反映） ───────────────────────
# 各要素: {person_id, date, note, applied(bool), summary}
_note_results: list[dict] = []


def save_note_results(items: list[dict]) -> None:
    """interpret-notes の分類結果を置き換え保存する。"""
    global _note_results
    _note_results = list(items)


def get_note_results() -> list[dict]:
    return list(_note_results)


def clear_note_results() -> None:
    global _note_results
    _note_results = []


# ── 投入済みデモデータのメタ情報 ─────────────────────────────────────
# load-demo で投入したパターンの meta（label/frame/demo_submitter 等）を覚えておく。
# 提出者UIの「デモの希望を読み込む」で overall_note を返すのに使う。
_demo_meta: Optional[dict] = None


def save_demo_meta(meta: Optional[dict]) -> None:
    """投入したデモパターンの meta を保存する（CSV手動投入時は None でクリア）。"""
    global _demo_meta
    _demo_meta = meta


def get_demo_meta() -> Optional[dict]:
    return _demo_meta


# ── 責任者への質問（需要に依存する要望の保留） ──────────────────────
# 「混みそうなら入ります」等を即拒否せず、実行前に責任者へ確認する。
# 各要素: {id, person_id, question, summary, recipe(はいの時のレシピ), status, answer}
_manager_questions: list[dict] = []


def add_manager_question(q: dict) -> None:
    _manager_questions.append(q)


def list_manager_questions(status: Optional[str] = None) -> list[dict]:
    if status:
        return [q for q in _manager_questions if q.get("status") == status]
    return list(_manager_questions)


def get_manager_question(qid: str) -> Optional[dict]:
    return next((q for q in _manager_questions if q.get("id") == qid), None)


def clear_manager_questions() -> None:
    _manager_questions.clear()
