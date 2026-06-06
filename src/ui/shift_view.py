"""
⑤ シフト確認画面

保存済みデータ（マスタ＋営業情報＋②方針＋③出勤希望）から
シフトを計算して表示する（一気通貫の出口）。
"""

import pandas as pd
import requests
import streamlit as st

API_URL = "http://localhost:8001"

try:
    st.set_page_config(page_title="シフト確認", page_icon="📅", layout="wide")
except Exception:
    pass

st.title("📅 シフト確認")
st.markdown(
    "①〜③で登録した内容をまとめて使い、シフトを計算します。  \n"
    "（マスタ＋営業情報＋②の方針＋③の出勤希望）"
)


def _safe_get(path: str):
    try:
        return requests.get(f"{API_URL}{path}", timeout=20)
    except requests.exceptions.ConnectionError:
        return None


# ── 登録状況のサマリ ────────────────────────────────────────────────
m = _safe_get("/setup/masters")
f = _safe_get("/setup/frame")
d = _safe_get("/setup/desired-shifts")

if m is None:
    st.error("APIサーバーに接続できません。`python -m uvicorn src.api.main:app --port 8001` で起動してください。")
    st.stop()

c1, c2, c3 = st.columns(3)
c1.metric("マスタ", "✅ 登録済み" if m.status_code == 200 else "未登録")
c2.metric("営業情報", "✅ 登録済み" if f.status_code == 200 else "未登録")
c3.metric("出勤希望", f"{d.json()['件数']} 件" if d is not None and d.status_code == 200 else "未登録")

if m.status_code != 200 or f.status_code != 200:
    st.warning("先に「① セットアップ」でマスタと営業情報を登録してください。")
    st.stop()

st.divider()


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


# ── 計算 ────────────────────────────────────────────────────────────
if st.button("🧮 シフトを計算する", type="primary"):
    with st.spinner("OR-Toolsで計算中..."):
        try:
            resp = requests.post(f"{API_URL}/solver/run-stored", timeout=60)
        except requests.exceptions.ConnectionError:
            st.error("APIサーバーに接続できません。")
            st.stop()

    if resp.status_code != 200:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        st.error(f"計算に失敗しました（{resp.status_code}）\n\n{detail}")
        st.stop()

    out = resp.json()
    masters = m.json()

    if out["status"] == "solved":
        if out["shift_status"] == "provisional":
            st.info("⚠️ 暫定版（未翻訳の要望が残っています）")
        else:
            st.success("✅ 確定版シフト")
        meta = out.get("meta") or {}
        st.caption(f"計算時間 {meta.get('elapsed_ms','?')}ms / 目的関数値 {meta.get('objective','?')}（出勤者のみ表示）")
        render_shift_table(out["assignments"], masters)
    elif out["status"] == "infeasible":
        st.error("条件を満たすシフトが作れませんでした（人数不足の可能性）。")
        for b in out.get("blocking_constraints", []):
            w = b.get("where", {})
            st.markdown(f"- {w.get('date','')} {w.get('slot','')} ／ {w.get('position_id','')}：{b.get('detail','')}")
    else:
        st.warning("計算が時間内に終わりませんでした。条件を見直してください。")

    # ソルバー未対応タイプの警告（正直に表示）
    unhandled = [w["type"] for w in out.get("warnings", []) if w.get("type", "").startswith(("unhandled:", "unregistered:"))]
    if unhandled:
        st.caption(f"※ 計算に未反映のタイプ: {', '.join(unhandled)}")
