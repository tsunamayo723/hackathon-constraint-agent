"""
状態の保存口（storage）

各「バケット」（承認キュー / 制約の蓄積 / マスタ 等）の読み書き口をここに集約する。
保存先そのものは `persistence.py` の **StateStore**（差し替え可能な KVS）に委譲する:

- Supabaseキーが揃っていれば SupabaseStore（`app_state` テーブル）に永続化
- 無ければ InMemoryStore（プロセス内・再起動で消える。デモ1セッションは可）

これにより「保存先の切り替え」は `.env` にキーを入れるだけで済む（コード変更不要）。

※ 現状の配線範囲（T5土台）:
  - **_store 越し（永続化対象）**: shift_status / policy_constraints / availability /
    base_headcounts / dynamic_constraints / note_results / demo_meta / manager_questions
  - **据え置き（インメモリのまま）**: pending_queue / masters / frame
    → Pydantic の直列化（model_dump/model_validate）が要る＆テストが直接触るため、
      実DB接続フェーズ（T6とセット）で同様に _store 越しへ移す。下部の TODO 参照。
"""

from typing import Optional

from src.models import Frame, Masters, PendingTypeRequest
from src.persistence import get_store

# 保存口（差し替え可能な StateStore）。キーの有無で Supabase / インメモリを自動選択。
_store = get_store()


# ── 承認キュー（pending_queue） ─────────────────────────────────────
# TODO(T5/T6・実DB接続フェーズ): PendingTypeRequest を model_dump(mode="json") で
#   直列化して _store 越しへ移す。現状はインメモリ（テストが storage._pending_queue を直接触る）。
_pending_queue: dict[str, PendingTypeRequest] = {}


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


# ── シフトの再計算フラグ（shift_status） ────────────────────────────

def mark_shift_for_recalc(shift_id: str, reason: str) -> None:
    statuses = dict(_store.get("shift_status", {}))
    statuses[shift_id] = {"recalculation_needed": True, "reason": reason}
    _store.set("shift_status", statuses)


def get_shift_status(shift_id: str) -> dict:
    return _store.get("shift_status", {}).get(shift_id, {"recalculation_needed": False})


# ── マスタ（人/役職/ポジション/スキル） ─────────────────────────────
# TODO(T5/T6): Masters を model_dump 経由で _store へ。現状インメモリ（テストが直接触る）。
_masters: Optional[Masters] = None


def save_masters(masters: Masters) -> None:
    global _masters
    _masters = masters


def get_masters() -> Optional[Masters]:
    return _masters


# ── 営業情報（frame: 期間・営業時間・ポリシー） ─────────────────────
# TODO(T5/T6): Frame を model_dump 経由で _store へ。現状インメモリ（テストが直接触る）。
_frame: Optional[Frame] = None


def save_frame(frame: Frame) -> None:
    global _frame
    _frame = frame


def get_frame() -> Optional[Frame]:
    return _frame


# ── 制約の蓄積（シフト計算用） ──────────────────────────────────────
# ②の方針（翻訳済み制約）と ③の出勤希望（availability）を貯め、⑤で合算して解く。
# どちらも {"type": ..., "params": {...}} の dict 形式（JSONネイティブ）なので _store に直接置ける。

def add_policy_constraints(items: list[dict]) -> None:
    """②の翻訳済み制約を追記する。"""
    _store.set("policy_constraints", _store.get("policy_constraints", []) + list(items))


def get_policy_constraints() -> list[dict]:
    return list(_store.get("policy_constraints", []))


def clear_policy_constraints() -> None:
    _store.set("policy_constraints", [])


def save_availability(items: list[dict]) -> None:
    """③の出勤希望（availability制約）を置き換え保存する。"""
    _store.set("availability", list(items))


def get_availability() -> list[dict]:
    return list(_store.get("availability", []))


def clear_availability() -> None:
    _store.set("availability", [])


def save_base_headcounts(items: list[dict]) -> None:
    """①の必要人数（headcount制約）を置き換え保存する。"""
    _store.set("base_headcounts", list(items))


def get_base_headcounts() -> list[dict]:
    return list(_store.get("base_headcounts", []))


# ── 動的タイプの制約インスタンス（承認された新typeの「材料」） ───────
# 承認時、ParamsAgent が各人の原文を params化したものを貯める。
# 各要素: {"type", "params": {...}, "source": {person_id, date, source_text}}
# run-stored がこれをソルバーに渡す（②方針・③希望と並ぶ第4の制約源）。
# ★再起動で消えて一番困るのがここ（L2の成果）→ _store 越しで永続化対象にする。

def save_dynamic_constraints(items: list[dict]) -> None:
    """承認された新typeの制約インスタンスを追記する。"""
    _store.set("dynamic_constraints", _store.get("dynamic_constraints", []) + list(items))


def get_dynamic_constraints() -> list[dict]:
    return list(_store.get("dynamic_constraints", []))


def clear_dynamic_constraints() -> None:
    _store.set("dynamic_constraints", [])


# ── 備考(note)の解釈結果（✅適用 / ⚠️未反映） ───────────────────────
# 各要素: {person_id, date, note, applied(bool), summary}

def save_note_results(items: list[dict]) -> None:
    """interpret-notes の分類結果を置き換え保存する。"""
    _store.set("note_results", list(items))


def get_note_results() -> list[dict]:
    return list(_store.get("note_results", []))


def clear_note_results() -> None:
    _store.set("note_results", [])


# ── 投入済みデモデータのメタ情報 ─────────────────────────────────────
# load-demo で投入したパターンの meta（label/frame/demo_submitter 等）を覚えておく。
# 提出者UIの「デモの希望を読み込む」で overall_note を返すのに使う。

def save_demo_meta(meta: Optional[dict]) -> None:
    """投入したデモパターンの meta を保存する（CSV手動投入時は None でクリア）。"""
    _store.set("demo_meta", meta)


def get_demo_meta() -> Optional[dict]:
    return _store.get("demo_meta", None)


# ── 責任者への質問（需要に依存する要望の保留） ──────────────────────
# 「混みそうなら入ります」等を即拒否せず、実行前に責任者へ確認する。
# 各要素: {id, person_id, question, summary, recipe(はいの時のレシピ), status, answer}

def add_manager_question(q: dict) -> None:
    _store.set("manager_questions", _store.get("manager_questions", []) + [q])


def list_manager_questions(status: Optional[str] = None) -> list[dict]:
    items = list(_store.get("manager_questions", []))
    if status:
        return [q for q in items if q.get("status") == status]
    return items


def get_manager_question(qid: str) -> Optional[dict]:
    return next((q for q in _store.get("manager_questions", []) if q.get("id") == qid), None)


def clear_manager_questions() -> None:
    _store.set("manager_questions", [])
