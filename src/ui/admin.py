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

from _shift_table import render_shift_table

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


def _fetch_masters():
    try:
        r = _get("/setup/masters")
        return r.json() if r.status_code == 200 else None
    except requests.exceptions.ConnectionError:
        return None


def _desc(a: dict, masters) -> str:
    """割当1件を『名前 日付 ポジション 時間』の文字列にする。"""
    pn = {p["id"]: p["name"] for p in masters["persons"]} if masters else {}
    posn = {p["id"]: p["name"] for p in masters["positions"]} if masters else {}
    who = pn.get(a["person_id"], a["person_id"])
    pos = posn.get(a["position_id"], a["position_id"])
    return f"{who} ・ {a['date']} ・ {pos} {a['start']}-{a['end']}"


def _render_approval_result(data: dict, masters) -> None:
    """承認直後の「このルールでシフトがこう変わった」を before/after で見せる。"""
    approve = data.get("approve") or {}
    diff_data = data.get("diff")

    with st.container(border=True):
        st.subheader(f"✅ 承認しました：`{approve.get('タイプ名', '')}`")
        c1, c2 = st.columns(2)
        c1.metric("ハンドラ登録", approve.get("ハンドラ登録", "—"))
        c2.metric("反映した要望（件）", approve.get("反映した要望(params)件数", "—"))
        if approve.get("警告"):
            st.warning(approve["警告"])

        if diff_data is None:
            st.info("反映効果の比較を取得できませんでした。「④ シフト計算・確認」で再計算してご確認ください。")
        elif diff_data.get("handler_failed"):
            st.error(
                "⚠️ AIが生成したコードに**実行時エラー**があり、このルールは適用できませんでした。\n\n"
                "（ハンドラ登録と要望のparams化は済んでいますが、計算時にコードが落ちます）  \n"
                "下のカードで対象タイプの「🤖 AIにハンドラを生成させる」をもう一度押して、"
                "コードを作り直してから再度承認してください。"
            )
        else:
            removed = diff_data["diff"]["removed"]
            added = diff_data["diff"]["added"]
            st.markdown("#### 🔁 このルールで変わった割り当て")
            if not removed and not added:
                st.info("このルールによる割り当ての変化はありませんでした（もともと条件を満たしていた）。")
            else:
                if removed:
                    st.markdown("**❌ 消えた割り当て（このルールで入れられなくなった）**")
                    for a in removed:
                        st.markdown(f"- {_desc(a, masters)}")
                if added:
                    st.markdown("**➕ 増えた割り当て**")
                    for a in added:
                        st.markdown(f"- {_desc(a, masters)}")

            if masters is not None:
                t_after, t_before = st.tabs(["反映後（after）", "反映前（before）"])
                with t_after:
                    render_shift_table(diff_data["after"]["assignments"], masters)
                with t_before:
                    render_shift_table(diff_data["before"]["assignments"], masters)

        st.caption("「④ シフト計算・確認」で再計算すると、確定版（全要望反映）になります。")
        if st.button("閉じる", key="dismiss_approval"):
            del st.session_state["last_approval"]
            st.rerun()


# ── 直前の承認結果（before/after差分）を最上部に表示 ──────────────────
_masters = _fetch_masters()
if "last_approval" in st.session_state:
    _render_approval_result(st.session_state["last_approval"], _masters)
    st.divider()


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

# 「表現できない」理由カテゴリ → 日本語ラベル（正直な拒否の表示用）
_REJECT_LABELS = {
    "negotiation_dependent": "他者の希望に依存（交渉が必要）",
    "history_dependent": "過去の実績データが必要",
    "missing_data": "手持ちに無いデータが必要",
    "subjective": "主観的で数値化できない",
    "advanced_logic": "高度な条件ロジックが必要（現在の部品で表現不可）",
}


