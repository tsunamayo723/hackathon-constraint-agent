"""
サンプルCSV（全パターン）にデモ用の「ルール系note」を仕込む

未知タイプ検出（T1）のデモ用。各パターンで「note空き行を持つスタッフ」を
4人選び、1人1件ずつルール系noteを設定する。
実行: python scripts/add_demo_notes.py
※ scripts/gen_desired_shifts.py で再生成すると消えるので、再生成後はもう一度実行する。
"""

import pandas as pd

PATHS = [
    "data/sample/pattern_a_cafe/desired_shifts.csv",
    "data/sample/pattern_b_restaurant/desired_shifts.csv",
    "data/sample/pattern_c_izakaya/desired_shifts.csv",
]

RULE_NOTES = [
    "毎週水曜は習い事があって入れません",          # → recurring_day_off
    "毎週水曜は大学の授業で入れません",            # → recurring_day_off（集約の見どころ）
    "12/10〜20が試験期間なので極力入れないでください",  # → exam_period
    "22時以降のシフトは月3回までにしてほしいです",      # → max_late_shift_count
]


def seed(path: str) -> None:
    print(f"--- {path}")
    df = pd.read_csv(path, dtype=str).fillna("")

    # 既に仕込み済みならスキップ
    if df["note"].isin(RULE_NOTES).any():
        print("  スキップ（設定済み）")
        return

    # note空き行を持つスタッフを順に4人選び、1人1件ずつ設定
    persons = [p for p in df["person_id"].unique() if (df["person_id"].eq(p) & df["note"].eq("")).any()]
    if len(persons) < len(RULE_NOTES):
        print(f"  !! note空き行を持つスタッフが{len(persons)}人しかいません")
    for pid, note in zip(persons, RULE_NOTES):
        idx = df[(df["person_id"] == pid) & (df["note"] == "")].index[0]
        df.loc[idx, "note"] = note
        print(f"  {pid} {df.loc[idx, 'date']} に設定:「{note}」")

    df.to_csv(path, index=False)
    print("  保存OK")


if __name__ == "__main__":
    for p in PATHS:
        seed(p)
