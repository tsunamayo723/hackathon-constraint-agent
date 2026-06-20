"""
レシピ・インタプリタのテスト（Gemini不要）

5操作（forbid/require/limit_count/penalize/prefer）が、レシピ（データ）から
正しくソルバー制約に翻訳されることを確認する。デモ3type＋既知数typeを
レシピで表現して、期待どおりシフトが動くかを見る。
"""

from datetime import date

from ortools.sat.python import cp_model

from src.models.master import Masters
from src.solver.context import SolverContext
from src.solver.engine import _build_variables
from src.solver.recipe import apply_recipe
from src.solver.slots import build_day_slots, date_range


def _ctx(persons=3, start=date(2026, 11, 2), end=date(2026, 11, 8),
         open_="11:00", close="22:00", slot=60):
    """3名×1週間（月〜日）×ホールの検証用文脈。p1はリーダー＆バー持ち。"""
    masters = Masters.model_validate({
        "persons": [
            {"id": f"p{i}", "name": f"P{i}",
             "role_id": "r_lead" if i == 1 else "r_staff",
             "skill_ids": ["sk_bar"] if i == 1 else []}
            for i in range(1, persons + 1)
        ],
        "positions": [{"id": "pos_hall", "name": "ホール"}],
        "roles": [{"id": "r_lead", "name": "リーダー"}, {"id": "r_staff", "name": "スタッフ"}],
        "skills": [{"id": "sk_bar", "name": "バー"}],
    })
    ctx = SolverContext(
        model=cp_model.CpModel(),
        days=date_range(start, end),
        slots=build_day_slots(open_, close, slot),
        masters=masters,
    )
    _build_variables(ctx)
    return ctx


