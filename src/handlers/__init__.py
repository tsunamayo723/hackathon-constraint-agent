"""
ハンドラ辞書

type名 → ハンドラ関数 の対応表。
ハンドラは「制約1件を OR-Tools の制約・罰金に翻訳する」関数。

★ここがエージェントの肝★
将来 AI（L2フロー）が未知タイプのハンドラを自動生成したら、
このHANDLERS辞書に追記して永続登録する。
既知タイプは最初からここに登録しておく（＝AIを毎回呼ばない）。
"""

from .builtin import handle_availability, handle_headcount, handle_separate

# type名 → ハンドラ関数
HANDLERS = {
    "headcount_requirement": handle_headcount,
    "availability": handle_availability,
    "separate": handle_separate,
}


def get_handler(type_name: str):
    """type名に対応するハンドラを返す。未登録なら None。"""
    return HANDLERS.get(type_name)
