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

# 計算に使う制約の内訳（蓄積の可視化）
demands: list[dict] = []
s = _safe_get("/setup/summary")
if s is not None and s.status_code == 200:
    summary = s.json()
    demands = summary.get("必要人数", [])
    st.caption(
        f"📋 計算に使う制約：方針 {summary['方針の制約数']}件 "
        f"{summary['方針の内訳']} ／ 出勤希望 {summary['出勤希望(availability)件数']}件"
        f"　|　対象期間 {summary['対象期間']}"
    )
    st.caption(
        "⚠️ 出勤希望CSVの日付が**対象期間内**にあるか確認してください"
        "（期間外の希望は無視され、人数不足になります）。"
    )
    if st.button("🗑️ 方針・出勤希望をリセット（やり直し）"):
        r = requests.post(f"{API_URL}/setup/reset-constraints", timeout=20)
        if r.status_code == 200:
            st.success("リセットしました。②③から入れ直してください。")
            st.rerun()

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
            st.info("⚠️ **暫定版**シフト（未反映の要望が残っています。承認後に再計算で確定）")
        else:
            st.success("✅ **確定版**シフト（すべての要望を反映）")

        # ── 充足スコア（100点満点・分かりやすい評価） ────────────
        meta = out.get("meta") or {}
        score = meta.get("coverage_score", 100.0)
        st.metric(
            "🎯 充足スコア（100点満点）", f"{score} 点",
            help="必要人数をどれだけ満たせたか＝(必要−不足)/必要×100。100点＝全ブロック充足。",
        )
        sc1, sc2, sc3 = st.columns(3)
        sc1.metric("必要人数（計）", meta.get("required_units", "?"), help="必要だった人数の合計（コマ単位）")
        sc2.metric("不足（計）", meta.get("shortage_units", "?"), help="満たせなかった人数（コマ単位）")
        sc3.metric("希望違反（罰金）", meta.get("soft_penalty", "?"), help="ソフト制約の違反度。0が理想（スケールは曖昧なので参考値）")
        st.caption(f"計算時間 {meta.get('elapsed_ms','?')}ms / 目的関数 {meta.get('objective','?')}（参考・小さいほど良い）")

        # ── 必要人数（ブロック別の需要）＋ 充足状況 ───────────────
        if demands:
            st.markdown("**必要人数（方針）：**")
            df_d = pd.DataFrame([
                {"対象日": x.get("date", "毎日"), "ブロック": x["slot_label"], "時間": x["time"],
                 "ポジション": x["position_id"], "必要人数": x["count"]}
                for x in demands
            ])
            st.dataframe(df_d, use_container_width=True, hide_index=True)
            st.caption("※ 必要人数はHard制約のため、計算できた（solved）時点で全ブロック充足しています。")

        # ── 結果サマリ（出勤者・ポジション別） ────────────────────
        assignments = out["assignments"]
        position_name = {p["id"]: p["name"] for p in masters["positions"]}
        by_pos: dict[str, int] = {}
        for a in assignments:
            by_pos[a["position_id"]] = by_pos.get(a["position_id"], 0) + 1
        workers = len({a["person_id"] for a in assignments})
        pos_txt = "／".join(f"{position_name.get(k,k)} {v}枠" for k, v in by_pos.items())
        st.caption(f"📊 出勤者 {workers}名 ・ 勤務ブロック {len(assignments)}件（{pos_txt}）")

        # ── 未反映の要望（暫定の理由） ────────────────────────────
        pending = out.get("pending_constraints", [])
        if pending:
            st.warning(f"⏳ **未反映の要望 {len(pending)}件**（管理者の承認待ち）")
            for p in pending:
                st.markdown(f"- 「{p['source_text']}」→ 推定: `{p.get('suggested_type_name') or '不明'}`")

        st.divider()
        render_shift_table(assignments, masters)
    elif out["status"] == "infeasible":
        st.error("条件を満たすシフトが作れませんでした。")
        blocking = out.get("blocking_constraints", [])
        if blocking:
            st.markdown("**詰まり箇所（人数不足）：**")
            for b in blocking:
                w = b.get("where", {})
                st.markdown(f"- {w.get('date','')} {w.get('slot','')} ／ {w.get('position_id','')}：{b.get('detail','')}")
        else:
            st.info(
                "詰まり箇所を特定できませんでした。よくある原因：  \n"
                "- 出勤希望の**日付が対象期間外**（11月のデータに対し期間が別月など）  \n"
                "- ②の方針が**蓄積して矛盾**している → 上の「🗑️ リセット」で入れ直す  \n"
                "- 必要人数に対して出勤可能者が少ない"
            )
    else:
        st.warning("計算が時間内に終わりませんでした。条件を見直してください。")

    # 計算に未反映のタイプを「理由つき」で表示（正直に）
    warns = out.get("warnings", [])
    unhandled = [w["type"].split(":", 1)[1] for w in warns if w.get("type", "").startswith("unhandled:")]
    unregistered = [w["type"].split(":", 1)[1] for w in warns if w.get("type", "").startswith("unregistered:")]
    if unhandled:
        st.caption(
            f"※ 未反映（既知タイプだがソルバーのハンドラが未実装）: {', '.join(set(unhandled))}"
        )
    if unregistered:
        st.caption(
            f"※ 未反映（未承認の新タイプ）: {', '.join(set(unregistered))} "
            "→「⑤ 管理者承認」で承認すると次回計算から反映されます。"
        )
