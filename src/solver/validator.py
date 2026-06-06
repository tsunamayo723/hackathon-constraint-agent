"""
シフト検証器（バリデータ）

ソルバーの出力（assignments）を、**元の生データ（SolverInput）から独立に再検算**して、
守られるべき「不変条件」が破られていないかを確認する。

ねらい:
- ソルバーを信用せず出力を検算し、「入れない人を入れた」等の致命的ミスを検出する。
- テスト段階で「良いシフト＝不変条件ゼロ違反」を機械的に保証する。

違反（あってはいけない＝0が正常）:
- out_of_availability : 本人の出勤希望枠の外に配置している
- double_booking      : 同じ人を同じ時間に2か所へ配置している
- out_of_hours        : 営業時間外に配置している
- invalid_id          : 存在しない person_id / position_id

要注意（運用上の警告）:
- 希望を1件も出していないスタッフ（＝配置対象外。希望を集めきれていない）
"""

from src.models.solver_io import SolverInput, SolverOutput, ValidationResult, Violation
from .slots import hhmm_to_min


def validate(spec: SolverInput, out: SolverOutput) -> ValidationResult:
    person_ids = {p.id for p in spec.masters.persons}
    position_ids = {p.id for p in spec.masters.positions}
    open_min = hhmm_to_min(spec.frame.operating_window.open)
    close_min = hhmm_to_min(spec.frame.operating_window.close)

    # 生データの出勤可能枠: (person_id, date) -> [(start_min, end_min), ...]
    windows: dict[tuple, list[tuple[int, int]]] = {}
    submitted: set[str] = set()
    for c in spec.constraints:
        if c.type == "availability":
            p = c.params
            windows.setdefault((p.person_id, p.date), []).append(
                (hhmm_to_min(p.start), hhmm_to_min(p.end))
            )
            submitted.add(p.person_id)

    violations: list[Violation] = []
    # 二重配置チェック用: (person_id, date) -> [(start_min, end_min), ...]
    by_person_day: dict[tuple, list[tuple[int, int]]] = {}

    for a in out.assignments:
        s = hhmm_to_min(a.start)
        e = hhmm_to_min(a.end)

        if a.person_id not in person_ids:
            violations.append(Violation(type="invalid_id", person_id=a.person_id,
                                        date=a.date, detail=f"存在しないスタッフID: {a.person_id}"))
        if a.position_id not in position_ids:
            violations.append(Violation(type="invalid_id", person_id=a.person_id,
                                        date=a.date, detail=f"存在しないポジションID: {a.position_id}"))

        if s < open_min or e > close_min:
            violations.append(Violation(type="out_of_hours", person_id=a.person_id, date=a.date,
                                        detail=f"営業時間外の配置: {a.start}-{a.end}"))

        # 出勤希望枠の外に配置していないか（希望を出した人のみ厳格チェック）
        if a.person_id in submitted:
            ws = windows.get((a.person_id, a.date), [])
            if not any(s >= w0 and e <= w1 for (w0, w1) in ws):
                violations.append(Violation(
                    type="out_of_availability", person_id=a.person_id, date=a.date,
                    detail=f"希望枠外の配置: {a.date} {a.start}-{a.end}",
                ))

        # 二重配置（同じ人・同じ日に時間が重なる別ブロック）
        key = (a.person_id, a.date)
        for (os_, oe) in by_person_day.get(key, []):
            if s < oe and os_ < e:  # 区間が重なる
                violations.append(Violation(
                    type="double_booking", person_id=a.person_id, date=a.date,
                    detail=f"同時刻に複数配置: {a.date} {a.start}-{a.end}",
                ))
                break
        by_person_day.setdefault(key, []).append((s, e))

    # 要注意: 希望を1件も出していないスタッフ（＝配置されない＝穴の温床）
    warnings: list[str] = []
    not_submitted = [p.name for p in spec.masters.persons if p.id not in submitted]
    if not_submitted:
        head = "、".join(not_submitted[:10]) + ("…" if len(not_submitted) > 10 else "")
        warnings.append(f"出勤希望が未提出のスタッフ {len(not_submitted)}名（配置対象外）: {head}")

    return ValidationResult(
        valid=len(violations) == 0,
        violation_count=len(violations),
        violations=violations,
        warnings=warnings,
    )
