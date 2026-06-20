"""
デモデータ生成スクリプト（10人 × 10日 × 3パターン）

手書きで数百行のCSVを書くと事故るので、設計をコードで表現して生成する（再生成可能）。
出力先: data/demo/<pattern>/ に roles/positions/skills/staff/headcounts/desired_shifts.csv ＋ meta.json

期間は 2026-11-02(月)〜11-11(水) の10日。水曜が2回（11/04, 11/11）入るので
「毎週水曜は入れません」が2日に効く（デモの肝）。営業 11:00-22:00・30分スロット。

3パターン:
  cafe_easy   … カフェ・余裕あり。基本動作と「自分も店舗もOK」が綺麗に出る（主役）
  diner_tight … 定食屋・必要人数が多めでタイト。制約の効き目がはっきり出る
  izakaya_late… 居酒屋・ディナー偏重＆遅番多め。深夜系ルールが映える

使い方:  python scripts/gen_demo_data.py
"""

import csv
import json
import sys
from pathlib import Path

# Windowsコンソール(cp932)でも文字化けしないよう標準出力をUTF-8に
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = ROOT / "data" / "demo"

# ── 共通の枠 ──────────────────────────────────────────────────────────
DATES = [f"2026-11-{d:02d}" for d in range(2, 12)]  # 11/02..11/11（10日）
WEDNESDAYS = {"2026-11-04", "2026-11-11"}            # この期間の水曜（weekday=2）
OPEN, CLOSE = "11:00", "22:00"

# ── 共通マスタ語彙（カフェ系。全パターンで共通にして単純化） ────────────
ROLES = [("r_owner", "オーナー"), ("r_staff", "スタッフ"), ("r_newbie", "新人")]
POSITIONS = [("pos_counter", "カウンター"), ("pos_floor", "フロア")]
SKILLS = [("sk_coffee", "コーヒー"), ("sk_register", "レジ"), ("sk_food", "フード")]

# 共通スタッフ10名（id, 名前, 役職, スキル）。p01 がデモの主役（提出者）。
STAFF = [
    ("p01", "スタッフ01", "r_staff", ["sk_coffee", "sk_register"]),
    ("p02", "スタッフ02", "r_owner", ["sk_coffee", "sk_food"]),
    ("p03", "スタッフ03", "r_staff", ["sk_register"]),
    ("p04", "スタッフ04", "r_staff", ["sk_coffee"]),
    ("p05", "スタッフ05", "r_staff", ["sk_register", "sk_food"]),
    ("p06", "スタッフ06", "r_staff", ["sk_coffee"]),
    ("p07", "スタッフ07", "r_staff", ["sk_register"]),
    ("p08", "スタッフ08", "r_newbie", ["sk_coffee"]),
    ("p09", "スタッフ09", "r_newbie", []),
    ("p10", "スタッフ10", "r_staff", ["sk_food"]),
]

# デモ用の備考（per-day note）。NoteAgent の3分類を一通り踏ませる題材。
#   ✅時間補正 / 🆕新ルール候補(max_late_shift_count, exam_period) / ⚠️申し送り
# ※ 主役 p01 は per-day note を持たせず、overall_note（毎週水曜）で before/after を見せる。
COMMON_NOTES = {
    ("p05", "2026-11-06"): "お迎えがあるので17時までにしてほしいです",
    ("p06", "2026-11-05"): "通院のため午前は入れません。16時から入ります",
    ("p07", "2026-11-03"): "22時以降のシフトは月3回までにしてほしいです",
    ("p03", "2026-11-10"): "11/9〜11/11が試験期間なので極力入れないでください",
    ("p10", "2026-11-07"): "この日はできれば遅番希望です",
}

HERO_NOTE = "毎週水曜は習い事があって入れません"


