"""
デモデータ生成スクリプト（10人 × 10日 × 3パターン）

手書きで数百行のCSVを書くと事故るので、設計をコードで表現して生成する（再生成可能）。
出力先: data/demo/<pattern>/ に roles/positions/skills/staff/headcounts/desired_shifts.csv ＋ meta.json

期間は 2026-11-02(月)〜11-11(水) の10日。水曜が2回（11/04, 11/11）入るので
「毎週水曜は入れません」が2日に効く（デモの肝）。30分スロット。

前提条件（2026-06 改修）: 1人1日は「連続1ライン・基本最大8時間」（ソルバーのハード制約）。
そのため昼番と夜番は別人で埋める設計にし、各パターンとも「1ライン編成で店舗が充足する」よう
人数配分を組んでいる（`scripts/verify_demo_data.py` で実測検証）。

3パターン（営業時間も店ごとに変える）:
  cafe_easy   … カフェ 11:00-20:00・余裕あり。基本動作と「自分も店舗もOK」が綺麗に出る（主役）
  diner_tight … 定食屋 11:00-23:00・必要人数が多めでタイト。制約の効き目がはっきり出る
  izakaya_late… 居酒屋 16:00-24:00・ディナー偏重＆遅番中心。深夜系ルールが映える

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

# ── 共通マスタ語彙（カフェ系。全パターンで共通にして単純化） ────────────
ROLES = [("r_owner", "オーナー"), ("r_staff", "スタッフ"), ("r_newbie", "新人")]
POSITIONS = [("pos_counter", "カウンター"), ("pos_floor", "フロア")]
SKILLS = [("sk_coffee", "コーヒー"), ("sk_register", "レジ"), ("sk_food", "フード")]

# 共通スタッフ10名（id, 名前, 役職, スキル）。p01 がデモの主役（提出者）。
# p08/p09 が新人（r_newbie）＝「新人だけにしない」等の役職ルールのデモ対象。
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
# open/close:  店ごとの営業時間（案A: パターン別にバラけさせる）
# late_start:  late_only の人がその時刻から入る（遅番のみ可）。None なら late_only 無効
# off_on_wed:  水曜に出られない人（水曜の母数を絞り、主役 p01 を必要にする）
# late_only:   open からではなく late_start から入る人（遅番テーマ）
# headcounts:  (slot_label, time_start, time_end, position_id, count)
#   ※ 1人1日=連続1ラインなので、昼帯と夜帯は別人で埋まる前提で人数を置く。
PATTERNS = {
    "cafe_easy": {
        "label": "カフェ（11:00-20:00・標準/余裕あり）",
        "description": "カフェ。11:00〜20:00。10人で無理なく回る基本シナリオ。提出者の『毎週水曜NG』が反映され、店舗も必要人数を満たすのが綺麗に見える主役データ。",
        "policy_mode": "balance",
        "open": "11:00", "close": "20:00", "late_start": "16:00",
        "headcounts": [
            ("ランチ", "11:00", "15:00", "pos_counter", 1),
            ("ランチ", "11:00", "15:00", "pos_floor", 1),
            ("ディナー", "16:00", "20:00", "pos_counter", 1),
            ("ディナー", "16:00", "20:00", "pos_floor", 2),
        ],
        # 水曜に出られないのは {p09,p10}。残り8人（うち主役p01）で昼2・夜3を1ライン編成。
        # p01 を抜いても7人で賄える「余裕あり」バランス。
        "off_on_wed": {"p09", "p10"},
        "late_only": set(),
    },
    "diner_tight": {
        "label": "定食屋（11:00-23:00・必要人数多めでタイト）",
        "description": "定食屋。11:00〜23:00と長め。必要人数が人員に対して多め。備考を無視すると無理が出やすく、AIが翻訳して組み込むと収まる…という制約の効き目が見えるシナリオ。",
        "policy_mode": "balance",
        "open": "11:00", "close": "23:00", "late_start": "16:00",
        "headcounts": [
            ("ランチ", "11:00", "15:00", "pos_counter", 1),
            ("ランチ", "11:00", "15:00", "pos_floor", 2),
            ("ディナー", "18:00", "23:00", "pos_counter", 1),
            ("ディナー", "18:00", "23:00", "pos_floor", 3),
        ],
        # タイト: 昼3・夜4を1ライン（別人）で埋める＝1日7人。水曜の欠席は最小限。
        "off_on_wed": {"p10"},
        "late_only": {"p04"},  # 1名は16時から（夜寄り）
    },
    "izakaya_late": {
        "label": "居酒屋（16:00-24:00・ディナー偏重/遅番中心）",
        "description": "居酒屋。16:00〜24:00の夜営業。早番(16時〜)と遅番(20時〜)中心で夜の必要人数が多い。『22時以降は月◯回まで』のような深夜系ルールが映えるシナリオ。",
        "policy_mode": "balance",
        "open": "16:00", "close": "24:00", "late_start": "20:00",
        "headcounts": [
            ("早番", "16:00", "20:00", "pos_counter", 1),
            ("早番", "16:00", "20:00", "pos_floor", 1),
            ("遅番", "20:00", "24:00", "pos_counter", 1),
            ("遅番", "20:00", "24:00", "pos_floor", 3),
        ],
        "off_on_wed": {"p05", "p06", "p09"},
        # 一部スタッフは遅番(20:00-24:00)のみ → 夜偏重を表現
        "late_only": {"p07", "p10"},
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
    open_hhmm, close_hhmm, late_start = cfg["open"], cfg["close"], cfg["late_start"]
    rows: list[list] = []
    for pid, _name, _role, _skills in STAFF:
        for d in DATES:
            # 水曜に出られない人はその日の行を作らない（＝出勤不可）
            if d in WEDNESDAYS and pid in off_wed:
                continue
            start = late_start if (late_start and pid in late_only) else open_hhmm
            end = close_hhmm
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
                "operating_window": {"open": cfg["open"], "close": cfg["close"], "slot_minutes": 30},
                "policy_mode": cfg["policy_mode"],
            },
            # デモの主役（提出者）。React の「デモの希望を読み込む」既定＋overall_note。
            "demo_submitter": {"person_id": "p01", "overall_note": HERO_NOTE},
        }
        (pdir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[OK] {key}: {cfg['open']}-{cfg['close']} staff={len(STAFF)} dates={len(DATES)} -> {pdir}")


if __name__ == "__main__":
    generate()
