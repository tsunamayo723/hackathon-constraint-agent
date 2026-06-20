"""
提出者プレビュー（/submit/preview）のテスト（Gemini不要・ソルバーを実際に回す）

- 備考レシピ（毎週水曜NG）で本人の水曜が after で消える（personal.diff.removed）
- 控えのスタッフが居れば、本人が水曜を抜けても店舗の必要人数は満たせる（store.after_ok）
- 備考レシピなし → before==after・note_applied=False
- 効かないレシピ（対象日なし）→ note_applied=False
- 未登録/存在しないスタッフのエラー
"""

import pytest
from fastapi.testclient import TestClient

import src.handlers as handlers_mod
import src.storage as storage
from src.api.main import app

client = TestClient(app)

# 2026-11-02(月)〜11-08(日)。11-04が水曜(weekday=2)。
WEEK = [f"2026-11-0{d}" for d in range(2, 9)]  # 02..08
WED = "2026-11-04"
MASTERS = {
    "persons": [{"id": "p1", "name": "本人"}, {"id": "p2", "name": "控え"}],
    "positions": [{"id": "pos_hall", "name": "ホール"}],
    "roles": [], "skills": [],
}
FRAME = {
    "period": {"start": "2026-11-02", "end": "2026-11-08"},
    "operating_window": {"open": "11:00", "close": "12:00", "slot_minutes": 60},
    "policy_mode": "balance",
}
WISHES = [{"date": d, "start": "11:00", "end": "12:00"} for d in WEEK]
FORBID_WED = {"operation": "forbid", "who": "person",
              "when": "weekday", "weekday": 2, "band": "all_day"}


@pytest.fixture(autouse=True)
def _clean():
    for fn in (storage._pending_queue.clear, storage.clear_dynamic_constraints,
               storage.clear_availability, storage.clear_policy_constraints,
               handlers_mod._DYNAMIC_HANDLERS.clear):
        fn()
    # マスタ/営業情報は専用クリア関数が無いのでモジュール変数を直接リセット（テスト独立性）
    storage._masters = None
    storage._frame = None
    storage.save_base_headcounts([])
    yield
    storage.clear_availability()
    storage.clear_dynamic_constraints()


def _setup(persons=MASTERS, with_bench=False):
    assert client.post("/setup/masters", json=persons).status_code == 200
    assert client.post("/setup/frame", json=FRAME).status_code == 200
    hc = [{"slot_label": "L", "time_start": "11:00", "time_end": "12:00",
           "position_id": "pos_hall", "count": 1}]
    assert client.post("/setup/headcounts", json=hc).status_code == 200
    if with_bench:
        # 控え p2 を全日出勤可能として事前登録（店舗側のデータ）
        bench = [{"person_id": "p2", "date": d, "start": "11:00", "end": "12:00"} for d in WEEK]
        assert client.post("/setup/desired-shifts", json=bench).status_code == 200


def test_preview_forbid_removes_wednesday():
    # 本人 p1 のみ。水曜NGにすると after では水曜の割当が消える。
    _setup({"persons": [{"id": "p1", "name": "本人"}], "positions": MASTERS["positions"],
            "roles": [], "skills": []})
    r = client.post("/submit/preview", json={
        "person_id": "p1", "type_name": "recurring_day_off",
        "wishes": WISHES, "recipe": FORBID_WED,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["note_applied"] is True

    after_dates = {a["date"] for a in body["personal"]["after"]}
    before_dates = {a["date"] for a in body["personal"]["before"]}
    assert WED in before_dates          # 考慮なしでは水曜に入っていた
    assert WED not in after_dates       # 考慮ありでは水曜が消えた
    removed_dates = {a["date"] for a in body["personal"]["diff"]["removed"]}
    assert WED in removed_dates


def test_preview_store_stays_covered_with_bench():
    # 控え p2 が居れば、本人が水曜を抜けても店舗の必要人数は満たせる。
    _setup(with_bench=True)
    r = client.post("/submit/preview", json={
        "person_id": "p1", "type_name": "recurring_day_off",
        "wishes": WISHES, "recipe": FORBID_WED,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["note_applied"] is True
    # 本人は水曜に入っていない
    assert WED not in {a["date"] for a in body["personal"]["after"]}
    # 店舗は after でも充足（控えが水曜を埋める）
    assert body["store"]["after_ok"] is True
    assert body["after"]["coverage_score"] == 100.0


def test_preview_no_recipe_means_no_change():
    _setup()
    r = client.post("/submit/preview", json={
        "person_id": "p1", "wishes": WISHES, "recipe": None,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["note_applied"] is False
    assert body["before"]["assignments"] == body["after"]["assignments"]


def test_preview_ineffective_recipe_not_applied():
    # 当たる曜日が無い（weekday=9）→ 制約が生まれない → note_applied=False
    _setup()
    r = client.post("/submit/preview", json={
        "person_id": "p1", "wishes": WISHES,
        "recipe": {"operation": "forbid", "who": "person",
                   "when": "weekday", "weekday": 9, "band": "all_day"},
    })
    assert r.status_code == 200
    body = r.json()
    assert body["note_applied"] is False
    assert body["before"]["assignments"] == body["after"]["assignments"]


def test_preview_requires_setup():
    # マスタ未登録 → 404
    r = client.post("/submit/preview", json={"person_id": "p1", "wishes": [], "recipe": None})
    assert r.status_code == 404


def test_preview_unknown_person():
    _setup()
    r = client.post("/submit/preview", json={"person_id": "zzz", "wishes": [], "recipe": None})
    assert r.status_code == 422
