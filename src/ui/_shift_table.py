"""
共有util — assignments を「スタッフ × 日付」の表にして描画する

④シフト確認と⑤管理者承認（before/after比較）で同じ描画を使うため切り出した。
assignments は dict のリスト（キー: date / person_id / position_id / start / end）。
masters は {"persons":[...], "positions":[...]} を含む dict。
"""

import pandas as pd
import streamlit as st


def render_shift_table(assignments: list[dict], masters: dict) -> None:
    """assignments を「スタッフ × 日付」の表にする（出勤者のみ）。"""
    person_name = {p["id"]: p["name"] for p in masters["persons"]}
    position_name = {p["id"]: p["name"] for p in masters["positions"]}

    dates = sorted({a["date"] for a in assignments})
    if not dates:
        st.info("この条件では割り当てが発生しませんでした（シフトは空です）。")
        return

    cells: dict[tuple, list[str]] = {}
    working: set[str] = set()
    for a in assignments:
        name = person_name.get(a["person_id"], a["person_id"])
        pos = position_name.get(a["position_id"], a["position_id"])
        cells.setdefault((name, a["date"]), []).append(f"{pos} {a['start']}-{a['end']}")
        working.add(name)

    rows = []
    for name in sorted(working):
        row = {"スタッフ": name}
        for dt in dates:
            row[dt] = " / ".join(cells.get((name, dt), [])) or "—"
        rows.append(row)
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
