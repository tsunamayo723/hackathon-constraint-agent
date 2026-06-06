"""
デモUI 入口（マルチページ・ハブ）

1つのURL（既定: 8501）で複数画面をサイドバーから切り替えられるようにする。
起動: python -m streamlit run src/ui/app.py

各画面（setup.py / staff.py …）は単独でも起動できるが、
通常はこの app.py から開くのを推奨。今後の画面もここに足していく。
"""

import streamlit as st

# 全画面共通のページ設定（最初の1回だけ。各画面側はガードして二重設定を避けている）
st.set_page_config(page_title="制約管理エージェント", page_icon="🤖", layout="centered")

# st.Page のパスは、この app.py があるディレクトリ（src/ui/）からの相対パス
pages = [
    st.Page("setup.py", title="① セットアップ", icon="⚙️"),
    st.Page("staff.py", title="② シフト作成の要望", icon="📝"),
    st.Page("desired_shifts.py", title="③ 出勤希望CSV", icon="🗓️"),
    st.Page("admin.py", title="④ 管理者承認", icon="🛡️"),
    st.Page("shift_view.py", title="⑤ シフト確認", icon="📅"),
]

st.navigation(pages).run()
