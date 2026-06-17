"""
レシピ（操作×選択子）→ ソルバー制約のインタプリタ

AIに生のPythonを書かせる代わりに、安全な「操作＋選択子」の**レシピ（データ）**を
出させ、この信頼できる固定コードがソルバー制約に変換する。
これでAPI誤用バグ（CP-SAT変数のbool評価・存在しないキー参照など）が
**構造的に発生しなくなる**（AIコードのexecも不要）。

操作（5個）:
  forbid       … Hard: 選択した枠に入れない
  require      … Hard: 選択範囲に最低 count 人（不足は減点＝best-effort）
  limit_count  … Hard: 条件に当たる「日数」を期間内 max 回まで
  penalize     … Soft: 条件成立で weight の罰金（なるべく避ける）
  prefer       … Soft: 選択枠をなるべく入れる（入らないと weight の罰金）

選択子:
  誰(who)     person / role / skill / pair / all
  時(when)    date / date_range / weekday / always
  時間帯(band) window(HH:MM-HH:MM) / all_day
  場所(where) position / any
  量          count / max / weight(50-1000にクリップ) / period(total/week/month)

例（既知/未知typeの対応）:
  recurring_day_off   = forbid(person, weekday, all_day)
  exam_period         = penalize(person, date_range, all_day, weight)
  max_late_shift_count= limit_count(person, band=window 22:00-, max=3, period=month)
  headcount_requirement = require(all, band=window, where=position, count)
  separate            = penalize(pair, ...)
  time_preference     = prefer(person, band=window)
"""

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

from src.solver.context import SolverContext
from src.solver.slots import hhmm_to_min

# 「date」という名前のフィールドが型名 date をシャドーするのを避けるための別名
DateType = date

# 必要人数の不足1人あたりの減点（builtin.handle_headcount と揃える）
SHORTAGE_PENALTY = 5000


class Recipe(BaseModel):
    """1ルール＝1操作＋選択子。AIはこの形（データ）を出すだけでよい。"""

    model_config = ConfigDict(extra="forbid")

    operation: Literal["forbid", "require", "limit_count", "penalize", "prefer"]

    # 誰 who
    who: Literal["person", "role", "skill", "pair", "all"] = "person"
    person_id: Optional[str] = None
    person_id_b: Optional[str] = None      # who=pair の相手
    role_id: Optional[str] = None
    skill_id: Optional[str] = None

    # 時 when
    when: Literal["date", "date_range", "weekday", "always"] = "always"
    date: Optional[DateType] = None
    date_start: Optional[DateType] = None
    date_end: Optional[DateType] = None
    weekday: Optional[int] = None          # 0=月 .. 6=日

    # 時間帯 band
    band: Literal["window", "all_day"] = "all_day"
    time_start: Optional[str] = None       # "HH:MM"
    time_end: Optional[str] = None

    # 場所 where
    where: Literal["position", "any"] = "any"
    position_id: Optional[str] = None

    # 量
    count: Optional[int] = None            # require の必要人数
    max: Optional[int] = None              # limit_count の上限
    weight: int = 500                      # soft操作の罰金
    period: Literal["total", "week", "month"] = "total"  # limit_count の期間


def _clip_weight(w: int) -> int:
    """ソフト罰金は 50〜1000 にクリップ（プロンプトインジェクション対策・設計ルール）。"""
    return max(50, min(1000, int(w)))


