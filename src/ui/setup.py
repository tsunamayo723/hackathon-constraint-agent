"""
① セットアップ画面（マスタ設定 ＋ 営業情報）

月次シフト作成の「土台」を登録する画面。
- マスタ設定: 役職/ポジション/スキル/スタッフのCSVをアップロード → POST /setup/masters
- 営業情報:   期間・営業時間・ポリシーをフォーム入力      → POST /setup/frame

Streamlit と FastAPI は別プロセスなので、必ずAPI経由で保存する。
"""

from datetime import date, time

import pandas as pd
import requests
import streamlit as st

API_URL = "http://localhost:8001"

# app.py（マルチページ入口）から読み込まれた場合は既に設定済みなので無視する
try:
    st.set_page_config(page_title="セットアップ", page_icon="⚙️", layout="centered")
except Exception:
    pass

st.title("⚙️ セットアップ")
st.markdown(
    "シフト作成の**土台**を登録します。  \n"
    "①マスタ（誰がいて、どんな役職・ポジション・スキルがあるか）と "
    "②営業情報（いつ・何時から何時まで営業するか）を設定してください。"
)

st.divider()


def _csv_to_records(uploaded_file) -> list[dict]:
    """アップロードされたCSVを辞書のリストに変換（空欄はNaN→None）"""
    df = pd.read_csv(uploaded_file, dtype=str).fillna("")
    return df.to_dict(orient="records")


# ═══════════════════════════════════════════════════════════════════
#  ⏩ デモデータをワンクリック投入（最短ルート）
# ═══════════════════════════════════════════════════════════════════

st.header("⏩ デモデータを使う（最短）")
st.caption(
    "CSVを用意しなくても、準備済みのデモデータをワンクリックで投入できます"
    "（**10人 × 10日** のコンパクトなデータ）。  \n"
    "※ 投入すると既存の方針・出勤希望・承認キューはクリアされ、"
    "マスタ・営業情報・必要人数も選んだデモで置き換わります。"
)

try:
    _demo_patterns = requests.get(f"{API_URL}/setup/demo-patterns", timeout=10).json()["patterns"]
except requests.exceptions.ConnectionError:
    _demo_patterns = []
    st.error(
        "**APIサーバーに接続できません。**\n\n"
        "別ターミナルで起動してください:\n"
        "```\npython -m uvicorn src.api.main:app --reload --port 8001\n```"
    )

if _demo_patterns:
    _labels = {p["key"]: p["label"] for p in _demo_patterns}
    _descs = {p["key"]: p["description"] for p in _demo_patterns}
    demo_key = st.selectbox(
        "デモパターンを選択",
        options=list(_labels.keys()),
        format_func=lambda k: _labels[k],
    )
    st.caption(_descs.get(demo_key, ""))

    if st.button("📥 このデモデータを投入する", type="primary"):
        try:
            resp = requests.post(f"{API_URL}/setup/load-demo", json={"pattern": demo_key}, timeout=30)
            if resp.status_code == 200:
                body = resp.json()
                g = body["概要"]
                st.success(
                    f"✅ {body['結果']}  \n"
                    f"スタッフ {g['スタッフ数']}名 / 期間 {g['対象期間']}  \n"
                    f"必要人数 {g['必要人数の行数']}行 / 出勤希望 {g['出勤希望の行数']}行 / "
                    f"提出者(主役) {g['提出者(主役)']}"
                )
                st.info("このまま④で計算、または提出者UI（:5173）で主役 p01 の体験を試せます。")
            else:
                st.error(f"投入に失敗しました（{resp.status_code}）: {resp.text}")
        except requests.exceptions.ConnectionError:
            st.error("APIサーバーに接続できません。")

st.divider()
st.subheader("または手動でCSVを用意する場合 ↓")


# ═══════════════════════════════════════════════════════════════════
#  ① マスタ設定（CSVアップロード）
# ═══════════════════════════════════════════════════════════════════

st.header("① マスタ設定")
st.caption(
    "4つのCSVをアップロードしてください。"
    "`data/sample/` に3パターンのデモ用サンプルがあります："
    "**pattern_a_cafe**（カフェ8名）/ **pattern_b_restaurant**（レストラン30名）/ "
    "**pattern_c_izakaya**（居酒屋50名）。"
)

col1, col2 = st.columns(2)
with col1:
    roles_file = st.file_uploader("役職 (roles.csv)", type="csv", key="roles")
    positions_file = st.file_uploader("ポジション (positions.csv)", type="csv", key="positions")
with col2:
    skills_file = st.file_uploader("スキル (skills.csv)", type="csv", key="skills")
    staff_file = st.file_uploader("スタッフ (staff.csv)", type="csv", key="staff")

