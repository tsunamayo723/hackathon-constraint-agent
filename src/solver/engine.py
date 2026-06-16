"""
ソルバーエンジン（OR-Tools CP-SAT）

SolverInput → 変数組み立て → ハンドラで制約付与 → 求解 → SolverOutput。

OR-Tools 本体（CpModel / CpSolver）はここでだけ触る。
個々の制約の翻訳はハンドラに任せ、ここは「土台作りと求解」に専念する。
"""

import logging
import time
from datetime import date

from ortools.sat.python import cp_model

from src.handlers import get_handler
from src.models.parser_io import UntranslatedConstraint
from src.models.solver_io import (
    Assignment,
    BlockingConstraint,
    PositionCoverage,
    ShiftEvaluation,
    SolverInput,
    SolverMeta,
    SolverOutput,
    SolverWarning,
    StaffStat,
)
from .context import SolverContext
from .slots import Slot, build_day_slots, date_range

logger = logging.getLogger("uvicorn.error")
from .validator import validate

# 求解の打ち切り時間（秒）。デモ規模なら十分。
TIME_LIMIT_SEC = 10.0
DEFAULT_SEED = 42


def solve(
    spec: SolverInput,
    pending: list[UntranslatedConstraint] | None = None,
) -> SolverOutput:
    """
    シフトを計算する。

    pending（未翻訳の要望）が非空なら、結果は「暫定版（provisional）」になる。
    """
    pending = pending or []
    started = time.perf_counter()

    days = date_range(spec.frame.period.start, spec.frame.period.end)
    slots = build_day_slots(
        spec.frame.operating_window.open,
        spec.frame.operating_window.close,
        spec.frame.operating_window.slot_minutes,
    )

    model = cp_model.CpModel()
    ctx = SolverContext(model=model, days=days, slots=slots, masters=spec.masters)

    _build_variables(ctx)

    # ── ハンドラ実行（type → 制約翻訳） ──────────────────────────
    warnings: list[SolverWarning] = []
    for c in spec.constraints:
        handler = get_handler(c.type)
        if handler is None:
            # 最小ソルバー未対応のタイプ。黙って捨てず警告で明示する。
            warnings.append(SolverWarning(type=f"unhandled:{c.type}"))
            continue
        handler(c.params, ctx)

    # 動的タイプ（AIが生成・承認した新type）。登録済みハンドラがあれば適用。
    for dc in spec.dynamic_constraints:
        dtype = dc.get("type", "")
        handler = get_handler(dtype)
        if handler is None:
            # 未承認/未登録の新type → 黙って捨てず警告で明示
            warnings.append(SolverWarning(type=f"unregistered:{dtype}"))
            continue
        try:
            handler(dc.get("params", {}), ctx)
        except Exception as exc:
            # AI生成ハンドラの実行時バグでソルバー全体を落とさない。
            # その制約だけ諦め、警告で正直に可視化する（→ 再生成を促す）。
            logger.warning("動的ハンドラ '%s' の実行に失敗: %s", dtype, exc)
            warnings.append(SolverWarning(type=f"handler_error:{dtype}"))

    # availability は全件出そろってから適用（枠外コマを0に固定）
    _apply_availability(ctx)

    # ── 目的関数 ────────────────────────────────────────────────
    # 必要人数の不足ペナルティ（最優先で小さく）＋ソフト罰金＋総割当数（過剰配置抑制）
    penalty_terms = [w * z for (w, z) in ctx.penalties]
    shortage_terms = [w * z for (w, z) in ctx.shortages]
    total_assigned = list(ctx.x.values())
    model.Minimize(sum(shortage_terms) + sum(penalty_terms) + sum(total_assigned))

    # ── 求解 ────────────────────────────────────────────────────
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = TIME_LIMIT_SEC
    solver.parameters.random_seed = DEFAULT_SEED
    result = solver.Solve(model)

    elapsed_ms = int((time.perf_counter() - started) * 1000)

    shift_status = "provisional" if pending else "confirmed"

    if result in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        assignments = _extract_assignments(ctx, solver)
        soft_penalty = sum(w * solver.Value(z) for (w, z) in ctx.penalties)
        shortage_penalty = sum(w * solver.Value(z) for (w, z) in ctx.shortages)
        assignment_units = sum(solver.Value(x) for x in ctx.x.values())
        warnings += _understaffed_warnings(ctx, solver)

        # 充足率ベースの100点満点スコア
        required_units = sum(info["required"] for _, info in ctx.shortage_info)
        shortage_units = sum(solver.Value(var) for var, _ in ctx.shortage_info)
        coverage_score = (
            100.0 if required_units == 0
            else round((required_units - shortage_units) / required_units * 100, 1)
        )

        output = SolverOutput(
            status="solved",
            shift_status=shift_status,
            meta=SolverMeta(
                seed=DEFAULT_SEED,
                elapsed_ms=elapsed_ms,
                objective=int(solver.ObjectiveValue()),
                soft_penalty=int(soft_penalty),
                shortage_penalty=int(shortage_penalty),
                assignment_units=int(assignment_units),
                required_units=int(required_units),
                shortage_units=int(shortage_units),
                coverage_score=coverage_score,
            ),
            assignments=assignments,
            warnings=warnings,
            pending_constraints=pending,
            evaluation=_evaluate(ctx, solver, coverage_score),
        )
        # 出力を生データから独立に再検算（不変条件チェック）
        output.validation = validate(spec, output)
        return output

    if result == cp_model.INFEASIBLE:
        return SolverOutput(
            status="infeasible",
            shift_status=shift_status,
            meta=SolverMeta(seed=DEFAULT_SEED, elapsed_ms=elapsed_ms, objective=0),
            warnings=warnings,
            blocking_constraints=_diagnose_infeasible(spec, ctx),
            pending_constraints=pending,
        )

    # UNKNOWN / MODEL_INVALID 等は時間切れ扱いにまとめる
    return SolverOutput(
        status="timeout",
        shift_status=shift_status,
        meta=SolverMeta(seed=DEFAULT_SEED, elapsed_ms=elapsed_ms, objective=0),
        warnings=warnings,
        pending_constraints=pending,
    )


