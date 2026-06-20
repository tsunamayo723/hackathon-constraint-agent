"""
組み込みハンドラ（最小ソルバー版・3タイプ）

各ハンドラは「制約1件」を受け取り、SolverContext（作業台）に
OR-Tools の制約や罰金を書き足す。返り値はなし（副作用で組み立てる）。

  - headcount_requirement (Hard): 必要人数を「≧」制約で表現
  - availability        (Hard): 出勤可能枠を記録 → engineが枠外を0に固定
  - separate            (Soft): 同席したら罰金（weightは50〜1000にクリップ済み）

設計ルール:
  Hard = ソルバーが絶対遵守 / Soft = 罰金変数で表現（できれば避ける）
"""

from src.models.constraints import (
    AvailabilityParams,
    HeadcountParams,
    PreferPersonParams,
    SeparateParams,
)
from src.solver.context import SolverContext
from src.solver.slots import hhmm_to_min


# 必要人数の「不足」1人あたりの減点。ソフト制約(50〜1000)より十分大きくし、
# 「できるだけ必要人数を満たす」を最優先しつつ、満たせない時は不足を最小化した暫定解を出す。
HEADCOUNT_SHORTAGE_PENALTY = 5000


def handle_headcount(params: HeadcountParams, ctx: SolverContext) -> None:
    """
    「この時間帯・このポジションに count 人」を **Soft（不足は減点）** で表現する。

    Hardにすると人が足りない時にシフト自体が作れなくなる（infeasible）。
    そこで「不足人数」を変数化して大きく減点し、**解けない状況でも
    不足を最小化した暫定シフトを必ず出力**できるようにする。
    """
    win_start = hhmm_to_min(params.time_start)
    win_end = hhmm_to_min(params.time_end)

    for di, day in enumerate(ctx.days):
        # 特定日付の指定があれば、その日以外はスキップ（省略時は全日に適用）
        if params.date is not None and day != params.date:
            continue
        for slot in ctx.slots:
            if not slot.is_within(win_start, win_end):
                continue
            in_position = [
                ctx.x[(pid, di, slot.index, params.position_id)]
                for pid in ctx.person_ids
                if (pid, di, slot.index, params.position_id) in ctx.x
            ]
            # 不足変数 short ≧ 必要人数 − 配置人数（0以上）
            short = ctx.model.NewIntVar(0, params.count, f"short_{params.position_id}_{di}_{slot.index}")
            if in_position:
                ctx.model.Add(short >= params.count - sum(in_position))
            else:
                ctx.model.Add(short == params.count)  # 配置できる変数が無い→全不足
            ctx.add_shortage(HEADCOUNT_SHORTAGE_PENALTY, short, {
                "date": str(day),
                "slot": f"{slot.start}-{slot.end}",
                "position_id": params.position_id,
                "required": params.count,
            })


def handle_availability(params: AvailabilityParams, ctx: SolverContext) -> None:
    """
    「その人がその日、この時間だけ入れる」を記録する。

    ここでは枠を ctx.availability に貯めるだけ。
    実際に「枠外を0に固定」するのは、全ハンドラ実行後に engine が行う
    （ある人の全可用枠が出そろってから複合判定する必要があるため）。
    """
    if params.person_id not in ctx.person_ids:
        return
    if params.date not in ctx.days:
        return  # 対象期間外の希望は無視

    di = ctx.days.index(params.date)
    start_min = hhmm_to_min(params.start)
    end_min = hhmm_to_min(params.end)

    person_windows = ctx.availability.setdefault(params.person_id, {})
    person_windows.setdefault(di, []).append((start_min, end_min))


def handle_separate(params: SeparateParams, ctx: SolverContext) -> None:
    """
    「AさんとBさんはできれば同席させない」を Soft 制約（罰金）にする。

    同じスコープ（日 or コマ）に両者が入ったら weight 分の罰金。
    罰金変数 z は z ≧ (Aいる) + (Bいる) − 1 で表現し、目的関数で最小化する。
    """
    a, b = params.person_a, params.person_b
    if a not in ctx.person_ids or b not in ctx.person_ids:
        return

    if params.scope == "day":
        for di, _day in enumerate(ctx.days):
            z = ctx.model.NewBoolVar(f"sep_day_{a}_{b}_{di}")
            ctx.model.Add(z >= ctx.work_day[(a, di)] + ctx.work_day[(b, di)] - 1)
            ctx.add_penalty(params.weight, z)
    else:  # scope == "slot"
        for di, _day in enumerate(ctx.days):
            for slot in ctx.slots:
                z = ctx.model.NewBoolVar(f"sep_slot_{a}_{b}_{di}_{slot.index}")
                ctx.model.Add(
                    z
                    >= ctx.present[(a, di, slot.index)]
                    + ctx.present[(b, di, slot.index)]
                    - 1
                )
                ctx.add_penalty(params.weight, z)


def handle_prefer_person(params: PreferPersonParams, ctx: SolverContext) -> None:
    """
    「その人をできるだけ多く配置する」を Soft 制約（罰金）にする。

    本人が**出勤可能な日に働いていない**と weight 分の罰金。
    ＝「入れるなら入りたい」人を優先配置する（提出者の希望を立てるのに使う）。
    可用枠を出していない日は対象外（無理に入れない）。
    ※ availability より後に処理されることを前提（ctx.availability が埋まっている）。
    """
    pid = params.person_id
    if pid not in ctx.person_ids:
        return
    day_windows = ctx.availability.get(pid)
    if not day_windows:
        return
    for di in day_windows:
        notwork = ctx.model.NewBoolVar(f"prefer_{pid}_{di}")
        ctx.model.Add(notwork + ctx.work_day[(pid, di)] == 1)  # 働かない日=1
        ctx.add_penalty(params.weight, notwork)
