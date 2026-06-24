"""
テスト全体の共通設定。

最重要: `storage._store` を毎テスト「まっさらな InMemoryStore」に差し替える。
.env に Supabase キーが入っていても、**テストは実DBを一切触らない**
（本番テーブルを汚さない・ネットワーク待ちが無く速い・テスト同士も独立になる）。

実DB（Supabase）接続の確認は、ユニットテストではなく
手動のライブチェック（scripts / scratchpad）で行う方針。
"""

import pytest

from src import storage
from src.persistence import InMemoryStore


@pytest.fixture(autouse=True)
def isolate_store():
    """各テストを独立した InMemoryStore に固定（実Supabaseを触らせない）。"""
    storage._store = InMemoryStore()
    yield
