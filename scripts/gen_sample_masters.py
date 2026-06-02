"""
デモ用マスタCSVを3パターン生成するスクリプト

3つの店舗規模を用意し、それぞれ data/sample/<pattern>/ に
roles.csv / positions.csv / skills.csv / staff.csv を書き出す。

role_id / skill_id の参照整合性を保証するため、スタッフのスキルは
そのパターンで定義済みのスキルからのみ選ぶ。
（API /setup/masters の整合性チェックを必ず通る作りにする）

実行: python scripts/gen_sample_masters.py
"""

import csv
import random
from pathlib import Path

OUT_ROOT = Path("data/sample")

# スタッフ名は「スタッフ01」のような連番の例データ名を使う。
# （実在しそうな氏名を避け、サンプルだと一目で分かるようにするため）


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def gen_pattern(
    folder: str,
    roles: list[tuple[str, str]],
    positions: list[tuple[str, str]],
    skills: list[tuple[str, str]],
    role_distribution: list[tuple[str, int]],  # (role_id, 人数)
    seed: int,
) -> None:
    """1パターン分のCSV4種を生成"""
    rng = random.Random(seed)
    out = OUT_ROOT / folder

    write_csv(out / "roles.csv", ["id", "name"], [list(r) for r in roles])
    write_csv(out / "positions.csv", ["id", "name"], [list(p) for p in positions])
    write_csv(out / "skills.csv", ["id", "name"], [list(s) for s in skills])

    skill_ids = [s[0] for s in skills]

    # スタッフ生成
    staff_rows: list[list] = []
    person_index = 1

    for role_id, count in role_distribution:
        for _ in range(count):
            pid = f"p{person_index:02d}"
            name = f"スタッフ{person_index:02d}"

            # 新人はスキル0〜1個、それ以外は1〜3個
            if "newbie" in role_id:
                n_skills = rng.choice([0, 0, 1])
            else:
                n_skills = rng.randint(1, min(3, len(skill_ids)))
            chosen = rng.sample(skill_ids, n_skills)

            staff_rows.append([pid, name, role_id, ";".join(chosen)])
            person_index += 1

    write_csv(out / "staff.csv", ["id", "name", "role_id", "skill_ids"], staff_rows)
    print(f"[{folder}] スタッフ{len(staff_rows)}名 / 役職{len(roles)} / "
          f"ポジション{len(positions)} / スキル{len(skills)} を生成")


# ═══════════════════════════════════════════════════════════════════
#  パターンA: 小規模カフェ（8名）
# ═══════════════════════════════════════════════════════════════════
gen_pattern(
    folder="pattern_a_cafe",
    roles=[("r_owner", "オーナー"), ("r_staff", "スタッフ"), ("r_newbie", "新人")],
    positions=[("pos_counter", "カウンター"), ("pos_floor", "フロア")],
    skills=[("sk_coffee", "コーヒー"), ("sk_register", "レジ"), ("sk_food", "フード")],
    role_distribution=[("r_owner", 1), ("r_staff", 5), ("r_newbie", 2)],
    seed=1,
)

# ═══════════════════════════════════════════════════════════════════
#  パターンB: 標準レストラン（30名）★メインデモ
# ═══════════════════════════════════════════════════════════════════
gen_pattern(
    folder="pattern_b_restaurant",
    roles=[
        ("r_leader", "リーダー"), ("r_senior", "シニア"),
        ("r_general", "一般"), ("r_newbie", "新人"),
    ],
    positions=[
        ("pos_hall", "ホール"), ("pos_kitchen", "キッチン"), ("pos_register", "レジ"),
    ],
    skills=[
        ("sk_cashier", "レジ可"), ("sk_bar", "バー"), ("sk_kitchen", "調理"),
        ("sk_open", "オープン作業"), ("sk_close", "クローズ作業"),
    ],
    role_distribution=[
        ("r_leader", 1), ("r_senior", 4), ("r_general", 17), ("r_newbie", 8),
    ],
    seed=2,
)

# ═══════════════════════════════════════════════════════════════════
#  パターンC: 大型居酒屋（50名）
# ═══════════════════════════════════════════════════════════════════
gen_pattern(
    folder="pattern_c_izakaya",
    roles=[
        ("r_manager", "店長"), ("r_leader", "リーダー"), ("r_regular", "一般"),
        ("r_part", "アルバイト"), ("r_newbie", "新人"),
    ],
    positions=[
        ("pos_hall", "ホール"), ("pos_kitchen", "キッチン"),
        ("pos_drink", "ドリンク"), ("pos_cashier", "レジ"),
    ],
    skills=[
        ("sk_cook", "調理"), ("sk_drink", "ドリンク作成"), ("sk_register", "レジ"),
        ("sk_open", "オープン作業"), ("sk_close", "クローズ作業"), ("sk_lead", "リーダー業務"),
    ],
    role_distribution=[
        ("r_manager", 1), ("r_leader", 4), ("r_regular", 20),
        ("r_part", 17), ("r_newbie", 8),
    ],
    seed=3,
)

print("\n完了: data/sample/ に3パターンを生成しました")