def _solve(ctx):
    """engineと同じ目的関数（不足＋罰金＋総割当）で解く。"""
    ctx.model.Minimize(
        sum(w * z for w, z in ctx.shortages)
        + sum(w * z for w, z in ctx.penalties)
        + sum(ctx.x.values())
    )
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    solver.parameters.random_seed = 42
    assert solver.Solve(ctx.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    return solver


def _slot_index(ctx, hhmm: str) -> int:
    return next(s.index for s in ctx.slots if s.start == hhmm)


# 必要人数（ランチに1名）をレシピで足す共通ヘルパー
def _require_lunch(count=1, who="all"):
    return {"operation": "require", "who": who, "band": "window",
            "time_start": "11:00", "time_end": "12:00",
            "where": "position", "position_id": "pos_hall", "count": count}


# ── forbid（recurring_day_off） ──────────────────────────────────────

def test_forbid_weekday_removes_that_day():
    ctx = _ctx()
    apply_recipe(_require_lunch(count=1), ctx)
    # p1は毎週水曜(=weekday 2)は終日不可
    apply_recipe({"operation": "forbid", "who": "person", "person_id": "p1",
                  "when": "weekday", "weekday": 2, "band": "all_day"}, ctx)
    solver = _solve(ctx)

    di_wed = next(di for di, d in enumerate(ctx.days) if d == date(2026, 11, 4))
    assert solver.Value(ctx.work_day[("p1", di_wed)]) == 0          # 水曜は入らない
    # 誰かが水曜のランチを埋めている（穴は開かない）
    li = _slot_index(ctx, "11:00")
    assert sum(solver.Value(ctx.present[(p, di_wed, li)]) for p in ctx.person_ids) >= 1


# ── require（headcount_requirement） ─────────────────────────────────

def test_require_fills_count():
    ctx = _ctx()
    apply_recipe(_require_lunch(count=2), ctx)
    solver = _solve(ctx)

    li = _slot_index(ctx, "11:00")
    for di in range(len(ctx.days)):
        assert sum(solver.Value(ctx.x[(p, di, li, "pos_hall")]) for p in ctx.person_ids) == 2


def test_require_by_role():
    """who=role: ランチにリーダー(p1)を最低1名 → p1がランチに入る。"""
    ctx = _ctx()
    apply_recipe({"operation": "require", "who": "role", "role_id": "r_lead",
                  "band": "window", "time_start": "11:00", "time_end": "12:00",
                  "where": "position", "position_id": "pos_hall", "count": 1}, ctx)
    solver = _solve(ctx)

    li = _slot_index(ctx, "11:00")
    for di in range(len(ctx.days)):
        assert solver.Value(ctx.x[("p1", di, li, "pos_hall")]) == 1


# ── penalize（exam_period / separate） ───────────────────────────────

def test_penalize_daterange_avoids_person():
    ctx = _ctx(persons=2)
    apply_recipe(_require_lunch(count=1), ctx)
    # p1は試験期間(週全体)はなるべく入れない（強め）
    apply_recipe({"operation": "penalize", "who": "person", "person_id": "p1",
                  "when": "date_range", "date_start": date(2026, 11, 2),
                  "date_end": date(2026, 11, 8), "band": "all_day", "weight": 1000}, ctx)
    solver = _solve(ctx)

    # p2だけで全日カバーできるので、p1は1日も入らない
    assert sum(solver.Value(ctx.work_day[("p1", di)]) for di in range(len(ctx.days))) == 0


def test_penalize_pair_separates():
    ctx = _ctx(persons=3)
    apply_recipe(_require_lunch(count=2), ctx)
    # p1とp2はなるべく同じ日に入れない
    apply_recipe({"operation": "penalize", "who": "pair", "person_id": "p1",
                  "person_id_b": "p2", "band": "all_day", "weight": 1000}, ctx)
    solver = _solve(ctx)

    for di in range(len(ctx.days)):
        both = solver.Value(ctx.work_day[("p1", di)]) and solver.Value(ctx.work_day[("p2", di)])
        assert not both     # 同じ日に2人同時はない


# ── limit_count（max_late_shift_count） ──────────────────────────────

def test_limit_count_caps_late_days():
    ctx = _ctx(persons=3)
    # 21:00-22:00（遅番枠）に毎日2名必要
    apply_recipe({"operation": "require", "who": "all", "band": "window",
                  "time_start": "21:00", "time_end": "22:00",
                  "where": "position", "position_id": "pos_hall", "count": 2}, ctx)
    # p1の遅番は週内に最大1回まで
    apply_recipe({"operation": "limit_count", "who": "person", "person_id": "p1",
                  "band": "window", "time_start": "21:00", "time_end": "22:00",
                  "max": 1, "period": "total"}, ctx)
    solver = _solve(ctx)

    late = _slot_index(ctx, "21:00")
    p1_late_days = sum(solver.Value(ctx.present[("p1", di, late)]) for di in range(len(ctx.days)))
    assert p1_late_days <= 1


# ── prefer（time_preference / prefer_person） ────────────────────────

def test_prefer_pulls_person_in():
    ctx = _ctx(persons=3)
    apply_recipe(_require_lunch(count=1), ctx)
    # p2をなるべく多く入れたい（毎日ランチ枠へ）
    apply_recipe({"operation": "prefer", "who": "person", "person_id": "p2",
                  "band": "window", "time_start": "11:00", "time_end": "12:00",
                  "weight": 800}, ctx)
    solver = _solve(ctx)

    li = _slot_index(ctx, "11:00")
    # preferが効けば p2 がランチに入る日数が多い（全日入る想定）
    p2_lunch = sum(solver.Value(ctx.present[("p2", di, li)]) for di in range(len(ctx.days)))
    assert p2_lunch == len(ctx.days)


# ── rest_after_late（前日遅番→翌日休み・逐次条件） ───────────────────

def test_rest_after_late_adds_penalty_per_pair():
    """連続する日のペアごとに罰金が1つ足される。"""
    ctx = _ctx(persons=2)
    before = len(ctx.penalties)
    apply_recipe({"operation": "rest_after_late", "who": "person", "person_id": "p1",
                  "band": "window", "time_start": "18:00", "time_end": "22:00", "weight": 600}, ctx)
    assert len(ctx.penalties) - before == len(ctx.days) - 1


def test_rest_after_late_frees_next_day():
    """初日に遅番を強いられた p1 は、翌日はお休みになる。"""
    ctx = _ctx(persons=2)
    # 遅番(18-22)・昼(11-12)を毎日1名必要
    apply_recipe({"operation": "require", "who": "all", "band": "window",
                  "time_start": "18:00", "time_end": "22:00",
                  "where": "position", "position_id": "pos_hall", "count": 1}, ctx)
    apply_recipe(_require_lunch(count=1), ctx)
    # 初日(11/2)の遅番は p2 を不可 → 初日遅番は p1 が担当
    apply_recipe({"operation": "forbid", "who": "person", "person_id": "p2",
                  "when": "date", "date": date(2026, 11, 2),
                  "band": "window", "time_start": "18:00", "time_end": "22:00"}, ctx)
    # p1: 前日が遅番なら翌日は休み（強め）
    apply_recipe({"operation": "rest_after_late", "who": "person", "person_id": "p1",
                  "band": "window", "time_start": "18:00", "time_end": "22:00", "weight": 1000}, ctx)
    solver = _solve(ctx)

    di0 = next(di for di, d in enumerate(ctx.days) if d == date(2026, 11, 2))
    di1 = next(di for di, d in enumerate(ctx.days) if d == date(2026, 11, 3))
    late = _slot_index(ctx, "18:00")
    assert solver.Value(ctx.present[("p1", di0, late)]) == 1   # 初日は p1 が遅番
    assert solver.Value(ctx.work_day[("p1", di1)]) == 0        # 翌日は休み
