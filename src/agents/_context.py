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

    # 在籍スタッフ（person_id = 名前 / 役職）。AIが「田中さん」や役職を実IDに解決できるように。
    if masters.persons:
        person_lines = "\n".join(
            f"  - {p.id} = {p.name}（役職: {p.role_id or '―'}）" for p in masters.persons
        )
    else:
        person_lines = "  - （スタッフ未登録）"

    # 役職ごとの所属（「新人は…」のような役職指定を who=\"role\" に落とせるように）
    role_name = {r.id: r.name for r in masters.roles}
    members: dict[str, list[str]] = {}
    for p in masters.persons:
        if p.role_id:
            members.setdefault(p.role_id, []).append(p.id)
    if members:
        group_lines = "\n".join(
            f"  - {rid}（{role_name.get(rid, rid)}）: {', '.join(ids)}"
            for rid, ids in members.items()
        )
    else:
        group_lines = "  - （所属情報なし）"

    return (
        "利用可能なポジション（position_id = 名前。ここに無いIDは作らない）:\n"
        f"{_lines(masters.positions, '（ポジション未登録）')}\n"
        "利用可能な役職（role_id = 名前）:\n"
        f"{_lines(masters.roles, '（役職なし）')}\n"
        "利用可能なスキル（skill_id = 名前）:\n"
        f"{_lines(masters.skills, '（スキルなし）')}\n"
        "在籍スタッフ（person_id = 名前 / 役職）:\n"
        f"{person_lines}\n"
        "役職ごとの所属（role_id（名前）: 所属person_id。"
        "「新人は…」等の役職指定は who=\"role\" でこの role_id を使う）:\n"
        f"{group_lines}"
    )
