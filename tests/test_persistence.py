"""
永続化の差し替え口（persistence.py）＋ storage の配線テスト（Gemini/Supabase 不要）。

- InMemoryStore が get/set で素直に往復する
- _looks_configured が雛形・空・非ASCII を「未設定」扱いにする（誤接続防止）
- get_store はキー未設定なら InMemoryStore を返す（安全フォールバック）
- storage.py が _store 越しに dynamic_constraints を保存/取得/クリアできる（配線確認）
"""

from src import storage
from src.persistence import InMemoryStore, _looks_configured, get_store


def test_inmemory_store_roundtrip():
    s = InMemoryStore()
    assert s.get("missing", []) == []          # 無いキーは default
    s.set("k", [{"a": 1}])
    assert s.get("k") == [{"a": 1}]


def test_looks_configured_rejects_placeholders():
    assert not _looks_configured("", "")                                      # 空
    assert not _looks_configured("https://your-project.supabase.co", "x")     # URL雛形
    assert not _looks_configured("https://abc.supabase.co", "your_service_role_key_here")  # キー雛形
    assert _looks_configured("https://abc.supabase.co", "ey.real.key")        # 実物っぽい→OK


def test_get_store_falls_back_to_inmemory(monkeypatch):
    """Supabaseキーが無ければ InMemoryStore（デモを止めない）。"""
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    assert isinstance(get_store(), InMemoryStore)


def test_storage_routes_through_store():
    """storage の dynamic_constraints が保存口越しに往復する（追記・順序保持・クリア）。"""
    storage.clear_dynamic_constraints()
    assert storage.get_dynamic_constraints() == []

    storage.save_dynamic_constraints([{"type": "x", "params": {"a": 1}}])
    storage.save_dynamic_constraints([{"type": "y", "params": {"b": 2}}])
    got = storage.get_dynamic_constraints()
    assert [g["type"] for g in got] == ["x", "y"]     # 追記され、順序が保たれる

    storage.clear_dynamic_constraints()
    assert storage.get_dynamic_constraints() == []
