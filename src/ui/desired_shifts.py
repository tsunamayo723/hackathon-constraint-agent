"""
③ 出勤希望CSV登録画面

desired_shifts.csv（person_id / date / start / end / note）をアップロードし、
availability制約としてバックエンドに保存する（経路B）。

※ note列（日ごとの自由記述）は保存され、下の「備考をAIで解釈」でバッチ解釈する
（✅時間補正 / 🆕新ルール候補→承認キュー / ⚠️申し送り の3分類）。
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
                st.caption("「④ シフト計算・確認」画面で計算できます。")
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


# ── 備考(note)のAI解釈 ──────────────────────────────────────────────
st.divider()
st.subheader("📝 備考をAIで解釈して反映")
st.caption(
    "登録済みの出勤希望のうち**備考付きの行**を、AIがまとめて解釈し、3つに分類します。  \n"
    "✅ その日の時間補正（例「お迎えで17時まで」→ 17時終わりに）  \n"
    "🆕 新しいルール候補（例「毎週水曜NG」→ 管理者の承認キューへ）  \n"
    "⚠️ どちらでもない（申し送りとして表示）  \n"
    "コスト対策で**バッチ処理**します。押した時だけ実行（＝課金タイミングを自分で制御）。"
)
if st.button("📝 備考をAIで解釈する", type="secondary"):
    with st.spinner("AIが備考を解釈中（バッチ）..."):
        try:
            r = requests.post(f"{API_URL}/setup/interpret-notes", timeout=120)
            if r.status_code == 200:
                d = r.json()
                applied = d.get("反映した備考", [])
                new_rules = d.get("新ルール候補", [])
                unreflected = d.get("未反映の備考", [])
                st.success(
                    f"解釈 {d.get('解釈件数', 0)} 件 ／ ✅ 反映 {len(applied)} 件 ／ "
                    f"🆕 新ルール候補 {len(new_rules)} 件 ／ ⚠️ 未反映 {len(unreflected)} 件"
                )
                if applied:
                    st.markdown("**✅ 反映した備考（出勤可能枠を補正）**")
                    for n in applied[:30]:
                        st.markdown(f"- {n['person_id']} {n['date']}：「{n['note']}」→ {n['summary']}")
                if new_rules:
                    st.markdown("**🆕 新しいルール候補（管理者の承認キューに送りました）**")
                    for n in new_rules[:30]:
                        st.markdown(
                            f"- {n['person_id']} {n['date']}：「{n['note']}」→ "
                            f"推定タイプ `{n['suggested_type_name']}`"
                        )
                    st.caption(
                        "「⑤ 管理者承認」でAIがハンドラ（処理コード）を生成し、"
                        "承認されると以降の計算に反映できるようになります。"
                    )
                if unreflected:
                    st.markdown("**⚠️ 未反映の備考（ルールでも時間でもない・人が確認）**")
                    for n in unreflected[:30]:
                        st.markdown(f"- {n['person_id']} {n['date']}：「{n['note']}」")
                    st.caption("これらは自動反映できていません。④でも『未反映の備考』として表示され、手当てが必要です。")
                st.caption("「④ シフト計算・確認」で再計算すると、反映ぶんが反映されます。")
            else:
                detail = r.json().get("detail", r.text)
                st.error(f"解釈に失敗しました（{r.status_code}）：{detail}")
        except requests.exceptions.ConnectionError:
            st.error("APIサーバーに接続できません。")
        except Exception as exc:
            st.error(f"エラーが発生しました: {exc}")
