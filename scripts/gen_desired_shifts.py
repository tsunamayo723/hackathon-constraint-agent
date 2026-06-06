"""
デモ用 出勤希望CSV（desired_shifts.csv）を生成する

pattern_b_restaurant（30名）の各スタッフについて、対象期間の一部の日に
出勤可能枠を割り当てる。一部の行には日ごとの備考(note)も付ける（将来のnote解釈用）。

列: person_id, date, start, end, note
実行: python scripts/gen_desired_shifts.py
"""

import csv
import random
from datetime import date, timedelta
from pathlib import Path

SRC = Path("data/sample/pattern_b_restaurant/staff.csv")
OUT = Path("data/sample/pattern_b_restaurant/desired_shifts.csv")

PERIOD_START = date(2026, 11, 1)
PERIOD_DAYS = 30
OFFER_DAYS = 18          # 各人が出勤希望を出す日数（30日中）
NOTES = ["この日は3時間だけ", "夕方から入りたい", "お迎えがあるので18時まで", "早番希望"]


def main() -> None:
    rng = random.Random(42)

    with SRC.open(encoding="utf-8") as f:
        person_ids = [row["id"] for row in csv.DictReader(f)]

    all_days = [PERIOD_START + timedelta(days=i) for i in range(PERIOD_DAYS)]

    rows: list[list] = []
    for pid in person_ids:
        offered = rng.sample(all_days, k=OFFER_DAYS)
        for d in sorted(offered):
            # たまに時間帯を変える / たまに備考を付ける
            start, end = "11:00", "22:00"
            note = ""
            if rng.random() < 0.15:
                start, end = "17:00", "22:00"
            if rng.random() < 0.10:
                note = rng.choice(NOTES)
            rows.append([pid, d.isoformat(), start, end, note])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["person_id", "date", "start", "end", "note"])
        w.writerows(rows)

    print(f"生成: {OUT}（{len(rows)}行 / {len(person_ids)}名 × 約{OFFER_DAYS}日）")


if __name__ == "__main__":
    main()