# アップロードされたファイルのプレビュー
all_uploaded = all([roles_file, positions_file, skills_file, staff_file])


def _preview(label: str, file, head: int | None = None) -> None:
    """アップロード済みCSVをコンパクトに表示する。head指定時は先頭N件のみ。"""
    if file is None:
        return
    file.seek(0)
    df = pd.read_csv(file, dtype=str).fillna("")
    file.seek(0)
    if head is not None and len(df) > head:
        st.caption(f"{label}（全{len(df)}件 / 先頭{head}件を表示）")
        st.dataframe(df.head(head), use_container_width=True, hide_index=True)
        st.caption(f"… ほか {len(df) - head} 件")
    else:
        st.caption(f"{label}（{len(df)}件）")
        st.dataframe(df, use_container_width=True, hide_index=True)


# アップロードされたファイルがあれば、まとめてエクスパンダー内で確認できる
if any([roles_file, positions_file, skills_file, staff_file]):
    with st.expander("📋 アップロード内容を確認", expanded=False):
        _preview("役職", roles_file)
        _preview("ポジション", positions_file)
        _preview("スキル", skills_file)
        _preview("スタッフ", staff_file, head=10)

if st.button("📤 マスタを登録する", type="primary", disabled=not all_uploaded):
    try:
        # CSV → モデルが期待する構造へ変換
        roles = _csv_to_records(roles_file)
        positions = _csv_to_records(positions_file)
        skills = _csv_to_records(skills_file)

        staff_records = _csv_to_records(staff_file)
        persons = []
        for r in staff_records:
            skill_ids = [s for s in r.get("skill_ids", "").split(";") if s.strip()]
            persons.append({
                "id": r["id"],
                "name": r["name"],
                "role_id": r.get("role_id") or None,
                "skill_ids": skill_ids,
            })

        payload = {
            "persons": persons,
            "positions": positions,
            "roles": roles,
            "skills": skills,
        }

        resp = requests.post(f"{API_URL}/setup/masters", json=payload, timeout=15)

        if resp.status_code == 200:
            summary = resp.json()["概要"]
            st.success(
                f"✅ マスタを登録しました  \n"
                f"スタッフ {summary['スタッフ数']}名 / "
                f"ポジション {summary['ポジション数']} / "
                f"役職 {summary['役職数']} / "
                f"スキル {summary['スキル数']}"
            )
        elif resp.status_code == 422:
            detail = resp.json().get("detail", {})
            st.error("整合性エラーがありました：")
            errs = detail.get("整合性エラー", detail)
            if isinstance(errs, list):
                for e in errs:
                    st.markdown(f"- {e}")
            else:
                st.write(errs)
        else:
            st.error(f"登録に失敗しました（{resp.status_code}）: {resp.text}")

    except requests.exceptions.ConnectionError:
        st.error(
            "**APIサーバーに接続できません。**\n\n"
            "別ターミナルで起動してください:\n"
            "```\npython -m uvicorn src.api.main:app --reload --port 8001\n```"
        )
    except Exception as exc:
        st.error(f"エラーが発生しました: {exc}")

st.divider()


# ═══════════════════════════════════════════════════════════════════
#  ② 営業情報（フォーム入力）
# ═══════════════════════════════════════════════════════════════════

st.header("② 営業情報")
st.caption("対象月・営業時間・シフト作成のポリシーを設定します。")

with st.form("frame_form"):
    st.caption("初期値はデモ用サンプル（2026年11月）に合わせてあります。")
    st.subheader("対象期間")
    c1, c2 = st.columns(2)
    with c1:
        start_date = st.date_input("開始日", value=date(2026, 11, 1))
    with c2:
        end_date = st.date_input("終了日", value=date(2026, 11, 7))

    st.subheader("営業時間")
    c3, c4, c5 = st.columns(3)
    with c3:
        open_time = st.time_input("開店", value=time(11, 0))
    with c4:
        close_time = st.time_input("閉店", value=time(22, 0))
    with c5:
        slot_minutes = st.selectbox("スロット単位", [30, 60], index=1)

    st.subheader("シフト作成ポリシー")
    policy_label = st.radio(
        "どれを優先しますか？",
        ["希望優先（スタッフの希望をできるだけ叶える）",
         "バランス（希望とコストの中間）",
         "コスト優先（人件費を抑える）"],
        index=1,
    )
    policy_map = {
        "希望優先（スタッフの希望をできるだけ叶える）": "wishes",
        "バランス（希望とコストの中間）": "balance",
        "コスト優先（人件費を抑える）": "cost",
    }

    frame_submitted = st.form_submit_button("📤 営業情報を登録する", type="primary")

