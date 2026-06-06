"""
最小ソルバー（OR-Tools）のテスト

対応3タイプ headcount_requirement / availability / separate の振る舞いを確認する。
- 必要人数を満たす解が出るか
- availability の枠外に入らないか
- separate がソフト（解を妨げず罰金を払う）として効くか
- 充足不能を正しく検出し、詰まり箇所を診断するか
- 未対応タイプを黙って捨てず警告で可視化するか
"""

from src.models.parser_io import UntranslatedConstraint
from src.models.solver_io import SolverInput
from src.solver.engine import solve
from src.solver.slots import build_day_slots, date_range, hhmm_to_min, min_to_hhmm
from datetime import date as _date


def _base_masters():
    return {
        "persons": [
            {"id": "p1", "name": "スタッフ01"},
            {"id": "p2", "name": "スタッフ02"},
        ],
        "positions": [{"id": "pos_hall", "name": "ホール"}],
        "roles": [],
        "skills": [],
    }


def _spec(constraints, start="2026-11-01", end="2026-11-01",
          open_="11:00", close="12:00", slot=60, with_availability=True):
    cons = list(constraints)
    # 希望未提出＝出勤不可になったので、既定で p1/p2 に全日フル可用を付与しておく
    # （availability そのものを検証するテストは with_availability=False で自前指定する）
    if with_availability:
        for d in date_range(_date.fromisoformat(start), _date.fromisoformat(end)):
            for pid in ("p1", "p2"):
                cons.append({"type": "availability", "params": {
                    "person_id": pid, "date": d.isoformat(), "start": "00:00", "end": "23:59"}})
    return SolverInput.model_validate({
        "frame": {
            "period": {"start": start, "end": end},
            "operating_window": {"open": open_, "close": close, "slot_minutes": slot},
            "policy_mode": "balance",
        },
        "masters": _base_masters(),
        "constraints": cons,
    })


# ── スロットのユーティリティ ──────────────────────────────────────


def test_hhmm_conversion_roundtrip():
    assert hhmm_to_min("11:30") == 690
    assert min_to_hhmm(690) == "11:30"


def test_build_day_slots_count():
    slots = build_day_slots("11:00", "14:00", 60)
    assert len(slots) == 3
    assert slots[0].start == "11:00" and slots[0].end == "12:00"
    assert slots[-1].end == "14:00"


# ── headcount ─────────────────────────────────────────────────────


def test_headcount_is_satisfied():
    out = solve(_spec([{
        "type": "headcount_requirement",
        "params": {"slot_label": "L", "time_start": "11:00", "time_end": "12:00",
                   "position_id": "pos_hall", "count": 1},
    }]))
    assert out.status == "solved"
    assert out.shift_status == "confirmed"
    assert len(out.assignments) == 1


def test_headcount_date_applies_only_that_day():
    # date 指定の headcount は「その日だけ」効く。
    # 11/02 だけ pos_hall 5名（在籍2名）→ その日だけ不足が出る。他日は需要なし。
    out = solve(_spec([{
        "type": "headcount_requirement",
        "params": {"slot_label": "L", "time_start": "11:00", "time_end": "12:00",
                   "position_id": "pos_hall", "count": 5, "date": "2026-11-02"},
    }], start="2026-11-01", end="2026-11-03"))
    assert out.status == "solved"
    # 不足が出るのは 11/02 のみ
    und_dates = {str(w.affected_date) for w in out.warnings if w.type == "understaffed"}
    assert und_dates == {"2026-11-02"}


def test_headcount_shortage_is_best_effort_not_infeasible():
    # 必要3名に対し在籍2名 → Hardではなく不足を減点。解けない状況でも暫定シフトを出す。
    out = solve(_spec([{
        "type": "headcount_requirement",
        "params": {"slot_label": "L", "time_start": "11:00", "time_end": "12:00",
                   "position_id": "pos_hall", "count": 3},
    }]))
    assert out.status == "solved"          # infeasibleにならず暫定解が出る
    assert len(out.assignments) == 2       # 配置できる2名は配置
    assert out.meta.shortage_penalty > 0   # 不足ぶんは減点
    assert any(w.type == "understaffed" and w.shortage == 1 for w in out.warnings)


# ── availability ──────────────────────────────────────────────────


