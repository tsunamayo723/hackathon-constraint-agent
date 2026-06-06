"""
③ 出勤希望CSV登録画面

desired_shifts.csv（person_id / date / start / end / note）をアップロードし、
availability制約としてバックエンドに保存する（経路B）。

※ note列（日ごとの自由記述）は保存される。AIによる解釈は次フェーズ（B2b）。
"""

import pandas as pd
import requests
import streamlit as st

API_URL = "http://localhost:8001"

try:
    st.set_page_config(page_title="出勤希望CSV", page_icon="🗓️", layout="centered")
except Exception:
    pass

st.title("🗓️ 出勤希望の登録（CSV）")
st.markdown(
    "誰が・いつ入れるかを **CSV** で登録します（経路B）。  \n"
    "列：`person_id, date, start, end, note`（note=日ごとの備考・任意）。  \n"
    "**CSVに無い日時は『出勤不可』**として扱われます（出勤希望ベース）。"
)
st.caption("デモ用サンプル：`data/sample/pattern_b_restaurant/desired_shifts.csv`（30名）")

st.divider()

uploaded = st.file_uploader("desired_shifts.csv をアップロード", type="csv")

if uploaded is not None:
    df = pd.read_csv(uploaded, dtype=str).fillna("")
    st.caption(f"読み込み：{len(df)} 行")
    with st.expander("📋 アップロード内容を確認（先頭20行）", expanded=False):
        st.dataframe(df.head(20), use_container_width=True, hide_index=True)

    if st.button("📤 出勤希望を登録する", type="primary"):
        # CSV行 → availability用レコード（空のnoteは送らない）
        records = []
        for r in df.to_dict(orient="records"):
            rec = {
                "person_id": r.get("person_id", ""),
                "date": r.get("date", ""),
                "start": r.get("start", ""),
                "end": r.get("end", ""),
            }
            if r.get("note", "").strip():
                rec["note"] = r["note"].strip()
            records.append(rec)

        try:
            resp = requests.post(f"{API_URL}/setup/desired-shifts", json=records, timeout=30)
            if resp.status_code == 200:
                st.success(f"✅ 出勤希望を登録しました（{resp.json()['件数']} 件）")
                st.caption("「⑤ シフト確認」画面で計算できます。")
            elif resp.status_code == 422:
                detail = resp.json().get("detail", {})
                errs = detail.get("出勤希望エラー", detail)
                st.error("登録エラーがありました：")
                if isinstance(errs, list):
                    for e in errs[:20]:
                        st.markdown(f"- {e}")
                    if len(errs) > 20:
                        st.caption(f"…ほか {len(errs) - 20} 件")
                else:
                    st.write(errs)
            else:
                st.error(f"登録に失敗しました（{resp.status_code}）: {resp.text}")
        except requests.exceptions.ConnectionError:
            st.error(
                "**APIサーバーに接続できません。**\n\n"
                "別ターミナルで起動してください:\n"
                "```\npython -m uvicorn src.api.main:app --port 8001\n```"
            )
        except Exception as exc:
            st.error(f"エラーが発生しました: {exc}")