def validate_recipe(recipe: dict) -> tuple[bool, str]:
    """レシピが解釈可能かを確かめる（パース＋小シナリオへ適用）。

    旧Python方式のサンドボックス（subprocess＋exec）の代わり。レシピは固定インタプリタが
    処理するので**任意コード実行が無く**、プロセス内で安全に検証できる。
    返り値: (合格か, メッセージ)
    """
    try:
        r = Recipe.model_validate(recipe)
    except Exception as exc:
        return False, f"レシピの形式エラー: {exc}"

    # 検証用の小さな文脈（3名×1週間×ホール）
    from datetime import date as _date

    from ortools.sat.python import cp_model

    from src.models.master import Masters
    from src.solver.engine import _build_variables
    from src.solver.slots import build_day_slots, date_range

    masters = Masters.model_validate({
        "persons": [
            {"id": "p1", "name": "A", "role_id": "r_lead", "skill_ids": ["sk_bar"]},
            {"id": "p2", "name": "B", "role_id": "r_staff", "skill_ids": []},
            {"id": "p3", "name": "C", "role_id": "r_staff", "skill_ids": []},
        ],
        "positions": [{"id": "pos_hall", "name": "ホール"}],
        "roles": [{"id": "r_lead", "name": "リーダー"}, {"id": "r_staff", "name": "スタッフ"}],
        "skills": [{"id": "sk_bar", "name": "バー"}],
    })
    ctx = SolverContext(
        model=cp_model.CpModel(),
        days=date_range(_date(2026, 11, 2), _date(2026, 11, 8)),
        slots=build_day_slots("11:00", "22:00", 60),
        masters=masters,
    )
    _build_variables(ctx)

    before = len(ctx.penalties) + len(ctx.shortages) + len(ctx.model.Proto().constraints)
    try:
        apply_recipe(r, ctx)
    except Exception as exc:
        return False, f"適用時エラー: {exc}"
    after = len(ctx.penalties) + len(ctx.shortages) + len(ctx.model.Proto().constraints)

    if after <= before:
        return False, "このレシピは制約を1つも生みませんでした（選択子が空・対象が居ない可能性）"
    return True, "レシピを検証シナリオに適用できました（制約が生成されました）"


# ── 選択子の解決 ────────────────────────────────────────────────────

def _resolve_persons(r: Recipe, ctx: SolverContext) -> list[str]:
    """who → 対象 person_id のリスト（ctxに居る人だけ）。"""
    valid = set(ctx.person_ids)
    if r.who == "all":
        return list(ctx.person_ids)
    if r.who == "pair":
        return [p for p in (r.person_id, r.person_id_b) if p in valid]
    if r.who == "person":
        return [r.person_id] if r.person_id in valid else []
    if r.who == "role":
        return [p.id for p in ctx.masters.persons if p.role_id == r.role_id and p.id in valid]
    if r.who == "skill":
        return [p.id for p in ctx.masters.persons if r.skill_id in (p.skill_ids or []) and p.id in valid]
    return []


def _matching_day_indices(r: Recipe, ctx: SolverContext) -> list[int]:
    """when → 対象の day_index リスト。"""
    out = []
    for di, day in enumerate(ctx.days):
        if r.when == "always":
            out.append(di)
        elif r.when == "weekday" and r.weekday is not None and day.weekday() == r.weekday:
            out.append(di)
        elif r.when == "date" and r.date is not None and day == r.date:
            out.append(di)
        elif r.when == "date_range" and r.date_start and r.date_end and r.date_start <= day <= r.date_end:
            out.append(di)
    return out


def _matching_slots(r: Recipe, ctx: SolverContext):
    """band → 対象スロットのリスト。"""
    if r.band == "all_day":
        return list(ctx.slots)
    ws = hhmm_to_min(r.time_start) if r.time_start else 0
    we = hhmm_to_min(r.time_end) if r.time_end else 24 * 60
    return [s for s in ctx.slots if s.is_within(ws, we)]


def _positions(r: Recipe, ctx: SolverContext) -> list[str]:
    """where → 対象 position_id のリスト。"""
    if r.where == "position" and r.position_id is not None:
        return [r.position_id]
    return list(ctx.position_ids)


def _period_key(day: date, period: str):
    """limit_count の期間グルーピングキー。"""
    if period == "month":
        return (day.year, day.month)
    if period == "week":
        iso = day.isocalendar()
        return (iso[0], iso[1])
    return "total"


# ── 操作の適用 ──────────────────────────────────────────────────────

def apply_recipe(recipe, ctx: SolverContext) -> None:
    """レシピ（dict または Recipe）をソルバー制約に変換して ctx に適用する。"""
    r = recipe if isinstance(recipe, Recipe) else Recipe.model_validate(recipe)

    persons = _resolve_persons(r, ctx)
    days = _matching_day_indices(r, ctx)
    slots = _matching_slots(r, ctx)
    positions = _positions(r, ctx)

    if r.operation == "forbid":
        _apply_forbid(r, ctx, persons, days, slots)
    elif r.operation == "require":
        _apply_require(r, ctx, persons, days, slots, positions)
    elif r.operation == "limit_count":
        _apply_limit_count(r, ctx, persons, days, slots)
    elif r.operation == "penalize":
        _apply_penalize(r, ctx, persons, days, slots)
    elif r.operation == "prefer":
        _apply_prefer(r, ctx, persons, days, slots)


