"""
デモUI 入口（マルチページ・ハブ）

1つのURL（既定: 8501）で複数画面をサイドバーから切り替えられるようにする。
起動: python -m streamlit run src/ui/app.py

各画面（setup.py / staff.py …）は単独でも起動できるが、
通常はこの app.py から開くのを推奨。今後の画面もここに足していく。
"""

import requests
import streamlit as st

# 全画面共通のページ設定（最初の1回だけ。各画面側はガードして二重設定を避けている）
st.set_page_config(page_title="制約管理エージェント", page_icon="🤖", layout="centered")

API_URL = "http://localhost:8001"

# デモの流れと同じ並び：設定 → 出勤希望 → 要望 → 計算 → 承認
# st.Page のパスは、この app.py があるディレクトリ（src/ui/）からの相対パス
pages = [
    st.Page("setup.py", title="① セットアップ", icon="⚙️"),
    st.Page("desired_shifts.py", title="② 出勤希望CSV", icon="🗓️"),
    st.Page("staff.py", title="③ シフト作成の要望", icon="📝"),
    st.Page("shift_view.py", title="④ シフト計算・確認", icon="📅"),
    st.Page("admin.py", title="⑤ 管理者承認", icon="🛡️"),
]

# サイドバーに Gemini のセッション消費（トークン・概算料金）を表示
with st.sidebar:
    try:
        total = requests.get(f"{API_URL}/admin/usage", timeout=5).json()["合計"]
        st.metric(
            "Gemini消費（このセッション）",
            f"{total['total_tokens']:,} tok",
            f"概算 ¥{total['jpy']:.2f}",
            delta_color="off",
        )
    except Exception:
        st.caption("Gemini消費：取得待ち")

st.navigation(pages).run()
