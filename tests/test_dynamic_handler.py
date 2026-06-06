"""
動的ハンドラ（A1b: 承認→登録→適用）のテスト

- register_dynamic_handler で生成ハンドラを登録すると、
  SolverInput.dynamic_constraints 経由でソルバーに効くこと
- 未登録の動的タイプは黙って捨てず warnings に出ること
"""

from datetime import date

from src.handlers import register_dynamic_handler
from src.models.solver_io import SolverInput
from src.solver.engine import solve

# AIが生成する想定の recurring_day_off ハンドラ（既知の正解コード）
RECURRING_DAY_OFF_CODE = """
def handle(params, ctx):
    weekday_map = {"monday":0,"tuesday":1,"wednesday":2,"thursday":3,
                   "friday":4,"saturday":5,"sunday":6}
    pid = params.get("person_id")
    wd = weekday_map.get(str(params.get("weekday","")).lower())
    if pid not in ctx.person_ids or wd is None:
        return
    for di, day in enumerate(ctx.days):
        if day.weekday() == wd:
            ctx.model.Add(ctx.work_day[(pid, di)] == 0)
"""


def _spec(dynamic_constraints):
    from datetime import date, timedelta
    # 希望未提出＝出勤不可になったので p1/p2 に全日フル可用を付与
    cons = [{
        "type": "headcount_requirement",
        "params": {"slot_label": "L", "time_start": "11:00", "time_end": "14:00",
                   "position_id": "pos_hall", "count": 1},
    }]
    d = date(2026, 11, 2)
    while d <= date(2026, 11, 8):
        for pid in ("p1", "p2"):
            cons.append({"type": "availability", "params": {
                "person_id": pid, "date": d.isoformat(), "start": "00:00", "end": "23:59"}})
        d += timedelta(days=1)

    return SolverInput.model_validate({
        "frame": {
            "period": {"start": "2026-11-02", "end": "2026-11-08"},  # 月〜日（水を含む）
            "operating_window": {"open": "11:00", "close": "14:00", "slot_minutes": 60},
            "policy_mode": "balance",
        },
        "masters": {
            "persons": [{"id": "p1", "name": "A"}, {"id": "p2", "name": "B"}],
            "positions": [{"id": "pos_hall", "name": "ホール"}],
            "roles": [], "skills": [],
        },
        "constraints": cons,
        "dynamic_constraints": dynamic_constraints,
    })


def test_registered_dynamic_handler_is_applied():
    # 承認＝登録
    register_dynamic_handler("recurring_day_off", RECURRING_DAY_OFF_CODE)

    out = solve(_spec([
        {"type": "recurring_day_off", "params": {"person_id": "p1", "weekday": "wednesday"}}
    ]))

    assert out.status == "solved"
    # p1 は水曜(weekday==2)には割り当てられない（p2が代わりに入る）
    for a in out.assignments:
        if a.person_id == "p1":
            assert date.fromisoformat(str(a.date)).weekday() != 2


def test_unregistered_dynamic_type_is_warned():
    out = solve(_spec([
        {"type": "never_registered_type", "params": {}}
    ]))
    assert any(w.type == "unregistered:never_registered_type" for w in out.warnings)
