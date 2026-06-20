"""
ハンドラ辞書

type名 → ハンドラ関数 の対応表。
ハンドラは「制約1件を OR-Tools の制約・罰金に翻訳する」関数。

★ここがエージェントの肝★
- 既知タイプ: 最初から HANDLERS に登録（AIを毎回呼ばない）。引数は Pydantic params。
- 未知タイプ: L2フローでAIが生成→承認されたら register_dynamic_handler で動的登録。
              引数は dict params（生成ハンドラの契約 def handle(params, ctx)）。

get_handler は「組み込み → 動的」の順で探す。
動的登録は当面インメモリ（再起動で消える。永続化はSupabase段階）。
"""

from .builtin import (
    handle_availability,
    handle_headcount,
    handle_prefer_person,
    handle_separate,
)

# 組み込み（既知16typeのうち実装済み）。引数は Pydantic params。
HANDLERS = {
    "headcount_requirement": handle_headcount,
    "availability": handle_availability,
    "separate": handle_separate,
    "prefer_person": handle_prefer_person,
}

# AIが生成し承認された動的ハンドラ。引数は dict params。
_DYNAMIC_HANDLERS: dict = {}


def get_handler(type_name: str):
    """type名に対応するハンドラを返す（組み込み→動的の順）。未登録なら None。"""
    if type_name in HANDLERS:
        return HANDLERS[type_name]
    return _DYNAMIC_HANDLERS.get(type_name)


def register_dynamic_handler(type_name: str, handler_code: str) -> None:
    """
    承認された生成コードを読み込み、動的ハンドラとして登録する。

    handler_code は `def handle(params, ctx): ...` を定義する文字列。
    ※ 承認済み（人がレビュー済み）のコードのみを渡すこと。本番プロセスで実行される。
    """
    namespace: dict = {}
    exec(handler_code, namespace)  # noqa: S102 — 承認済みハンドラの登録（設計上の意図）
    handle = namespace.get("handle")
    if not callable(handle):
        raise ValueError("handle(params, ctx) 関数が定義されていません")
    _DYNAMIC_HANDLERS[type_name] = handle


def is_registered(type_name: str) -> bool:
    """そのtypeのハンドラが使える状態か（組み込み or 動的登録済み）。"""
    return type_name in HANDLERS or type_name in _DYNAMIC_HANDLERS


def list_dynamic_handlers() -> list[str]:
    """動的登録済みのtype名一覧。"""
    return list(_DYNAMIC_HANDLERS.keys())