# ── パターン定義 ──────────────────────────────────────────────────────
# off_on_wed: 水曜に出られない人（水曜の母数を絞り、主役 p01 を必要にする）
# late_only:  終日ではなく16:00-22:00だけ可（遅番テーマ用）
# headcounts: (slot_label, time_start, time_end, position_id, count)
PATTERNS = {
    "cafe_easy": {
        "label": "カフェ（標準・余裕あり）",
        "description": "10人で無理なく回る基本シナリオ。提出者の『毎週水曜NG』が反映され、店舗も充足100%を保つのが綺麗に見える主役データ。",
        "policy_mode": "balance",
        "headcounts": [
            ("ランチ", "11:00", "15:00", "pos_counter", 1),
            ("ランチ", "11:00", "15:00", "pos_floor", 2),
            ("ディナー", "17:00", "22:00", "pos_counter", 1),
            ("ディナー", "17:00", "22:00", "pos_floor", 3),
        ],
        # 水曜に出られるのは {p01,p03,p04,p07,p08}。必要人数（昼3・夜4）に対し
        # p01 が水曜に必要になり、抜けても残り4人で賄える絶妙なバランス。
        "off_on_wed": {"p02", "p05", "p06", "p09", "p10"},
        "late_only": set(),
    },
    "diner_tight": {
        "label": "定食屋（必要人数が多くタイト）",
        "description": "必要人数が人員に対して多め。備考を無視すると無理が出やすく、AIが翻訳して組み込むと収まる…という制約の効き目が見えるシナリオ。",
        "policy_mode": "balance",
        "headcounts": [
            ("ランチ", "11:00", "15:00", "pos_counter", 1),
            ("ランチ", "11:00", "15:00", "pos_floor", 2),
            ("ディナー", "17:00", "22:00", "pos_counter", 2),
            ("ディナー", "17:00", "22:00", "pos_floor", 2),
        ],
        # タイトなので水曜の欠席は最小限（p01を抜いても回るギリギリの母数を残す）
        "off_on_wed": {"p09", "p10"},
        "late_only": set(),
    },
    "izakaya_late": {
        "label": "居酒屋（ディナー偏重・遅番多め）",
        "description": "夜の必要人数が多く、遅番(16時〜)中心。『22時以降は月◯回まで』のような深夜系ルールが映えるシナリオ。",
        "policy_mode": "balance",
        "headcounts": [
            ("ランチ", "11:00", "15:00", "pos_counter", 1),
            ("ランチ", "11:00", "15:00", "pos_floor", 1),
            ("ディナー", "17:00", "22:00", "pos_counter", 2),
            ("ディナー", "17:00", "22:00", "pos_floor", 3),
        ],
        "off_on_wed": {"p05", "p06", "p09"},
        # 一部スタッフは遅番(16:00-22:00)のみ → 夜偏重を表現
        "late_only": {"p04", "p07", "p10"},
    },
}


def _write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def _desired_shifts_rows(cfg: dict) -> list[list]:
    """そのパターンの desired_shifts.csv 行を組み立てる。"""
    off_wed = cfg["off_on_wed"]
    late_only = cfg["late_only"]
    rows: list[list] = []
    for pid, _name, _role, _skills in STAFF:
        for d in DATES:
            # 水曜に出られない人はその日の行を作らない（＝出勤不可）
            if d in WEDNESDAYS and pid in off_wed:
                continue
            start = "16:00" if pid in late_only else OPEN
            end = CLOSE
            note = COMMON_NOTES.get((pid, d), "")
            rows.append([pid, d, start, end, note])
    return rows


def generate() -> None:
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    for key, cfg in PATTERNS.items():
        pdir = DEMO_DIR / key
        pdir.mkdir(parents=True, exist_ok=True)

        _write_csv(pdir / "roles.csv", ["id", "name"], [list(r) for r in ROLES])
        _write_csv(pdir / "positions.csv", ["id", "name"], [list(p) for p in POSITIONS])
        _write_csv(pdir / "skills.csv", ["id", "name"], [list(s) for s in SKILLS])
        _write_csv(
            pdir / "staff.csv",
            ["id", "name", "role_id", "skill_ids"],
            [[pid, name, role, ";".join(skills)] for pid, name, role, skills in STAFF],
        )
        _write_csv(
            pdir / "headcounts.csv",
            ["date", "slot_label", "time_start", "time_end", "position_id", "count"],
            [["", lbl, ts, te, pos, cnt] for lbl, ts, te, pos, cnt in cfg["headcounts"]],
        )
        _write_csv(
            pdir / "desired_shifts.csv",
            ["person_id", "date", "start", "end", "note"],
            _desired_shifts_rows(cfg),
        )

        meta = {
            "key": key,
            "label": cfg["label"],
            "description": cfg["description"],
            "frame": {
                "period": {"start": DATES[0], "end": DATES[-1]},
                "operating_window": {"open": OPEN, "close": CLOSE, "slot_minutes": 30},
                "policy_mode": cfg["policy_mode"],
            },
            # デモの主役（提出者）。React の「デモの希望を読み込む」既定＋overall_note。
            "demo_submitter": {"person_id": "p01", "overall_note": HERO_NOTE},
        }
        (pdir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[OK] {key}: staff={len(STAFF)} dates={len(DATES)} -> {pdir}")


if __name__ == "__main__":
    generate()
