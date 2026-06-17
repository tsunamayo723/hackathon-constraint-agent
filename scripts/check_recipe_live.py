"""
T8の実Gemini検証: 未知type → AIがレシピ設計 → 検証 → 承認 → 反映

前提: バックエンド起動済み（http://localhost:8001）＋ GEMINI_API_KEY 設定済み。
  Flash: note解釈1回＋埋め込み1回 ／ Pro: レシピ設計（デモ3type分）。数円。

実行: python scripts/check_recipe_live.py

確認すること:
  1. RecipeAgent(Pro)がデモ3typeで**妥当なレシピ（操作×選択子）**を出すか
  2. validate_recipe が合格するか・confidence/concerns
  3. recurring_day_off を承認→埋め込み→run-storedで水曜が消えるか
"""

import json

import pandas as pd
import requests

API = "http://localhost:8001"
CSV = "data/sample/pattern_a_cafe/desired_shifts.csv"


def show(title, data):
    print(f"\n=== {title} ===")
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


masters = {
    "persons": [{"id": f"p{i:02d}", "name": f"スタッフ{i:02d}",
                 "role_id": "r_staff", "skill_ids": []} for i in range(1, 9)],
    "positions": [{"id": "pos_hall", "name": "ホール"}],
    "roles": [{"id": "r_staff", "name": "スタッフ"}],
    "skills": [],
}
frame = {
    "period": {"start": "2026-11-01", "end": "2026-11-14"},
    "operating_window": {"open": "11:00", "close": "22:00", "slot_minutes": 60},
    "policy_mode": "balance",
}

requests.post(f"{API}/setup/reset-constraints", timeout=20)
print("masters:", requests.post(f"{API}/setup/masters", json=masters, timeout=20).status_code)
print("frame  :", requests.post(f"{API}/setup/frame", json=frame, timeout=20).status_code)

df = pd.read_csv(CSV, dtype=str).fillna("")
df = df[df["person_id"].isin({p["id"] for p in masters["persons"]})]
records = []
for r in df.to_dict(orient="records"):
    rec = {"person_id": r["person_id"], "date": r["date"], "start": r["start"], "end": r["end"]}
    if r.get("note", "").strip():
        rec["note"] = r["note"].strip()
    records.append(rec)
print("desired:", requests.post(f"{API}/setup/desired-shifts", json=records, timeout=30).status_code)
hc = [{"slot_label": "昼", "time_start": "11:00", "time_end": "15:00", "position_id": "pos_hall", "count": 2},
      {"slot_label": "夜", "time_start": "18:00", "time_end": "22:00", "position_id": "pos_hall", "count": 2}]
requests.post(f"{API}/setup/headcounts", json=hc, timeout=20)

# ── 備考解釈（新ルール候補を承認キューへ） ───────────────────────────
d = requests.post(f"{API}/setup/interpret-notes", timeout=120).json()
print(f"\n🆕新ルール候補: {len(d.get('新ルール候補', []))} 件")

q = requests.get(f"{API}/admin/pending-types", params={"status": "pending"}, timeout=20).json()
by_type = {p["suggested_type_name"]: p for p in q}

# ── 各デモtypeで RecipeAgent にレシピ設計させる（Pro） ───────────────
for tname in ("recurring_day_off", "max_late_shift_count", "exam_period"):
    p = by_type.get(tname)
    if not p:
        print(f"\n[skip] {tname} は検出されませんでした")
        continue
    g = requests.post(f"{API}/admin/pending-types/{p['id']}/generate", timeout=180).json()
    show(f"レシピ設計: {tname}", {
        "テスト": g.get("テスト"), "自信度": g.get("自信度"),
        "レシピ": g.get("レシピ"), "例レシピ": g.get("例レシピ"),
        "懸念点": g.get("懸念点"), "説明": g.get("説明"),
    })

# ── recurring_day_off を承認→反映 ───────────────────────────────────
rdo = by_type.get("recurring_day_off")
if rdo:
    ap = requests.post(f"{API}/admin/pending-types/{rdo['id']}/approve", timeout=120).json()
    show("承認", ap)
    diff = requests.post(f"{API}/solver/preview-rule-effect",
                         json={"type_name": "recurring_day_off"}, timeout=120).json()
    print(f"\n反映効果: 消えた割当 {len(diff['diff']['removed'])} 件 / handler_failed={diff.get('handler_failed')}")
    for a in diff["diff"]["removed"][:8]:
        print(f"  ❌ {a['person_id']} {a['date']} {a['start']}-{a['end']}")

usage = requests.get(f"{API}/admin/usage", timeout=20).json()
show("Gemini消費", usage.get("合計", usage))