# ═══════════════════════════════════════════════════════════════════
#  内部ヘルパー
# ═══════════════════════════════════════════════════════════════════


def _build_variables(ctx: SolverContext) -> None:
    """割当変数 x / 在席 present / 出勤 work_day を作り、関係を結ぶ。"""
    model = ctx.model

    for pi, pid in enumerate(ctx.person_ids):
        for di in range(len(ctx.days)):
            day_present_vars = []
            for slot in ctx.slots:
                # この人・この日・このコマの、各ポジションへの割当
                pos_vars = []
                for pos_id in ctx.position_ids:
                    v = model.NewBoolVar(f"x_{pid}_{di}_{slot.index}_{pos_id}")
                    ctx.x[(pid, di, slot.index, pos_id)] = v
                    pos_vars.append(v)

                # 在席 = 各ポジション割当の合計（==present で1コマ1ポジションを強制）
                present = model.NewBoolVar(f"present_{pid}_{di}_{slot.index}")
                model.Add(sum(pos_vars) == present)
                ctx.present[(pid, di, slot.index)] = present
                day_present_vars.append(present)

            # 出勤 = その日のいずれかのコマに在席（OR）
            wd = model.NewBoolVar(f"workday_{pid}_{di}")
            model.AddMaxEquality(wd, day_present_vars)
            ctx.work_day[(pid, di)] = wd


def _apply_availability(ctx: SolverContext) -> None:
    """
    出勤希望ベースの固定（厳格）。

    「出した枠の中だけ」入れる。**希望を1件も出していない人は出勤不可**として扱い、
    全コマ present=0 に固定する（＝『入れない人を入れる』を原理的に起こさない）。
    足りなければ穴は穴として正直に出す（headcountはSoftなので不足が計上される）。
    """
    for pid in ctx.person_ids:
        day_windows = ctx.availability.get(pid)  # 未提出の人は None
        for di in range(len(ctx.days)):
            windows = day_windows.get(di) if day_windows else None
            for slot in ctx.slots:
                allowed = bool(windows) and any(slot.is_within(s, e) for (s, e) in windows)
                if not allowed:
                    ctx.model.Add(ctx.present[(pid, di, slot.index)] == 0)


def _extract_assignments(ctx: SolverContext, solver: cp_model.CpSolver) -> list[Assignment]:
    """
    解から割当を取り出す。読みやすさのため、同じ人・同じポジションで
    連続するコマは1つの勤務ブロックにまとめる。
    """
    assignments: list[Assignment] = []

    for pid in ctx.person_ids:
        for di, day in enumerate(ctx.days):
            for pos_id in ctx.position_ids:
                # この人・この日・このポジションで割当のあるコマを時系列に集める
                on_slots = [
                    slot
                    for slot in ctx.slots
                    if solver.Value(ctx.x[(pid, di, slot.index, pos_id)]) == 1
                ]
                if not on_slots:
                    continue
                # 連続するコマをまとめる
                for block in _merge_consecutive(on_slots):
                    assignments.append(Assignment(
                        date=day,
                        person_id=pid,
                        position_id=pos_id,
                        start=block[0].start,
                        end=block[-1].end,
                    ))
    return assignments


def _merge_consecutive(on_slots: list[Slot]) -> list[list[Slot]]:
    """時刻順のコマ列を、隣り合うものごとのブロックに分割する。"""
    on_slots = sorted(on_slots, key=lambda s: s.start_min)
    blocks: list[list[Slot]] = []
    for slot in on_slots:
        if blocks and blocks[-1][-1].end_min == slot.start_min:
            blocks[-1].append(slot)
        else:
            blocks.append([slot])
    return blocks


