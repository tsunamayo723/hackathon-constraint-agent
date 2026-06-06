"""
② 追加制約・特殊事情の入力（自然言語）

CSV（経路A:マスタ / 経路B:出勤希望）では表せない
**例外・個別事情・人間関係・繰り返しルール**を自然言語で受け取る画面（経路C）。

- 入力 → パーサAPIで既知/未知に振り分け
- 「✅ 反映済み（ルール化できた）」「⏳ 確認中（未知=管理者が対応準備中）」を表示
- 未知タイプはここが入口になり、L2フロー（AIがハンドラを自動生成→承認）へ進む

※ シフト表そのものの表示は別画面（⑤ シフト確認画面・実装予定）の役割。
　 この画面は「ルールを入れて、何が反映され/確認中かを見る」ことに専念する。
"""

import requests
import streamlit as st

API_URL = "http://localhost:8001"

# ── ページ設定 ─────────────────────────────────────────────────────────
# app.py（マルチページ入口）から読み込まれた場合は既に設定済みなので無視する
try:
    st.set_page_config(
        page_title="追加制約・特殊事情の入力",
        page_icon="📝",
        layout="centered",
    )
except Exception:
    pass

# ── ヘッダー ──────────────────────────────────────────────────────────
st.title("📝 シフト作成の要望（全体方針・特殊事情）")
st.markdown(
    "シフト全体に効く**作成方針**や、CSVの列では表せない**横断ルール・特殊事情**を、"
    "**自然言語**で入力してください。AIがJSONの制約に変換します。  \n\n"
    "**入れられる例：**  \n"
    "- 🏢 全体方針：「新人はキッチン優先」「リーダーは毎日1人は入れて」「なるべく希望優先」  \n"
    "- 🔗 横断ルール：「AさんとBさんは同じシフトにしない」「新人は1人で勤務させない」  \n"
    "- 🔁 繰り返し：「毎週水曜は入れない」  \n\n"
    "ルール化できたものは反映、できなかったものはサイト管理者が確認します。"
)

st.caption(
    "💡 「11/5はお迎えで18時まで」のような**特定の日・特定の人**の希望は、"
    "この画面ではなく**出勤希望CSV**側（備考列）で入力します（CSV開通後）。"
)

st.divider()

# ── サンプル選択 ──────────────────────────────────────────────────────
EXAMPLES = {
    "（サンプルを選ぶ）": "",
    "🏢 全体方針（新人配置・希望優先）": "新人はキッチン優先で入れて。リーダーは毎日1人は必ず入れて。なるべくみんなの希望を優先して。",
    "① 既知ルールのみ": "ランチに4人入れて。",
    "② 既知 + 未知の混在（デモ推奨）": "ランチに4人入れて。毎週水曜は習い事で休みです。",
    "③ 未知ルール3種（フルデモ）": (
        "毎週水曜は習い事があって入れません。"
        "22時以降のシフトは月3回までにしてください。"
        "12/10〜20が試験期間なので極力入れないで。"
    ),
}

selected = st.selectbox("サンプルから選ぶ（任意）", list(EXAMPLES.keys()))
prefill = EXAMPLES[selected]

# ── 入力フォーム ──────────────────────────────────────────────────────
with st.form("input_form"):
    input_text = st.text_area(
        "シフト作成の要望・方針を入力してください",
        value=prefill,
        height=130,
        placeholder="例: 新人はキッチン優先で。リーダーは毎日1人は入れて。AさんとBさんは同じシフトにしない。",
    )
    person_id = st.text_input(
        "スタッフID（個人の要望のときだけ・任意）",
        placeholder="p01",
    )
    submitted = st.form_submit_button("📨 送信する", type="primary")


# ── API 呼び出し & 結果表示 ────────────────────────────────────────────
if submitted:
    if not input_text.strip():
        st.warning("テキストを入力してください。")
        st.stop()

    with st.spinner("AIが解析中..."):
        try:
            resp = requests.post(
                f"{API_URL}/parser/parse",
                json={
                    "input_text": input_text.strip(),
                    "person_id": person_id.strip() or None,
                },
                timeout=90,  # Geminiの応答＋リトライ待ちを見込んで長めに
            )
            # エラー時は本文の detail（日本語の理由）を取り出して表示する
            if resp.status_code != 200:
                try:
                    detail = resp.json().get("detail", resp.text)
                except Exception:
                    detail = resp.text
                st.error(f"解析に失敗しました（{resp.status_code}）  \n{detail}")
                st.stop()
            result = resp.json()
        except requests.exceptions.ConnectionError:
            st.error(
                "**APIサーバーに接続できません。**\n\n"
                "別のターミナルで以下を実行してください:\n"
                "```\npython -m uvicorn src.api.main:app --reload --port 8001\n```"
            )
            st.stop()
        except Exception as exc:
            st.error(f"エラーが発生しました: {exc}")
            st.stop()

    translated = result.get("translated", [])
    untranslated = result.get("untranslated", [])
    total = len(translated) + len(untranslated)

    # ── ステータスバナー ──────────────────────────────────────────────
    if untranslated:
        st.warning(
            f"⚠️ **{len(untranslated)} 件は確認中です**  \n"
            f"入力 {total} 件のうち {len(untranslated)} 件はまだルール化できていません。  \n"
            "サイト管理者が対応ルールを準備中です。承認され次第、シフトへ自動反映されます。"
        )
    else:
        st.success(
            f"✅ **{total} 件すべてをルールとして反映できました。**"
        )

    st.divider()

    # ── ✅ 反映済み ──────────────────────────────────────────────────
    st.subheader(f"✅ 反映済み（{len(translated)} 件）")

    if translated:
        for item in translated:
            c = item["constraint"]
            type_name = c.get("type", "")
            params = c.get("params", {})
            source = item.get("source_text", "")
            confidence = item.get("confidence", 0)

            with st.container(border=True):
                col_text, col_badge = st.columns([5, 1])
                with col_text:
                    st.markdown(f"**「{source}」**")
                    st.caption(f"ルール: `{type_name}`")
                    if params:
                        param_str = "　".join(f"{k}: {v}" for k, v in list(params.items())[:4])
                        st.caption(param_str)
                with col_badge:
                    st.metric(label="確信度", value=f"{int(confidence * 100)}%")
    else:
        st.caption("反映済みの要望はありません。")

    # ── ⏳ 確認中 ──────────────────────────────────────────────────────
    st.subheader(f"⏳ 確認中（{len(untranslated)} 件）")

    if untranslated:
        st.caption(
            "以下の要望はサイト管理者が対応ルールを準備しています。"
            "承認後に自動でシフトへ反映・通知します。"
        )
        for item in untranslated:
            source = item.get("source_text", "")
            reason = item.get("reason", "")
            suggested = item.get("suggested_type_name")
            req_id = item.get("pending_request_id", "")

            with st.container(border=True):
                st.markdown(f"**「{source}」**")
                st.caption(f"→ {reason}")
                col_a, col_b = st.columns(2)
                with col_a:
                    if suggested:
                        st.caption(f"推定ルール名: `{suggested}`")
                with col_b:
                    if req_id:
                        st.caption(f"管理者キューID: `{req_id}`")
    else:
        st.caption("確認中の要望はありません。")

    # 作成者はこのまま計算へ進める（③要望→④計算は同じ作成者の一連の操作）
    st.divider()
    st.caption("要望を入れ終えたら、シフトを計算します。")

# 計算画面への導線（送信の有無に関わらず常に表示）
if st.button("▶ ④ シフト計算・確認へ進む", type="primary"):
    st.switch_page("shift_view.py")
