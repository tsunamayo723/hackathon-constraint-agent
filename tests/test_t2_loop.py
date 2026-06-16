"""
T2（承認→制約化→自動再計算）のテスト（Gemini不要）

ParamsAgent はモック化し、L2ループの「材料供給→反映→差分」の配線だけを検証する:
  - dynamic_constraints が solve に効く（recurring_day_off 風ハンドラで水曜が消える）
  - _paramize_and_store が occurrence→dynamic_constraints を正しく保存する（ParamsAgentモック）
  - run-stored が dynamic_constraints を反映する
  - preview-rule-effect が「水曜の割当が removed」を返す
"""

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

import src.handlers as handlers_mod
import src.storage as storage
from src.agents import ParamItem, ParamsAgent
from src.api.main import app
from src.handlers import register_dynamic_handler
from src.models.admin_queue import PendingTypeRequest
from src.models.solver_io import SolverInput
from src.solver.engine import solve

client = TestClient(app)

# recurring_day_off 風のハンドラ（指定者を指定曜日に出勤させない・Hard）
RECURRING_HANDLER = """
def handle(params, ctx):
    weekday_map = {"monday":0,"tuesday":1,"wednesday":2,"thursday":3,"friday":4,"saturday":5,"sunday":6}
    pid = params.get("person_id")
    wd = params.get("weekday")
    if isinstance(wd, str):
        wd = weekday_map.get(wd.lower())
    if pid not in ctx.person_ids or wd is None:
        return
    for di, day in enumerate(ctx.days):
        if day.weekday() == wd:
            ctx.model.Add(ctx.work_day[(pid, di)] == 0)
"""


@pytest.fixture(autouse=True)
def _clean_storage():
    """インメモリ状態をテストごとに初期化する。"""
    storage._pending_queue.clear()
    storage.clear_dynamic_constraints()
    storage.clear_availability()
    storage.clear_policy_constraints()
    storage.save_base_headcounts([])
    handlers_mod._DYNAMIC_HANDLERS.clear()
    yield
    storage._pending_queue.clear()
    storage.clear_dynamic_constraints()
    handlers_mod._DYNAMIC_HANDLERS.clear()


# 2026-11-02(月) 〜 11-04(水)。11-04 が水曜。
MASTERS = {
    "persons": [{"id": "p1", "name": "スタッフ01"}],
    "positions": [{"id": "pos_hall", "name": "ホール"}],
    "roles": [], "skills": [],
}
FRAME = {
    "period": {"start": "2026-11-02", "end": "2026-11-04"},
    "operating_window": {"open": "11:00", "close": "12:00", "slot_minutes": 60},
    "policy_mode": "balance",
}


def _spec(dynamic):
    cons = [{
        "type": "headcount_requirement",
        "params": {"slot_label": "L", "time_start": "11:00", "time_end": "12:00",
                   "position_id": "pos_hall", "count": 1},
    }]
    for d in ("2026-11-02", "2026-11-03", "2026-11-04"):
        cons.append({"type": "availability", "params": {
            "person_id": "p1", "date": d, "start": "11:00", "end": "12:00"}})
    return SolverInput.model_validate({
        "frame": FRAME, "masters": MASTERS,
        "constraints": cons, "dynamic_constraints": dynamic,
    })


# ── 1. dynamic_constraints が solve に効く ─────────────────────────────

def test_dynamic_constraint_removes_wednesday():
    register_dynamic_handler("recurring_day_off", RECURRING_HANDLER)
    dyn = [{"type": "recurring_day_off", "params": {"person_id": "p1", "weekday": "wednesday"}}]

    out = solve(_spec(dyn))

    wed_assigns = [a for a in out.assignments
                   if a.person_id == "p1" and a.date == date(2026, 11, 4)]
    other_assigns = [a for a in out.assignments
                     if a.person_id == "p1" and a.date != date(2026, 11, 4)]
    assert wed_assigns == []          # 水曜は消える
    assert len(other_assigns) == 2    # 月・火は入る


