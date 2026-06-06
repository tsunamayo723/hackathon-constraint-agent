"""
④ 管理者承認画面（サイト管理者向け）

未知タイプの承認キューを表示し、AIが生成したハンドラを確認して承認/却下する。
デモのクライマックス。

設計方針（判断に必要な情報を前面・詳細はタブ）:
- 前面: type名・要約・自信度・テスト結果・確認してほしい点
- タブ: 生成コード / スキーマ / 元の発言 / 生JSON（必要時のみ開く）
- 未生成なら「AIに生成させる」ボタンを出す
"""

import requests
import streamlit as st

API_URL = "http://localhost:8001"

# app.py から読み込まれた場合は設定済みなので無視
try:
    st.set_page_config(page_title="管理者承認", page_icon="🛡️", layout="centered")
except Exception:
    pass

st.title("🛡️ 管理者承認キュー")
st.caption(
    "AIが検出した未知ルールを確認し、生成されたハンドラを承認/却下します。"
    "（実運用ではサイト管理者が横断的にレビューします）"
)


def _get(path: str, **params):
    return requests.get(f"{API_URL}{path}", params=params, timeout=20)


def _post(path: str, **params):
    return requests.post(f"{API_URL}{path}", params=params, timeout=120)


# ── キュー取得 ──────────────────────────────────────────────────────
show_all = st.checkbox("処理済み（承認/却下）も表示する", value=False)

try:
    resp = _get("/admin/pending-types") if show_all else _get("/admin/pending-types", status="pending")
    resp.raise_for_status()
    queue = resp.json()
except requests.exceptions.ConnectionError:
    st.error(
        "**APIサーバーに接続できません。**\n\n"
        "別ターミナルで起動してください:\n"
        "```\npython -m uvicorn src.api.main:app --port 8001\n```"
    )
    st.stop()
except Exception as exc:
    st.error(f"キューの取得に失敗しました: {exc}")
    st.stop()

if not queue:
    st.success("承認待ちはありません。✨")
    st.caption("「② 追加制約・特殊事情」で未知ルールを送ると、ここに承認待ちが溜まります。")
    st.stop()

st.markdown(f"#### 承認待ち / 表示中：{len(queue)} 件")

_STATUS_LABEL = {"pending": "⏳ 承認待ち", "approved": "✅ 承認済み", "rejected": "❌ 却下済み"}


