"""
note解釈の分類ロジックのテスト（Gemini不要）

NoteAgentの応答（NoteResult）を手作りし、
  - _apply_note_results: ✅時間補正 / 🆕新ルール候補 / ⚠️未反映 の3分類
  - _register_note_pending: 承認キューへのクラスタリング登録・重複防止
だけを検証する。
"""

import pytest

import src.storage as storage
from src.agents.note_agent import NoteResult
from src.api.routes_setup import _apply_note_results, _register_note_pending


@pytest.fixture(autouse=True)
def _clean_pending_queue():
    """テストごとに承認キューを空にする（インメモリ共有のため）。"""
    storage._pending_queue.clear()
    yield
    storage._pending_queue.clear()


def _avail(person_id="p1", date="2026-11-01", start="09:00", end="22:00", note="備考"):
    return {
        "type": "availability",
        "params": {"person_id": person_id, "date": date, "start": start, "end": end, "note": note},
    }


def _items_from(availability):
    """endpointと同じ形で items / noted_idx を組み立てる（全行note付き前提）。"""
    items, noted_idx = [], []
    for i, c in enumerate(availability):
        p = c["params"]
        items.append({
            "index": len(items), "person_id": p["person_id"], "date": p["date"],
            "current_start": p["start"], "current_end": p["end"], "note": p["note"],
        })
        noted_idx.append(i)
    return items, noted_idx


# ── _apply_note_results: 3分類 ──────────────────────────────────────

def test_時間補正は枠に反映されてappliedになる():
    availability = [_avail(note="お迎えで17時まで")]
    items, noted_idx = _items_from(availability)
    results = [NoteResult(index=0, interpretable=True, new_end="17:00", note_summary="お迎えのため17時まで")]

    note_results, adjusted = _apply_note_results(availability, noted_idx, items, results)

    assert adjusted == 1
    assert availability[0]["params"]["end"] == "17:00"
    assert note_results[0]["status"] == "applied"
    assert "補正" in note_results[0]["summary"]


def test_新ルール候補はpendingになりタイプ名が付く():
    availability = [_avail(note="毎週水曜は習い事で入れません")]
    items, noted_idx = _items_from(availability)
    results = [NoteResult(
        index=0, interpretable=False,
        is_new_type=True, suggested_type_name="recurring_day_off",
        note_summary="毎週水曜は不可（繰り返し）",
    )]

    note_results, adjusted = _apply_note_results(availability, noted_idx, items, results)

    assert adjusted == 0
    assert note_results[0]["status"] == "pending"
    assert note_results[0]["suggested_type_name"] == "recurring_day_off"
    # 枠は変わらない
    assert availability[0]["params"]["end"] == "22:00"


def test_既知タイプ名の提案は誤検出として未反映扱い():
    availability = [_avail(note="Aさんと一緒は気まずい")]
    items, noted_idx = _items_from(availability)
    results = [NoteResult(
        index=0, interpretable=False,
        is_new_type=True, suggested_type_name="separate",  # 既知タイプ → ガード対象
    )]

    note_results, _ = _apply_note_results(availability, noted_idx, items, results)

    assert note_results[0]["status"] == "unreflected"
    assert "suggested_type_name" not in note_results[0]


def test_どちらでもない備考はunreflectedになる():
    availability = [_avail(note="よろしくお願いします")]
    items, noted_idx = _items_from(availability)
    results = [NoteResult(index=0, interpretable=False)]

    note_results, adjusted = _apply_note_results(availability, noted_idx, items, results)

    assert adjusted == 0
    assert note_results[0]["status"] == "unreflected"


def test_枠の外への補正は適用しない():
    availability = [_avail(start="09:00", end="22:00", note="23時までいけます")]
    items, noted_idx = _items_from(availability)
    results = [NoteResult(index=0, interpretable=True, new_end="23:00")]  # 枠を広げる方向 → 不可

    note_results, adjusted = _apply_note_results(availability, noted_idx, items, results)

    assert adjusted == 0
    assert availability[0]["params"]["end"] == "22:00"
    assert note_results[0]["status"] == "unreflected"


def test_時間補正と新ルールの両方を含む備考は両方扱いになる():
    availability = [_avail(note="今日は17時まで。あと毎週水曜はNGです")]
    items, noted_idx = _items_from(availability)
    results = [NoteResult(
        index=0, interpretable=True, new_end="17:00",
        is_new_type=True, suggested_type_name="recurring_day_off",
    )]

    note_results, adjusted = _apply_note_results(availability, noted_idx, items, results)

    assert adjusted == 1
    assert note_results[0]["status"] == "applied"  # 補正は効いている
    assert note_results[0]["suggested_type_name"] == "recurring_day_off"  # キュー登録もされる


# ── _register_note_pending: クラスタリング・重複防止 ────────────────

def _pending_entry(person_id, date, type_name, note="毎週水曜NG"):
    return {
        "person_id": person_id, "date": date, "note": note,
        "status": "pending", "summary": note, "suggested_type_name": type_name,
    }


def test_同じタイプ名は1件に集約される():
    note_results = [
        _pending_entry("p1", "2026-11-04", "recurring_day_off"),
        _pending_entry("p2", "2026-11-11", "recurring_day_off"),
        _pending_entry("p3", "2026-11-05", "exam_period", note="試験期間です"),
    ]

    registered = _register_note_pending(note_results)

    assert registered == 3
    pendings = storage.list_pending_requests(status="pending")
    assert len(pendings) == 2  # recurring_day_off と exam_period の2クラスタ

    recurring = storage.find_pending_by_type("recurring_day_off")
    assert recurring.occurrence_count == 2
    assert len(recurring.occurrences) == 2
    assert recurring.occurrences[0]["origin"] == "note"
    # 両エントリに同じpending_request_idが付与される
    assert note_results[0]["pending_request_id"] == note_results[1]["pending_request_id"]


def test_同じ備考の再解釈は二重登録しない():
    note_results = [_pending_entry("p1", "2026-11-04", "recurring_day_off")]

    assert _register_note_pending(note_results) == 1
    # 同じ内容でもう一度（＝解釈ボタンの押し直しを想定）
    assert _register_note_pending(list(note_results)) == 0

    recurring = storage.find_pending_by_type("recurring_day_off")
    assert recurring.occurrence_count == 1
    assert len(recurring.occurrences) == 1
