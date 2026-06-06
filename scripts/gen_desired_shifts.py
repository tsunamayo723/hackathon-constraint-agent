"""
デモ用 出勤希望CSV（desired_shifts.csv）を3パターン分生成する

各パターン（cafe/restaurant/izakaya）の staff.csv を読み、対象期間の一部の日に
出勤可能枠を割り当てる。**note（日ごとの自由記述）も多めに付ける**
（将来の note のAI解釈デモ・B2b用のテストデータになる）。

列: person_id, date, start, end, note
実行: python scripts/gen_desired_shifts.py
"""

import csv
import random
from datetime import date, timedelta
from pathlib import Path

ROOT = Path("data/sample")
PATTERNS = ["pattern_a_cafe", "pattern_b_restaurant", "pattern_c_izakaya"]

PERIOD_START = date(2026, 11, 1)
PERIOD_DAYS = 30
OFFER_DAYS = 18           # 各人が出勤希望を出す日数（30日中）
NOTE_PROB = 0.30          # 各行に備考を付ける確率（多めに）

# 日ごとの備考（自然言語）。B2bでAIが解釈する想定のバリエーション。
NOTES = [
    "この日は3時間だけ",
    "18時までに上がりたい",
    "オープンだけ入れます",
    "夜のみ可",
    "昼過ぎから入りたい",
    "できれば早番",
    "お迎えがあるので17時まで",
    "テスト期間中なので短めに",
    "この日は遅番希望",
    "ラストまでOK",
    "ランチだけ手伝えます",
    "通院のため午前は不可",
]


def gen_for_pattern(folder: str, rng: random.Random) -> None:
    src = ROOT / folder / "staff.csv"
    out = ROOT / folder / "desired_shifts.csv"

    with src.open(encoding="utf-8") as f:
        person_ids = [row["id"] for row in csv.DictReader(f)]

    all_days = [PERIOD_START + timedelta(days=i) for i in range(PERIOD_DAYS)]

    # 出せる時間帯のバリエーション（人によってムラを出して難易度UP）
    windows = [
        ("11:00", "22:00"),  # 終日
        ("11:00", "17:00"),  # 早番
        ("16:00", "22:00"),  # 遅番
        ("11:00", "15:00"),  # 昼のみ
        ("18:00", "22:00"),  # 夜のみ
    ]
    # 人ごとの「出しやすさ」: よく出す人/たまにしか出さない人を作る
    window_weights = [0.40, 0.20, 0.20, 0.10, 0.10]

    rows: list[list] = []
    note_count = 0
    for pid in person_ids:
        # 出勤希望を出す日数を人ごとにばらつかせる（8〜24日）
        offer_days = rng.randint(8, min(24, len(all_days)))
        offered = rng.sample(all_days, k=offer_days)
        for d in sorted(offered):
            start, end = rng.choices(windows, weights=window_weights, k=1)[0]
            note = rng.choice(NOTES) if rng.random() < NOTE_PROB else ""
            if note:
                note_count += 1
            rows.append([pid, d.isoformat(), start, end, note])

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["person_id", "date", "start", "end", "note"])
        w.writerows(rows)

    print(f"[{folder}] {len(rows)}行 / {len(person_ids)}名 / note付き {note_count}行")


def main() -> None:
    # パターンごとに seed を変えて再現性を持たせる
    for i, folder in enumerate(PATTERNS):
        gen_for_pattern(folder, random.Random(100 + i))
    print("完了: 3パターンの desired_shifts.csv を生成しました")


if __name__ == "__main__":
    main()
