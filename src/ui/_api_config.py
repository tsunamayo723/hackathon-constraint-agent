"""
Streamlit 裏方UI の共通設定（兄弟モジュール）。

`API_URL` = FastAPI バックエンドの宛先。
- ローカル開発: 既定の http://localhost:8001
- Cloud Run 等: 環境変数 `API_URL` に FastAPI サービスのURLを入れて差し替える。
  （Streamlit と FastAPI は **別サービス＝別URL** になるため、localhost では繋がらない）

各画面（setup.py / staff.py …）は `from _api_config import API_URL` で読み込む
（`_shift_table` と同じく、streamlit run の実行ディレクトリ src/ui/ を基準にした兄弟import）。
"""

import os

API_URL = os.environ.get("API_URL", "http://localhost:8001")