# ── 1件ずつカード表示 ────────────────────────────────────────────────
for req in queue:
    req_id = req["id"]
    generated = bool(req.get("suggested_handler_code"))

    with st.container(border=True):
        # 見出し
        st.markdown(
            f"### `{req['suggested_type_name']}`　"
            f"<span style='font-size:0.8em;color:gray'>検出 {req['occurrence_count']} 件 ・ {req_id}</span>",
            unsafe_allow_html=True,
        )
        if req.get("summary"):
            st.markdown(f"**要約：{req['summary']}**")

        # 前面の指標（自信度・テスト・状態）
        c1, c2, c3 = st.columns(3)
        with c1:
            if generated:
                st.metric("AI自信度", f"{int(req.get('confidence', 0) * 100)}%")
            else:
                st.metric("AI自信度", "—")
        with c2:
            tr = req.get("test_results")
            if tr is None:
                st.metric("テスト", "未実施")
            else:
                st.metric("テスト", "✅ 合格" if tr["passed"] else "❌ 不合格")
        with c3:
            st.metric("状態", _STATUS_LABEL.get(req["status"], req["status"]))

        # 確認してほしい点（解釈について・パース時のFlash由来）
        review_points = req.get("review_points") or []
        if review_points:
            st.markdown("🔍 **確認してほしい点（解釈について）**")
            for r in review_points:
                st.markdown(f"- {r}")

        # AIからの申し送り（生成コードについての懸念点・自信度と対になる情報）
        if generated:
            concerns = req.get("concerns") or []
            st.markdown("📨 **AIからの申し送り（懸念点）**")
            if concerns:
                for c in concerns:
                    st.markdown(f"- ⚠️ {c}")
            else:
                st.caption("特になし（AIは懸念を申告していません）")

        # テスト内容の透明化（「合格」が何を意味するか）
        tr = req.get("test_results")
        if tr is not None:
            with st.expander("🧪 テスト内容（合格＝簡易動作確認。正しさの保証ではありません）", expanded=not tr["passed"]):
                st.markdown(f"**結果：{'✅ 合格' if tr['passed'] else '❌ 不合格'}**")
                if tr.get("detail"):
                    st.caption(tr["detail"])
                if req.get("tested_params"):
                    st.markdown("テストに使った例params：")
                    st.json(req["tested_params"])
                if not tr["passed"] and tr.get("failed_cases"):
                    st.warning("失敗内容：" + " / ".join(tr["failed_cases"]))
                st.info(
                    "このテストは「3名×1週間の小シナリオに適用してエラーなく解けるか」を見る"
                    "**簡易動作確認**です。ルールの意味が正しいか（Hard/Softや対象範囲）は"
                    "コードと確認ポイントで人が判断してください。"
                )

        # ── 未生成: 生成ボタン ──────────────────────────────────
        if not generated:
            st.info("まだAIがハンドラを生成していません。")
            with st.expander("💬 元の発言を見る"):
                for s in req["source_texts"]:
                    st.markdown(f"- 「{s}」")
            if st.button("🤖 AIにハンドラを生成させる", key=f"gen_{req_id}", type="primary"):
                with st.spinner("AIがハンドラを生成・テスト中..."):
                    try:
                        r = _post(f"/admin/pending-types/{req_id}/generate")
                        if r.status_code == 200:
                            st.success("生成・テストが完了しました。")
                            st.rerun()
                        else:
                            detail = r.json().get("detail", r.text)
                            st.error(f"生成に失敗（{r.status_code}）：{detail}")
                    except Exception as exc:
                        st.error(f"生成に失敗しました: {exc}")
            continue

        # ── 生成済み: 詳細タブ ─────────────────────────────────
        tab_code, tab_schema, tab_src, tab_json = st.tabs(
            ["📝 生成コード", "🧩 スキーマ", "💬 元の発言", "{} JSON"]
        )
        with tab_code:
            st.code(req["suggested_handler_code"], language="python")
        with tab_schema:
            st.json(req.get("suggested_schema") or {})
        with tab_src:
            for s in req["source_texts"]:
                st.markdown(f"- 「{s}」")
        with tab_json:
            st.json(req)

        # ── 承認 / 却下 ────────────────────────────────────────
        if req["status"] == "pending":
            st.caption(
                "※ 現状、承認は記録されますが、ハンドラを本番ソルバーへ自動登録して"
                "シフトに反映する処理は次フェーズ（A1b）です。"
            )
            comment = st.text_input("コメント（任意）", key=f"cmt_{req_id}", placeholder="承認/却下の理由など")
            b1, b2, _ = st.columns([1, 1, 3])
            with b1:
                if st.button("✅ 承認", key=f"ap_{req_id}", type="primary"):
                    try:
                        r = _post(f"/admin/pending-types/{req_id}/approve", comment=comment)
                        if r.status_code == 200:
                            st.success("承認しました。")
                            st.rerun()
                        else:
                            st.error(f"承認に失敗（{r.status_code}）：{r.text}")
                    except Exception as exc:
                        st.error(f"承認に失敗しました: {exc}")
            with b2:
                if st.button("❌ 却下", key=f"rj_{req_id}"):
                    try:
                        r = _post(f"/admin/pending-types/{req_id}/reject", comment=comment)
                        if r.status_code == 200:
                            st.success("却下しました。")
                            st.rerun()
                        else:
                            st.error(f"却下に失敗（{r.status_code}）：{r.text}")
                    except Exception as exc:
                        st.error(f"却下に失敗しました: {exc}")
        else:
            st.caption(f"このリクエストは処理済みです（{_STATUS_LABEL.get(req['status'])}）。")
