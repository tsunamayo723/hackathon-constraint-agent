"""
サンプルCSV（pattern_b）にデモ用の「ルール系note」を仕込む

未知タイプ検出（T1）のデモ用。その人の最初のnote空き行に設定する。
実行: python scripts/add_demo_notes.py
※ scripts/gen_desired_shifts.py で再生成すると消えるので、再生成後はもう一度実行する。
"""

import pandas as pd

PATH = "data/sample/pattern_b_restaurant/desired_shifts.csv"

RULES = [
    ("p07", "毎週水曜は習い事があって入れません"),
    ("p10", "毎週水曜は大学の授業で入れません"),        # → p07と同じtypeに集約されるはず
    ("p15", "12/10〜20が試験期間なので極力入れないでください"),
    ("p20", "22時以降のシフトは月3回までにしてほしいです"),
]


def main():
    df = pd.read_csv(PATH, dtype=str).fillna("")
    for pid, note in RULES:
        if (df["note"] == note).any():
            print(f"スキップ（設定済み）: {pid}「{note}」")
            continue
        hit = df[(df["person_id"] == pid) & (df["note"] == "")].index
        if len(hit) == 0:
            print(f"!! {pid} に空きnote行なし")
            continue
        df.loc[hit[0], "note"] = note
        print(f"{pid} {df.loc[hit[0], 'date']} に設定:「{note}」")
    df.to_csv(PATH, index=False)
    print("保存OK:", PATH)


if __name__ == "__main__":
    main()