if frame_submitted:
    if end_date < start_date:
        st.error("終了日が開始日より前になっています。")
    else:
        payload = {
            "period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
            },
            "operating_window": {
                "open": open_time.strftime("%H:%M"),
                "close": close_time.strftime("%H:%M"),
                "slot_minutes": slot_minutes,
            },
            "policy_mode": policy_map[policy_label],
        }
        try:
            resp = requests.post(f"{API_URL}/setup/frame", json=payload, timeout=15)
            if resp.status_code == 200:
                summary = resp.json()["概要"]
                st.success(
                    f"✅ 営業情報を登録しました  \n"
                    f"期間: {summary['対象期間']}  \n"
                    f"営業時間: {summary['営業時間']}（{summary['スロット単位']}単位）  \n"
                    f"ポリシー: {summary['ポリシー']}"
                )
            else:
                st.error(f"登録に失敗しました（{resp.status_code}）: {resp.text}")
        except requests.exceptions.ConnectionError:
            st.error(
                "**APIサーバーに接続できません。**\n\n"
                "別ターミナルで起動してください:\n"
                "```\npython -m uvicorn src.api.main:app --reload --port 8001\n```"
            )
        except Exception as exc:
            st.error(f"エラーが発生しました: {exc}")

st.divider()


# ═══════════════════════════════════════════════════════════════════
#  ③ 必要人数（時間帯×ポジションの基本人数）
# ═══════════════════════════════════════════════════════════════════

st.header("③ 必要人数")
st.caption(
    "時間帯×ポジションごとに、何人必要かを登録します（シフトの「需要」）。"
    "ここが無いとソルバーに条件が無く、シフトが空になります。  \n"
    "**CSVアップロード**（`headcounts.csv`）または下の表で直接編集できます。"
    "サンプル：`data/sample/pattern_*/headcounts.csv`。"
)

# date 列は空＝毎日適用 / 日付（YYYY-MM-DD）を入れるとその日だけ適用（繁忙日の上書きなど）
_default_headcounts = pd.DataFrame([
    {"date": "", "slot_label": "ランチ", "time_start": "11:00", "time_end": "14:00", "position_id": "pos_hall", "count": 3},
    {"date": "", "slot_label": "ランチ", "time_start": "11:00", "time_end": "14:00", "position_id": "pos_kitchen", "count": 2},
    {"date": "", "slot_label": "ディナー", "time_start": "18:00", "time_end": "22:00", "position_id": "pos_hall", "count": 4},
    {"date": "", "slot_label": "ディナー", "time_start": "18:00", "time_end": "22:00", "position_id": "pos_kitchen", "count": 2},
])

hc_file = st.file_uploader("必要人数CSV（headcounts.csv）をアップロード（任意）", type="csv", key="hc_csv")
if hc_file is not None:
    base_headcounts = pd.read_csv(hc_file, dtype=str).fillna("")
else:
    base_headcounts = _default_headcounts

hc_edited = st.data_editor(
    base_headcounts,
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True,
    key="headcounts_editor",
)

if st.button("📤 必要人数を登録する", type="primary"):
    records = []
    for r in hc_edited.to_dict(orient="records"):
        if not str(r.get("slot_label", "")).strip():
            continue
        try:
            rec = {
                "slot_label": str(r["slot_label"]).strip(),
                "time_start": str(r["time_start"]).strip(),
                "time_end": str(r["time_end"]).strip(),
                "position_id": str(r["position_id"]).strip(),
                "count": int(r["count"]),
            }
            # date 列が空でなければ「その日だけ」適用として送る
            if str(r.get("date", "")).strip():
                rec["date"] = str(r["date"]).strip()
            records.append(rec)
        except (ValueError, KeyError):
            st.error("入力に不備があります（人数は整数で）。")
            st.stop()
    try:
        resp = requests.post(f"{API_URL}/setup/headcounts", json=records, timeout=15)
        if resp.status_code == 200:
            st.success(f"✅ 必要人数を登録しました（{resp.json()['件数']} 行）")
        elif resp.status_code == 422:
            errs = resp.json().get("detail", {}).get("必要人数エラー", [])
            st.error("登録エラー：")
            for e in errs:
                st.markdown(f"- {e}")
        else:
            st.error(f"登録に失敗しました（{resp.status_code}）: {resp.text}")
    except requests.exceptions.ConnectionError:
        st.error("APIサーバーに接続できません。")
    except Exception as exc:
        st.error(f"エラーが発生しました: {exc}")
