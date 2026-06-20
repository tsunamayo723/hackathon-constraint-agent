"""
デモデータの「肝」をソルバーで実測検証する（Gemini不要・engine.solve を直接呼ぶ）。

各パターンで次が成立するかを確認する:
  1. before（備考考慮なし）で 主役 p01 が水曜に割り当てられている
  2. after （p01の水曜を forbid）で p01 の水曜が消える
  3. after でも店舗の必要人数は満たせている（shortage_units == 0）

CP-SAT は seed 固定で決定的なので、ここが通れば本番でも安定して同じ結果になる。
使い方:  python scripts/verify_demo_data.py
"""

import csv
import json
import sys
from pathlib import Path

# Windowsコンソール(cp932)でも日本語が文字化けしないよう標準出力をUTF-8に
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.models.solver_io import SolverInput  # noqa: E402
from src.solver.engine import solve  # noqa: E402

DEMO_DIR = ROOT / "data" / "demo"
WEDNESDAYS = {"2026-11-04", "2026-11-11"}


def _read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _load_pattern(key: str) -> dict:
    pdir = DEMO_DIR / key
    meta = json.loads((pdir / "meta.json").read_text(encoding="utf-8"))

    persons = []
    for r in _read_csv(pdir / "staff.csv"):
        skills = [s for s in (r.get("skill_ids") or "").split(";") if s.strip()]
        persons.append({"id": r["id"], "name": r["name"],
                        "role_id": r.get("role_id") or None, "skill_ids": skills})
    masters = {
        "persons": persons,
        "positions": _read_csv(pdir / "positions.csv"),
        "roles": _read_csv(pdir / "roles.csv"),
        "skills": _read_csv(pdir / "skills.csv"),
    }

    headcounts = []
    for r in _read_csv(pdir / "headcounts.csv"):
        params = {"slot_label": r["slot_label"], "time_start": r["time_start"],
                  "time_end": r["time_end"], "position_id": r["position_id"],
                  "count": int(r["count"])}
        if r.get("date"):
            params["date"] = r["date"]
        headcounts.append({"type": "headcount_requirement", "params": params})

    availability = []
    for r in _read_csv(pdir / "desired_shifts.csv"):
        availability.append({"type": "availability", "params": {
            "person_id": r["person_id"], "date": r["date"],
            "start": r["start"], "end": r["end"],
        }})

    return {"meta": meta, "masters": masters,
            "headcounts": headcounts, "availability": availability}


def _solve(data: dict, dynamic: list[dict]):
    spec = SolverInput.model_validate({
        "frame": data["meta"]["frame"],
        "masters": data["masters"],
        "constraints": data["headcounts"] + data["availability"],
        "dynamic_constraints": dynamic,
    })
    return solve(spec)


def verify(key: str) -> bool:
    data = _load_pattern(key)
    pid = data["meta"]["demo_submitter"]["person_id"]
    # 本番（store-compare）と同じく、提出者を優先配置（prefer_person）して堅牢にする
    data["availability"].append({
        "type": "prefer_person", "params": {"person_id": pid, "weight": 100},
    })

    forbid_wed = [{"type": "recurring_day_off", "params": {
        "operation": "forbid", "who": "person", "person_id": pid,
        "when": "weekday", "weekday": 2, "band": "all_day",
    }}]

    before = _solve(data, [])
    after = _solve(data, forbid_wed)

    before_wed = sorted({a.date.isoformat() for a in before.assignments
                         if a.person_id == pid and a.date.isoformat() in WEDNESDAYS})
    after_wed = sorted({a.date.isoformat() for a in after.assignments
                        if a.person_id == pid and a.date.isoformat() in WEDNESDAYS})

    before_short = before.meta.shortage_units if before.meta else None
    after_short = after.meta.shortage_units if after.meta else None

    ok_assigned = len(before_wed) > 0
    ok_removed = len(after_wed) == 0
    ok_store = after_short == 0

    print(f"\n=== {key} ({data['meta']['label']}) ===")
    print(f"  before: {pid} の水曜割当 = {before_wed or 'なし'}  / 店舗不足={before_short}")
    print(f"  after : {pid} の水曜割当 = {after_wed or 'なし'}  / 店舗不足={after_short}")
    print(f"  [{'OK' if ok_assigned else 'NG'}] before で p01 が水曜に入っている")
    print(f"  [{'OK' if ok_removed else 'NG'}] after で p01 の水曜が消える")
    print(f"  [{'OK' if ok_store else 'NG'}] after でも店舗は充足（不足0）")
    return ok_assigned and ok_removed and ok_store


if __name__ == "__main__":
    results = {k: verify(k) for k in ("cafe_easy", "diner_tight", "izakaya_late")}
    print("\n---- 総合 ----")
    for k, v in results.items():
        print(f"  {k}: {'PASS' if v else 'FAIL'}")
    sys.exit(0 if all(results.values()) else 1)