def test_without_dynamic_constraint_keeps_wednesday():
    out = solve(_spec([]))   # ルール無し
    wed = [a for a in out.assignments
           if a.person_id == "p1" and a.date == date(2026, 11, 4)]
    assert len(wed) == 1     # ルールが無ければ水曜も入る


# ── 2. _paramize_and_store（ParamsAgentモック） ───────────────────────

def test_paramize_and_store_saves_dynamic_constraints(monkeypatch):
    from src.api.routes_admin import _paramize_and_store

    def fake_convert(self, type_name, param_schema_json, example_params_json, occurrences):
        return [ParamItem(index=o["index"],
                          params_json=json.dumps({"person_id": o["person_id"], "weekday": "wednesday"}))
                for o in occurrences]

    monkeypatch.setattr(ParamsAgent, "convert", fake_convert)

    req = PendingTypeRequest(
        id="req_x", suggested_type_name="recurring_day_off",
        source_texts=["毎週水曜NG", "毎週水曜は授業"],
        occurrences=[
            {"person_id": "p1", "date": "2026-11-04", "source_text": "毎週水曜NG", "origin": "note"},
            {"person_id": "p2", "date": "2026-11-11", "source_text": "毎週水曜は授業", "origin": "note"},
        ],
        suggested_schema={"person_id": "str", "weekday": "str"},
        tested_params={"person_id": "p1", "weekday": "wednesday"},
        created_at=__import__("datetime").datetime.now(),
    )

    n = _paramize_and_store(req)

    assert n == 2
    saved = storage.get_dynamic_constraints()
    assert len(saved) == 2
    assert saved[0]["type"] == "recurring_day_off"
    assert saved[0]["params"] == {"person_id": "p1", "weekday": "wednesday"}
    assert saved[0]["source"]["person_id"] == "p1"


# ── 3. run-stored が dynamic_constraints を反映 ───────────────────────

def _setup_via_api():
    assert client.post("/setup/masters", json=MASTERS).status_code == 200
    assert client.post("/setup/frame", json=FRAME).status_code == 200
    desired = [{"person_id": "p1", "date": d, "start": "11:00", "end": "12:00"}
               for d in ("2026-11-02", "2026-11-03", "2026-11-04")]
    assert client.post("/setup/desired-shifts", json=desired).status_code == 200
    hc = [{"slot_label": "L", "time_start": "11:00", "time_end": "12:00",
           "position_id": "pos_hall", "count": 1}]
    assert client.post("/setup/headcounts", json=hc).status_code == 200


def test_run_stored_reflects_dynamic_constraint():
    _setup_via_api()
    register_dynamic_handler("recurring_day_off", RECURRING_HANDLER)
    storage.save_dynamic_constraints([{
        "type": "recurring_day_off",
        "params": {"person_id": "p1", "weekday": "wednesday"},
        "source": {"person_id": "p1", "date": "2026-11-04", "source_text": "毎週水曜NG"},
    }])

    out = client.post("/solver/run-stored").json()

    wed = [a for a in out["assignments"]
           if a["person_id"] == "p1" and a["date"] == "2026-11-04"]
    assert wed == []


# ── 4. preview-rule-effect が removed を返す ──────────────────────────

def test_preview_rule_effect_reports_removed():
    _setup_via_api()
    register_dynamic_handler("recurring_day_off", RECURRING_HANDLER)
    storage.save_dynamic_constraints([{
        "type": "recurring_day_off",
        "params": {"person_id": "p1", "weekday": "wednesday"},
        "source": {"person_id": "p1", "date": "2026-11-04", "source_text": "毎週水曜NG"},
    }])

    resp = client.post("/solver/preview-rule-effect", json={"type_name": "recurring_day_off"})
    assert resp.status_code == 200
    data = resp.json()

    removed = data["diff"]["removed"]
    assert any(a["person_id"] == "p1" and a["date"] == "2026-11-04" for a in removed)
    # before は水曜あり、after は水曜なし
    assert any(a["date"] == "2026-11-04" for a in data["before"]["assignments"])
    assert all(a["date"] != "2026-11-04" for a in data["after"]["assignments"]
               if a["person_id"] == "p1")
