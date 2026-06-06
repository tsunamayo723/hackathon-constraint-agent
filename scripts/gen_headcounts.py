"""
デモ用 必要人数CSV（headcounts.csv）を3パターン分生成する

- 時間帯を増やす（ランチ / アイドル / ディナー）＝「パート数」を増やして難易度UP。
- **特定日付の上書き行**（date列）を入れて、日によって必要人数が変わるようにする。
  date 空＝毎日適用 / 日付あり＝その日だけ適用（繁忙日・イベント日）。

列: date, slot_label, time_start, time_end, position_id, count
実行: python scripts/gen_headcounts.py
"""

import csv
from pathlib import Path

ROOT = Path("data/sample")

# 時間帯（slot_label, time_start, time_end）
BANDS = {
    "lunch": ("ランチ", "11:00", "14:00"),
    "idle": ("アイドル", "14:00", "17:00"),
    "dinner": ("ディナー", "17:00", "22:00"),
}

# パターンごとの基本需要: { band: { position_id: count } }
BASE = {
    "pattern_a_cafe": {
        "lunch": {"pos_counter": 1, "pos_floor": 2},
        "dinner": {"pos_counter": 1, "pos_floor": 2},
    },
    "pattern_b_restaurant": {
        "lunch": {"pos_hall": 3, "pos_kitchen": 2, "pos_register": 1},
        "idle": {"pos_hall": 1, "pos_kitchen": 1},
        "dinner": {"pos_hall": 4, "pos_kitchen": 3, "pos_register": 1},
    },
    "pattern_c_izakaya": {
        "lunch": {"pos_hall": 3, "pos_kitchen": 2, "pos_drink": 1, "pos_cashier": 1},
        "idle": {"pos_hall": 1, "pos_kitchen": 1, "pos_drink": 1},
        "dinner": {"pos_hall": 6, "pos_kitchen": 4, "pos_drink": 2, "pos_cashier": 2},
    },
}

# 特定日付の上書き需要（デモ期間 2026-11-01〜07 内の日付を使う）: { (date, band): {pos: count} }
OVERRIDE = {
    "pattern_b_restaurant": {
        ("2026-11-03", "dinner"): {"pos_hall": 6, "pos_kitchen": 4},          # 繁忙日
        ("2026-11-07", "lunch"): {"pos_hall": 5, "pos_kitchen": 3},           # イベント日（昼）
        ("2026-11-07", "dinner"): {"pos_hall": 7, "pos_kitchen": 4, "pos_register": 2},
    },
    "pattern_c_izakaya": {
        ("2026-11-07", "dinner"): {"pos_hall": 8, "pos_kitchen": 5, "pos_drink": 3, "pos_cashier": 2},
    },
}


def gen(folder: str) -> None:
    out = ROOT / folder / "headcounts.csv"
    rows: list[list] = []

    # 基本需要（date 空＝毎日）
    for band, demand in BASE[folder].items():
        label, ts, te = BANDS[band]
        for pos, count in demand.items():
            rows.append(["", label, ts, te, pos, count])

    # 特定日付の上書き
    for (d, band), demand in OVERRIDE.get(folder, {}).items():
        label, ts, te = BANDS[band]
        for pos, count in demand.items():
            rows.append([d, label, ts, te, pos, count])

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "slot_label", "time_start", "time_end", "position_id", "count"])
        w.writerows(rows)
    base_n = sum(1 for r in rows if r[0] == "")
    ovr_n = len(rows) - base_n
    print(f"[{folder}] {len(rows)}行（基本{base_n} / 日付上書き{ovr_n}）")


def main() -> None:
    for folder in BASE:
        gen(folder)
    print("完了: 3パターンの headcounts.csv を生成しました")


if __name__ == "__main__":
    main()
