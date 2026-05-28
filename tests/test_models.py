"""
モデル定義の動作確認テスト
"""

import pytest
from datetime import date
from pydantic import ValidationError

from src.models import (
    Constraint,
    KNOWN_TYPES,
    Masters,
    Person,
    Position,
    Role,
    Skill,
    SolverInput,
    Frame,
    OperatingWindow,
    Period,
    HeadcountRequirement,
    Availability,
    Separate,
    DesiredWorkdays,
)


# ── マスタ ────────────────────────────────────────────────────────

def test_masters_basic():
    masters = Masters(
        persons=[Person(id="p1", name="田中", role_id="r_leader", skill_ids=["sk_cash"])],
        positions=[Position(id="pos_hall", name="ホール")],
        roles=[Role(id="r_leader", name="リーダー")],
        skills=[Skill(id="sk_cash", name="レジ")],
    )
    assert masters.persons[0].name == "田中"


def test_person_no_role():
    p = Person(id="p2", name="佐藤")
    assert p.role_id is None
    assert p.skill_ids == []


# ── Hard 制約 ─────────────────────────────────────────────────────

def test_headcount_requirement():
    c = HeadcountRequirement(params={
        "slot_label": "ランチ",
        "time_start": "11:00",
        "time_end": "14:00",
        "position_id": "pos_hall",
        "count": 4,
    })
    assert c.type == "headcount_requirement"
    assert c.params.count == 4


def test_availability():
    c = Availability(params={
        "person_id": "p1",
        "date": "2026-11-01",
        "start": "10:00",
        "end": "15:00",
    })
    assert c.params.date == date(2026, 11, 1)


# ── Soft 制約: weight クリップ ────────────────────────────────────

def test_weight_clip_upper():
    c = Separate(params={"person_a": "p1", "person_b": "p2", "scope": "day", "weight": 9999})
    assert c.params.weight == 1000   # 上限クリップ


def test_weight_clip_lower():
    c = Separate(params={"person_a": "p1", "person_b": "p2", "scope": "day", "weight": 1})
    assert c.params.weight == 50     # 下限クリップ


def test_weight_in_range():
    c = Separate(params={"person_a": "p1", "person_b": "p2", "scope": "day", "weight": 600})
    assert c.params.weight == 600    # そのまま


# ── Discriminated union ───────────────────────────────────────────

def test_constraint_union_headcount():
    raw = {"type": "headcount_requirement", "params": {
        "slot_label": "ランチ", "time_start": "11:00", "time_end": "14:00",
        "position_id": "pos_hall", "count": 4,
    }}
    from pydantic import TypeAdapter
    ta = TypeAdapter(Constraint)
    c = ta.validate_python(raw)
    assert c.type == "headcount_requirement"


def test_constraint_union_desired_workdays():
    raw = {"type": "desired_workdays", "params": {
        "person_id": "p1", "kind": "range", "min": 10, "max": 15, "weight": 300,
    }}
    from pydantic import TypeAdapter
    ta = TypeAdapter(Constraint)
    c = ta.validate_python(raw)
    assert c.params.min == 10


# ── KNOWN_TYPES ───────────────────────────────────────────────────

def test_known_types_count():
    assert len(KNOWN_TYPES) == 16


def test_unknown_type_detection():
    assert "recurring_day_off" not in KNOWN_TYPES    # L2デモ対象
    assert "max_late_shift_count" not in KNOWN_TYPES  # L2デモ対象
    assert "exam_period" not in KNOWN_TYPES           # L2デモ対象


# ── SolverInput ───────────────────────────────────────────────────

def test_solver_input_full():
    spec = SolverInput(
        frame=Frame(
            period=Period(start="2026-11-01", end="2026-11-14"),
            operating_window=OperatingWindow(open="10:00", close="22:00", slot_minutes=30),
            policy_mode="wishes",
        ),
        masters=Masters(
            persons=[Person(id="p1", name="田中")],
            positions=[Position(id="pos_hall", name="ホール")],
            roles=[],
            skills=[],
        ),
        constraints=[
            HeadcountRequirement(params={
                "slot_label": "ランチ",
                "time_start": "11:00",
                "time_end": "14:00",
                "position_id": "pos_hall",
                "count": 3,
            }),
        ],
    )
    assert spec.frame.policy_mode == "wishes"
    assert len(spec.constraints) == 1
