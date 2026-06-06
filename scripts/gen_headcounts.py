"""
デモ用 必要人数CSV（headcounts.csv）を3パターン分生成する

各パターンの positions に対し、ランチ／ディナーの必要人数を設定する。
「簡単すぎない」よう、複数ポジション×2時間帯で、スタッフ規模に対して
そこそこ厳しめの需要にする（出勤希望や希望制約が効くように）。

列: slot_label, time_start, time_end, position_id, count
実行: python scripts/gen_headcounts.py
"""

import csv
from pathlib import Path

ROOT = Path("data/sample")

# パターンごとの需要: position_id -> (ランチ人数, ディナー人数)
DEMAND = {
    "pattern_a_cafe": {
        "pos_counter": (1, 1),
        "pos_floor": (2, 3),
    },
    "pattern_b_restaurant": {
        "pos_hall": (3, 5),
        "pos_kitchen": (2, 3),
        "pos_register": (1, 1),
    },
    "pattern_c_izakaya": {
        "pos_hall": (3, 6),
        "pos_kitchen": (2, 4),
        "pos_drink": (1, 2),
        "pos_cashier": (1, 2),
    },
}

LUNCH = ("ランチ", "11:00", "14:00")
DINNER = ("ディナー", "18:00", "22:00")


def gen(folder: str, demand: dict) -> None:
    out = ROOT / folder / "headcounts.csv"
    rows = []
    for pos_id, (lunch_n, dinner_n) in demand.items():
        if lunch_n > 0:
            rows.append([LUNCH[0], LUNCH[1], LUNCH[2], pos_id, lunch_n])
        if dinner_n > 0:
            rows.append([DINNER[0], DINNER[1], DINNER[2], pos_id, dinner_n])
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["slot_label", "time_start", "time_end", "position_id", "count"])
        w.writerows(rows)
    total_lunch = sum(d[0] for d in demand.values())
    total_dinner = sum(d[1] for d in demand.values())
    print(f"[{folder}] {len(rows)}行 / ランチ計{total_lunch}名・ディナー計{total_dinner}名")


def main() -> None:
    for folder, demand in DEMAND.items():
        gen(folder, demand)
    print("完了: 3パターンの headcounts.csv を生成しました")


if __name__ == "__main__":
    main()