def _evaluate(ctx: SolverContext, solver: cp_model.CpSolver, coverage_score: float) -> ShiftEvaluation:
    """完成シフトの評価指標（ポジション別充足・スタッフ別稼働・公平性・ソフト違反）を集計する。"""
    name_of = {p.id: p.name for p in ctx.masters.persons}

    # ① ポジション別の充足率
    pos_req: dict[str, int] = {}
    pos_short: dict[str, int] = {}
    for var, info in ctx.shortage_info:
        pid = info["position_id"]
        pos_req[pid] = pos_req.get(pid, 0) + info["required"]
        pos_short[pid] = pos_short.get(pid, 0) + solver.Value(var)
    position_coverage = []
    for pid, req in pos_req.items():
        filled = req - pos_short.get(pid, 0)
        position_coverage.append(PositionCoverage(
            position_id=pid, required=req, filled=filled,
            rate=round(filled / req * 100, 1) if req else 100.0,
        ))

    # ② スタッフ別の稼働・出勤希望消化率
    staff_stats: list[StaffStat] = []
    assigned_list: list[int] = []
    for pid in ctx.person_ids:
        assigned = sum(
            solver.Value(ctx.present[(pid, di, slot.index)])
            for di in range(len(ctx.days)) for slot in ctx.slots
        )
        work_days = sum(solver.Value(ctx.work_day[(pid, di)]) for di in range(len(ctx.days)))

        # 出した枠（availability）のコマ数。希望を出していない人（無制限）は None。
        offered = None
        util = None
        day_windows = ctx.availability.get(pid)
        if day_windows is not None:
            offered = sum(
                1
                for di, windows in day_windows.items()
                for slot in ctx.slots
                if any(slot.is_within(s, e) for (s, e) in windows)
            )
            util = round(assigned / offered * 100, 1) if offered else 0.0

        assigned_list.append(assigned)
        staff_stats.append(StaffStat(
            person_id=pid, name=name_of.get(pid, pid),
            assigned_slots=assigned, work_days=work_days,
            offered_slots=offered, utilization=util,
        ))

    # ③ 公平性（出勤コマ数の散らばり）
    fair_min = min(assigned_list) if assigned_list else 0
    fair_max = max(assigned_list) if assigned_list else 0
    fair_avg = round(sum(assigned_list) / len(assigned_list), 1) if assigned_list else 0.0

    # ④ ソフト制約（separate等）の違反件数
    soft_violations = sum(1 for (_w, z) in ctx.penalties if solver.Value(z) > 0)

    return ShiftEvaluation(
        coverage_score=coverage_score,
        position_coverage=position_coverage,
        staff_stats=staff_stats,
        fair_min=fair_min, fair_max=fair_max, fair_avg=fair_avg,
        soft_violations=soft_violations,
    )


def _understaffed_warnings(ctx: SolverContext, solver: cp_model.CpSolver) -> list[SolverWarning]:
    """解の中で必要人数に届かなかったコマを警告にする（暫定シフトの不足箇所）。"""
    warnings: list[SolverWarning] = []
    for short_var, info in ctx.shortage_info:
        v = solver.Value(short_var)
        if v > 0:
            warnings.append(SolverWarning(
                type="understaffed",
                affected_date=info["date"],
                affected_time=f"{info['slot']} / {info['position_id']}",
                shortage=v,
            ))
            if len(warnings) >= 20:  # 多すぎると読みにくいので打ち切り
                break
    return warnings


def _is_available(ctx: SolverContext, pid: str, di: int, slot: Slot) -> bool:
    """診断用: その人がそのコマに入れる可能性があるか（厳格: 未提出は不可）。"""
    day_windows = ctx.availability.get(pid)
    if day_windows is None:
        return False  # 希望未提出＝出勤不可
    windows = day_windows.get(di)
    if not windows:
        return False
    return any(slot.is_within(s, e) for (s, e) in windows)


def _diagnose_infeasible(spec: SolverInput, ctx: SolverContext) -> list[BlockingConstraint]:
    """
    充足不能のとき、headcount のどこで人が足りないかを簡易診断する。
    （厳密な証明ではなく、よくある「可用人数 < 必要人数」を探す）
    """
    from src.solver.slots import hhmm_to_min

    blocking: list[BlockingConstraint] = []
    for c in spec.constraints:
        if c.type != "headcount_requirement":
            continue
        p = c.params
        win_start = hhmm_to_min(p.time_start)
        win_end = hhmm_to_min(p.time_end)
        for di, day in enumerate(ctx.days):
            for slot in ctx.slots:
                if not slot.is_within(win_start, win_end):
                    continue
                pool = sum(
                    1 for pid in ctx.person_ids if _is_available(ctx, pid, di, slot)
                )
                if pool < p.count:
                    blocking.append(BlockingConstraint(
                        type="understaffed",
                        where={
                            "date": str(day),
                            "slot": f"{slot.start}-{slot.end}",
                            "position_id": p.position_id,
                        },
                        detail=f"必要{p.count}名に対し可用{pool}名",
                    ))
                    if len(blocking) >= 10:  # 多すぎると読みにくいので打ち切り
                        return blocking
    return blocking
