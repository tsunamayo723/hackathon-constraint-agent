"""
シフト検証器（バリデータ）のテスト

- ソルバーの正常出力は不変条件を満たす（valid=True・違反0）
- 希望未提出スタッフは warning に出る
- わざと枠外の割当を混ぜると out_of_availability を検出する
"""

from src.models.solver_io import Assignment, SolverInput, SolverOutput
from src.solver.engine import solve
from src.solver.validator import validate


def _spec(constraints):
    return SolverInput.model_validate({
        "frame": {"period": {"start": "2026-11-01", "end": "2026-11-02"},
                  "operating_window": {"open": "11:00", "close": "14:00", "slot_minutes": 60},
                  "policy_mode": "balance"},
        "masters": {"persons": [{"id": "p1", "name": "A"}, {"id": "p2", "name": "B"}],
                    "positions": [{"id": "pos_hall", "name": "ホール"}], "roles": [], "skills": []},
        "constraints": constraints,
    })


_HEADCOUNT = {"type": "headcount_requirement",
              "params": {"slot_label": "L", "time_start": "11:00", "time_end": "14:00",
                         "position_id": "pos_hall", "count": 1}}


def test_solver_output_passes_validation():
    spec = _spec([
        _HEADCOUNT,
        {"type": "availability", "params": {"person_id": "p1", "date": "2026-11-01", "start": "11:00", "end": "14:00"}},
        {"type": "availability", "params": {"person_id": "p1", "date": "2026-11-02", "start": "11:00", "end": "14:00"}},
    ])
    out = solve(spec)
    assert out.validation is not None
    assert out.validation.valid is True
    assert out.validation.violation_count == 0
    # p2 は希望未提出 → 要注意warningに出る
    assert any("未提出" in w for w in out.validation.warnings)


def test_validator_detects_out_of_availability():
    # p1 は 11/01 11:00-14:00 のみ可用。わざと 11/02 に配置した出力を検証 → 違反検出。
    spec = _spec([
        {"type": "availability", "params": {"person_id": "p1", "date": "2026-11-01", "start": "11:00", "end": "14:00"}},
    ])
    bad = SolverOutput(status="solved", assignments=[
        Assignment(date="2026-11-02", person_id="p1", position_id="pos_hall", start="11:00", end="12:00"),
    ])
    result = validate(spec, bad)
    assert result.valid is False
    assert any(v.type == "out_of_availability" for v in result.violations)