def test_availability_restricts_to_offered_day():
    # 2日間・各日1名必要。p1は両日可用、p2は1日目だけ可用。
    # → p2は2日目に入れない（枠外固定）
    out = solve(_spec(
        [
            {"type": "headcount_requirement",
             "params": {"slot_label": "L", "time_start": "11:00", "time_end": "12:00",
                        "position_id": "pos_hall", "count": 1}},
            {"type": "availability",
             "params": {"person_id": "p1", "date": "2026-11-01", "start": "11:00", "end": "12:00"}},
            {"type": "availability",
             "params": {"person_id": "p1", "date": "2026-11-02", "start": "11:00", "end": "12:00"}},
            {"type": "availability",
             "params": {"person_id": "p2", "date": "2026-11-01", "start": "11:00", "end": "12:00"}},
        ],
        start="2026-11-01", end="2026-11-02", with_availability=False,
    ))
    assert out.status == "solved"
    # p2 が2日目(11-02)に割り当てられていないこと
    p2_day2 = [a for a in out.assignments if a.person_id == "p2" and str(a.date) == "2026-11-02"]
    assert p2_day2 == []


# ── separate（ソフト制約） ────────────────────────────────────────


def test_separate_is_soft_not_blocking():
    # 必要2名×在籍2名 → 同席は不可避。separateがHardなら詰まるが、
    # ソフトなので罰金を払って解ける（status=solved）。
    out = solve(_spec([
        {"type": "headcount_requirement",
         "params": {"slot_label": "L", "time_start": "11:00", "time_end": "12:00",
                    "position_id": "pos_hall", "count": 2}},
        {"type": "separate",
         "params": {"person_a": "p1", "person_b": "p2", "scope": "day", "weight": 600}},
    ]))
    assert out.status == "solved"
    assert len(out.assignments) == 2
    # 罰金600が目的関数に乗る（割当2 + 罰金600 = 602）
    assert out.meta.objective >= 600


def test_separate_avoided_when_possible():
    # 各日1名で足りる2日間。separateありでも片方ずつ入れれば罰金0で済む。
    out = solve(_spec(
        [
            {"type": "headcount_requirement",
             "params": {"slot_label": "L", "time_start": "11:00", "time_end": "12:00",
                        "position_id": "pos_hall", "count": 1}},
            {"type": "separate",
             "params": {"person_a": "p1", "person_b": "p2", "scope": "day", "weight": 600}},
        ],
        start="2026-11-01", end="2026-11-02",
    ))
    assert out.status == "solved"
    # 同じ日に2人同席していないこと
    by_day: dict[str, set] = {}
    for a in out.assignments:
        by_day.setdefault(str(a.date), set()).add(a.person_id)
    assert all(len(persons) <= 1 for persons in by_day.values())


# ── 暫定 / 未対応タイプ ───────────────────────────────────────────


def test_evaluation_is_populated():
    # solved 時に評価指標（ポジション別充足・スタッフ別稼働・公平性）が入る
    out = solve(_spec([{
        "type": "headcount_requirement",
        "params": {"slot_label": "L", "time_start": "11:00", "time_end": "12:00",
                   "position_id": "pos_hall", "count": 1},
    }]))
    assert out.evaluation is not None
    assert out.evaluation.position_coverage  # ポジション別が1件以上
    assert len(out.evaluation.staff_stats) == 2  # 2名分
    assert out.evaluation.fair_max >= out.evaluation.fair_min


def test_pending_makes_provisional():
    pending = [UntranslatedConstraint(
        source_text="毎週水曜は休み", suggested_type_name="recurring_day_off", reason="AI準備中",
    )]
    out = solve(_spec([{
        "type": "headcount_requirement",
        "params": {"slot_label": "L", "time_start": "11:00", "time_end": "12:00",
                   "position_id": "pos_hall", "count": 1},
    }]), pending)
    assert out.shift_status == "provisional"
    assert len(out.pending_constraints) == 1


def test_unhandled_type_is_warned_not_dropped():
    out = solve(_spec([
        {"type": "headcount_requirement",
         "params": {"slot_label": "L", "time_start": "11:00", "time_end": "12:00",
                    "position_id": "pos_hall", "count": 1}},
        {"type": "fairness", "params": {"dimension": "shifts", "weight": 300}},
    ]))
    assert any(w.type == "unhandled:fairness" for w in out.warnings)
