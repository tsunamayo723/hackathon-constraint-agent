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
    SeparateParams,
)
from src.solver.context import SolverContext
from src.solver.slots import hhmm_to_min


def handle_headcount(params: HeadcountParams, ctx: SolverContext) -> None:
    """
    「この時間帯・このポジションに count 人」を Hard 制約にする。

    対象時間帯に重なる各コマについて、そのポジションに入る人数の合計 ≧ count。
    """
    win_start = hhmm_to_min(params.time_start)
    win_end = hhmm_to_min(params.time_end)

    for di, _day in enumerate(ctx.days):
        for slot in ctx.slots:
            if not slot.is_within(win_start, win_end):
                continue
            # そのコマ・そのポジションに入る全員の合計
            in_position = [
                ctx.x[(pid, di, slot.index, params.position_id)]
                for pid in ctx.person_ids
                if (pid, di, slot.index, params.position_id) in ctx.x
            ]
            if in_position:
                ctx.model.Add(sum(in_position) >= params.count)
            else:
                # 変数が1つも無い（ポジション未定義など）→ 必ず詰まる
                ctx.model.Add(0 >= params.count)


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
