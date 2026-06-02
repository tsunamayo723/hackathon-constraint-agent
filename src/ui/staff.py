"""
スタッフ・店長向け入力画面

自然言語でシフト希望を入力 → パーサAPIを呼んで既知/未知に振り分け →
「✅ 反映済み」「⏳ 確認中」の2ブロックで結果を表示する。
"""

import requests
import streamlit as st

API_URL = "http://localhost:8001"

# ── ページ設定 ─────────────────────────────────────────────────────────
st.set_page_config(
    page_title="シフト希望入力",
    page_icon="📅",
    layout="centered",
)

# ── ヘッダー ──────────────────────────────────────────────────────────
st.title("📅 シフト希望入力")
st.markdown(
    "希望やルールを**自然言語**で入力すると、AIが解析してシフトに反映します。  \n"
    "反映できなかった要望はサイト管理者が確認し、承認後に自動で反映されます。"
)

st.divider()

# ── サンプル選択 ──────────────────────────────────────────────────────
EXAMPLES = {
    "（サンプルを選ぶ）": "",
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
        "希望・ルールを入力してください",
        value=prefill,
        height=130,
        placeholder="例: ランチに4人入れて。毎週水曜は習い事で休みです。",
    )
    person_id = st.text_input(
        "スタッフID（任意）",
        placeholder="p1",
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
                timeout=15,
            )
            resp.raise_for_status()
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
            f"⚠️ **暫定シフト表示中**  \n"
            f"入力 {total} 件のうち **{len(untranslated)} 件**はまだシフトに反映されていません。  \n"
            "サイト管理者が新しいルールを準備中です。承認され次第、自動でシフトが更新されます。"
        )
    else:
        st.success(
            f"✅ **{total} 件すべてがシフトに反映されました。**"
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

    # ── シフト表示（暫定プレースホルダー） ────────────────────────────
    st.divider()
    status_label = "⚠️ 暫定シフト" if untranslated else "✅ 確定シフト"
    st.subheader(f"📋 {status_label}")

    if untranslated:
        st.info(
            "このシフトは確認中の要望を除いて計算された**暫定版**です。  \n"
            "管理者が承認すると、このシフトは自動的に再計算されます。"
        )
    else:
        st.success("このシフトはすべての要望を反映した**確定版**です。")

    st.caption("※ シフト自動計算（OR-Tools連携）は実装予定です")

    # シフト表のダミーデータ
    import pandas as pd
    dummy_shift = pd.DataFrame(
        {
            "スタッフ": ["田中", "鈴木", "佐藤", "山田"],
            "11/1 (月)": ["ランチ", "ディナー", "休み", "ランチ"],
            "11/2 (火)": ["休み", "ランチ", "ディナー", "休み"],
            "11/3 (水)": ["ランチ", "休み", "ランチ", "⏳保留"],
            "11/4 (木)": ["ディナー", "ランチ", "休み", "ランチ"],
        }
    )
    st.dataframe(dummy_shift, use_container_width=True, hide_index=True)

    if untranslated:
        st.caption("⏳ 保留 = 確認中の要望が影響する可能性がある枠")