def _apply_forbid(r, ctx, persons, days, slots):
    """Hard: 対象の人を対象の枠に入れない。"""
    for pid in persons:
        for di in days:
            if r.band == "all_day":
                if (pid, di) in ctx.work_day:
                    ctx.model.Add(ctx.work_day[(pid, di)] == 0)
            else:
                for s in slots:
                    if (pid, di, s.index) in ctx.present:
                        ctx.model.Add(ctx.present[(pid, di, s.index)] == 0)


def _apply_require(r, ctx, persons, days, slots, positions):
    """Hard(best-effort): 対象範囲に最低 count 人。不足は大きく減点。"""
    count = r.count or 1
    target = set(persons)
    for di in days:
        for s in slots:
            for pos in positions:
                in_scope = [
                    ctx.x[(pid, di, s.index, pos)]
                    for pid in target
                    if (pid, di, s.index, pos) in ctx.x
                ]
                short = ctx.model.NewIntVar(0, count, f"req_short_{pos}_{di}_{s.index}")
                if in_scope:
                    ctx.model.Add(short >= count - sum(in_scope))
                else:
                    ctx.model.Add(short == count)
                ctx.add_shortage(SHORTAGE_PENALTY, short, {
                    "date": str(ctx.days[di]), "slot": f"{s.start}-{s.end}",
                    "position_id": pos, "required": count,
                })


def _apply_limit_count(r, ctx, persons, days, slots):
    """Hard: 「対象時間帯に入った日数」を期間ごとに max 回まで。"""
    max_count = r.max if r.max is not None else 0
    for pid in persons:
        # 期間 → その期間の「対象日に入ったか」boolリスト
        groups: dict = {}
        for di in days:
            present_vars = [
                ctx.present[(pid, di, s.index)]
                for s in slots
                if (pid, di, s.index) in ctx.present
            ]
            if not present_vars:
                continue
            active = ctx.model.NewBoolVar(f"lc_active_{pid}_{di}")
            for pv in present_vars:
                ctx.model.Add(active >= pv)   # 1コマでも入れば active=1
            key = _period_key(ctx.days[di], r.period)
            groups.setdefault(key, []).append(active)
        for actives in groups.values():
            ctx.model.Add(sum(actives) <= max_count)


def _apply_penalize(r, ctx, persons, days, slots):
    """Soft: 条件成立で weight の罰金。who=pair は同席に罰金。"""
    w = _clip_weight(r.weight)
    if r.who == "pair":
        if len(persons) < 2:
            return
        a, b = persons[0], persons[1]
        for di in days:
            if r.band == "all_day":
                if (a, di) in ctx.work_day and (b, di) in ctx.work_day:
                    z = ctx.model.NewBoolVar(f"pen_pair_{a}_{b}_{di}")
                    ctx.model.Add(z >= ctx.work_day[(a, di)] + ctx.work_day[(b, di)] - 1)
                    ctx.add_penalty(w, z)
            else:
                for s in slots:
                    if (a, di, s.index) in ctx.present and (b, di, s.index) in ctx.present:
                        z = ctx.model.NewBoolVar(f"pen_pair_{a}_{b}_{di}_{s.index}")
                        ctx.model.Add(z >= ctx.present[(a, di, s.index)] + ctx.present[(b, di, s.index)] - 1)
                        ctx.add_penalty(w, z)
        return
    # 個人系: 対象の枠に入ること自体に罰金
    for pid in persons:
        for di in days:
            if r.band == "all_day":
                if (pid, di) in ctx.work_day:
                    ctx.add_penalty(w, ctx.work_day[(pid, di)])
            else:
                for s in slots:
                    if (pid, di, s.index) in ctx.present:
                        ctx.add_penalty(w, ctx.present[(pid, di, s.index)])


def _apply_prefer(r, ctx, persons, days, slots):
    """Soft: 対象枠になるべく入れる（入らないと weight の罰金）。"""
    w = _clip_weight(r.weight)
    for pid in persons:
        for di in days:
            if r.band == "all_day":
                if (pid, di) in ctx.work_day:
                    nw = ctx.model.NewBoolVar(f"pref_{pid}_{di}")
                    ctx.model.Add(nw + ctx.work_day[(pid, di)] == 1)
                    ctx.add_penalty(w, nw)
            else:
                for s in slots:
                    if (pid, di, s.index) in ctx.present:
                        nv = ctx.model.NewBoolVar(f"pref_{pid}_{di}_{s.index}")
                        ctx.model.Add(nv + ctx.present[(pid, di, s.index)] == 1)
                        ctx.add_penalty(w, nv)
