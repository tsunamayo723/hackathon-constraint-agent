"""
エージェント共通: 実マスタをプロンプトへ注入する文脈づくり

パーサやレシピ生成のプロンプトに「実在するID（pos_floor 等）」を渡すことで、
AIが存在しないポジションID（pos_hall 等）を捏造する不具合を構造的に防ぐ。

storage に依存するが、未登録（None）でも安全に動く（一般的推定にフォールバック）。
"""

from src import storage


def masters_context() -> str:
    """現在のマスタを「ID＝名前」の一覧テキストにして返す。

    未登録なら、AIに一般的な推定を許す短い注記を返す（プロンプトを壊さない）。
    """
    masters = storage.get_masters()
    if masters is None:
        return "（マスタ未登録。一般的なIDで推定してよいが、確信が持てなければ未知扱いにする）"

    def _lines(items, empty: str) -> str:
        if not items:
            return f"  - {empty}"
        return "\n".join(f"  - {it.id} = {it.name}" for it in items)

    return (
        "利用可能なポジション（position_id = 名前。ここに無いIDは作らない）:\n"
        f"{_lines(masters.positions, '（ポジション未登録）')}\n"
        "利用可能な役職（role_id = 名前）:\n"
        f"{_lines(masters.roles, '（役職なし）')}\n"
        "利用可能なスキル（skill_id = 名前）:\n"
        f"{_lines(masters.skills, '（スキルなし）')}"
    )
