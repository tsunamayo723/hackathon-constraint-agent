"""
永続化の差し替え口（StateStore）

`storage.py` はこの StateStore 越しに状態を読み書きする（保存先を1か所に集約）。
キー（バケット名）→ 値（JSONにできる dict / list / スカラ）の単純なKVS。

- InMemoryStore: プロセス内 dict。**既定**。再起動で消える（デモ1セッションは可）。
- SupabaseStore: Supabase の単一テーブル `app_state(key text primary key, value jsonb)` に保存。
  `SUPABASE_URL` と キー（SERVICE_ROLE 優先・無ければ ANON）が揃ったときだけ有効になる。
  ※ これは **T5の骨組み**。実DBでの検証は接続情報が入ってから（T6デプロイとセット）。

`get_store()` が環境変数を見てどちらかを返す（キーが無ければ自動で InMemory にフォールバック）。
テーブル定義は `db/schema.sql`。
"""

import logging
import os
from typing import Any, Protocol, runtime_checkable

from dotenv import load_dotenv

# storage.py より先に import されても環境変数を読めるようにしておく（冪等）
load_dotenv()

logger = logging.getLogger("uvicorn.error")


@runtime_checkable
class StateStore(Protocol):
    """保存口の最小インターフェース（キー→JSON値のKVS）。"""

    def get(self, key: str, default: Any = None) -> Any: ...
    def set(self, key: str, value: Any) -> None: ...


class InMemoryStore:
    """プロセス内 dict。既定のバックエンド（再起動で消える）。"""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value


class SupabaseStore:
    """Supabase(`app_state`)に保存するバックエンド（T5骨組み）。

    単一店舗デモなので、各バケットを `key=バケット名` の1行に丸ごと JSONB で持つ。
    実DBでの検証は接続情報が入ってから（`db/schema.sql` を先にSupabaseで実行しておく）。
    """

    TABLE = "app_state"

    def __init__(self, url: str, key: str) -> None:
        # supabase クライアントはここでだけ import（キーが無い環境では読み込まない）
        from supabase import create_client

        self._client = create_client(url, key)

    def get(self, key: str, default: Any = None) -> Any:
        res = self._client.table(self.TABLE).select("value").eq("key", key).execute()
        rows = res.data or []
        return rows[0]["value"] if rows else default

    def set(self, key: str, value: Any) -> None:
        # 同じ key があれば上書き（upsert）
        self._client.table(self.TABLE).upsert({"key": key, "value": value}).execute()


def _looks_configured(url: str, key: str) -> bool:
    """接続情報が「実物っぽい」かを判定（雛形・空・非ASCIIは未設定扱い）。"""
    if not url or not key:
        return False
    if not url.isascii() or url.startswith("https://your-project"):
        return False
    if key in ("your_supabase_anon_key_here", "your_service_role_key_here"):
        return False
    return True


def get_store() -> StateStore:
    """環境変数を見て保存口を返す。Supabaseキーが揃えばSupabase、無ければインメモリ。"""
    url = (os.environ.get("SUPABASE_URL") or "").strip()
    key = (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_ANON_KEY")
        or ""
    ).strip()

    if _looks_configured(url, key):
        try:
            store = SupabaseStore(url, key)
            logger.info("永続化: Supabase を使用します（テーブル app_state）")
            return store
        except Exception as exc:  # 初期化失敗時はデモを止めずインメモリへ
            logger.warning("Supabase 初期化に失敗→インメモリにフォールバック: %s", exc)

    logger.info("永続化: インメモリ（再起動で消える）。Supabaseキー未設定のため。")
    return InMemoryStore()
