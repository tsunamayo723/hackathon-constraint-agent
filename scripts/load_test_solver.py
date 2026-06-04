"""
最小ソルバーの負荷テスト（本番規模: 30名 × 1ヶ月）

目的: デモ本番サイズで「現実的な時間で解けるか（速度）」を確認する。
実在の30名サンプル（pattern_b_restaurant）を使い、現実的な制約を載せて計測する。

実行: python scripts/load_test_solver.py
"""

import csv
import random
import time
from datetime import date
from pathlib import Path

from src.models.solver_io import SolverInput
from src.solver.engine import solve

SAMPLE = Path("data/sample/pattern_b_restaurant")


def load_masters() -> dict:
    """サンプルCSVからマスタを組み立てる。"""
    def rows(name):
        with (SAMPLE / name).open(encoding="utf-8") as f:
            return list(csv.DictReader(f))

    persons = []
    for r in rows("staff.csv"):
        persons.append({
            "id": r["id"],
            "name": r["name"],
            "role_id": r["role_id"] or None,
            "skill_ids": [s for s in r["skill_ids"].split(";") if s],
        })
    return {
        "persons": persons,
        "positions": rows("positions.csv"),
        "roles": rows("roles.csv"),
        "skills": rows("skills.csv"),
    }


def build_constraints(person_ids: list[str], days: list[date]) -> list[dict]:
    """現実的な制約セットを生成する。"""
    rng = random.Random(2026)
    constraints: list[dict] = []

    # ① 必要人数（ランチ/ディナー × ポジション）
    headcounts = [
        ("ランチ", "11:00", "14:00", "pos_hall", 3),
        ("ランチ", "11:00", "14:00", "pos_kitchen", 2),
        ("ランチ", "11:00", "14:00", "pos_register", 1),
        ("ディナー", "18:00", "22:00", "pos_hall", 4),
        ("ディナー", "18:00", "22:00", "pos_kitchen", 2),
        ("ディナー", "18:00", "22:00", "pos_register", 1),
    ]
    for label, ts, te, pos, cnt in headcounts:
        constraints.append({
            "type": "headcount_requirement",
            "params": {"slot_label": label, "time_start": ts, "time_end": te,
                       "position_id": pos, "count": cnt},
        })

    # ② 出勤希望（availability）: 各人が30日中ランダムに約22日、全枠を希望
    for pid in person_ids:
        offered_days = rng.sample(days, k=22)
        for d in offered_days:
            constraints.append({
                "type": "availability",
                "params": {"person_id": pid, "date": d.isoformat(),
                           "start": "11:00", "end": "22:00"},
            })

    # ③ separate（同席を避けたいペア）を5組
    for _ in range(5):
        a, b = rng.sample(person_ids, 2)
        constraints.append({
            "type": "separate",
            "params": {"person_a": a, "person_b": b, "scope": "day", "weight": 500},
        })

    return constraints


def run(slot_minutes: int) -> None:
    masters = load_masters()
    person_ids = [p["id"] for p in masters["persons"]]

    frame = {
        "period": {"start": "2026-11-01", "end": "2026-11-30"},
        "operating_window": {"open": "11:00", "close": "22:00", "slot_minutes": slot_minutes},
        "policy_mode": "balance",
    }

    spec_dict = {"frame": frame, "masters": masters,
                 "constraints": None}  # constraints は下で日付確定後に作る

    spec_tmp = SolverInput.model_validate({**spec_dict, "constraints": []})
    from src.solver.slots import date_range
    days = date_range(spec_tmp.frame.period.start, spec_tmp.frame.period.end)

    constraints = build_constraints(person_ids, days)
    spec = SolverInput.model_validate({**spec_dict, "constraints": constraints})

    n_persons = len(person_ids)
    n_days = len(days)
    n_pos = len(masters["positions"])
    from src.solver.slots import build_day_slots
    n_slots = len(build_day_slots("11:00", "22:00", slot_minutes))

    print(f"\n{'='*60}")
    print(f"slot_minutes={slot_minutes}  →  1日{n_slots}コマ")
    print(f"規模: {n_persons}名 × {n_days}日 × {n_slots}コマ × {n_pos}ポジション")
    print(f"  おおよその割当変数 x ≒ {n_persons*n_days*n_slots*n_pos:,} 個")
    print(f"  制約数: {len(constraints)}（うちavailability {n_persons*22}件）")
    print(f"{'='*60}")

    t0 = time.perf_counter()
    out = solve(spec)
    elapsed = time.perf_counter() - t0

    print(f"結果 status: {out.status} / shift_status: {out.shift_status}")
    print(f"割当(マージ後)ブロック数: {len(out.assignments)}")
    if out.meta:
        print(f"目的関数値: {out.meta.objective}")
    print(f"[実時間] {elapsed:.2f} 秒")
    if out.warnings:
        print(f"警告: {[w.type for w in out.warnings]}")


if __name__ == "__main__":
    # 本番デモ想定の60分コマでまず計測。十分速ければ30分コマも試す。
    run(slot_minutes=60)
    run(slot_minutes=30)