# ── 1件ずつカード表示 ────────────────────────────────────────────────
for req in queue:
    req_id = req["id"]
    generated = bool(req.get("suggested_handler_code") or req.get("suggested_recipe"))

    with st.container(border=True):
        # 見出し
        st.markdown(
            f"### `{req['suggested_type_name']}`　"
            f"<span style='font-size:0.8em;color:gray'>検出 {req['occurrence_count']} 件 ・ {req_id}</span>",
            unsafe_allow_html=True,
        )
        if req.get("summary"):
            st.markdown(f"**要約：{req['summary']}**")

        # ── 表現できない＝AIが正直に拒否（分かったフリをしない・核の見せ場） ──
        if req.get("expressible") is False:
            cat = req.get("reject_category") or ""
            st.error(f"❌ このルールは現在の仕組みでは**表現できません**（理由：{_REJECT_LABELS.get(cat, '不明')}）")
            tr = req.get("test_results")
            if tr and tr.get("detail"):
                st.caption(f"AIの説明：{tr['detail']}")
            with st.expander("💬 元の発言を見る"):
                for s in req["source_texts"]:
                    st.markdown(f"- 「{s}」")
            st.caption("AIは“分かったフリ”をせず、表現できないことを正直に申告します。手作業での対応をご検討ください。")
            if req["status"] == "pending":
                if st.button("🗂️ 却下として記録する", key=f"rj_inexp_{req_id}"):
                    try:
                        r = _post(f"/admin/pending-types/{req_id}/reject", comment=f"表現不可: {cat}")
                        if r.status_code == 200:
                            st.success("却下として記録しました。")
                            st.rerun()
                        else:
                            st.error(f"記録に失敗（{r.status_code}）：{r.text}")
                    except Exception as exc:
                        st.error(f"記録に失敗しました: {exc}")
            else:
                st.caption(f"処理済み（{_STATUS_LABEL.get(req['status'], req['status'])}）")
            continue

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
                    "このテストは「3名×1週間の検証シナリオにレシピを当てて、エラーなく制約が作られるか」"
                    "を見る**動作確認**です（任意コードの実行はありません）。ルールの意味が正しいか"
                    "（Hard/Softや対象範囲）は、レシピと確認ポイントで人が判断してください。"
                )

        # ── 未生成: 設計ボタン ──────────────────────────────────
        if not generated:
            st.info("まだAIがルールを設計していません。")
            with st.expander("💬 元の発言を見る"):
                for s in req["source_texts"]:
                    st.markdown(f"- 「{s}」")
            if st.button("🤖 AIにルールを設計させる", key=f"gen_{req_id}", type="primary"):
                with st.spinner("AIがレシピ（操作×選択子）を設計・検証中..."):
                    try:
                        r = _post(f"/admin/pending-types/{req_id}/generate")
                        if r.status_code == 200:
                            st.success("設計・検証が完了しました。")
                            st.rerun()
                        else:
                            detail = r.json().get("detail", r.text)
                            st.error(f"設計に失敗（{r.status_code}）：{detail}")
                    except Exception as exc:
                        st.error(f"設計に失敗しました: {exc}")
            continue

        # ── 生成済み: 詳細タブ ─────────────────────────────────
        recipe = req.get("suggested_recipe")
        if recipe:
            tab_recipe, tab_src, tab_json = st.tabs(
                ["🧩 レシピ（操作×選択子）", "💬 元の発言", "{} JSON"]
            )
            with tab_recipe:
                st.caption("AIは生のコードではなく、**安全な部品（操作＋選択子）の組み合わせ**を設計します。")
                st.json(recipe)
                if req.get("tested_params"):
                    st.markdown("検証に使った完成レシピの例：")
                    st.json(req["tested_params"])
            with tab_src:
                for s in req["source_texts"]:
                    st.markdown(f"- 「{s}」")
            with tab_json:
                st.json(req)
        else:
            tab_code, tab_schema, tab_src, tab_json = st.tabs(
                ["📝 生成コード", "🧩 スキーマ", "💬 元の発言", "{} JSON"]
            )
            with tab_code:
                st.code(req.get("suggested_handler_code") or "", language="python")
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
                "※ 承認すると、AIが各人の原文をレシピに埋めて制約化し、再計算でシフトに反映されます。"
            )
            comment = st.text_input("コメント（任意）", key=f"cmt_{req_id}", placeholder="承認/却下の理由など")
            b1, b2, _ = st.columns([1, 1, 3])
            with b1:
                if st.button("✅ 承認", key=f"ap_{req_id}", type="primary"):
                    try:
                        with st.spinner("承認 → 要望をparams化 → 反映効果を計算中..."):
                            r = _post(f"/admin/pending-types/{req_id}/approve", comment=comment)
                            if r.status_code == 200:
                                approve_body = r.json()
                                diff_data = None
                                try:
                                    pr = requests.post(
                                        f"{API_URL}/solver/preview-rule-effect",
                                        json={"type_name": req["suggested_type_name"]},
                                        timeout=120,
                                    )
                                    if pr.status_code == 200:
                                        diff_data = pr.json()
                                except Exception:
                                    diff_data = None
                                st.session_state["last_approval"] = {
                                    "approve": approve_body, "diff": diff_data,
                                }
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
