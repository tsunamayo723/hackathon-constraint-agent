"""
T2の実サーバー検証: 承認 → params化 → 自動再計算（before/after差分）

前提: バックエンド起動済み（http://localhost:8001）。実Geminiを使う。
  Flash: note解釈1回 ＋ params化1回 ／ Pro: ハンドラ生成1回（数円）

実行: python scripts/check_t2_live.py

確認すること:
  1. recurring_day_off が承認され、各人の原文が params化されて dynamic_constraints に入る
  2. preview-rule-effect が「水曜の割当が消えた」を before/after で返す
  3. run-stored が確定版（pending無し）になり、水曜の割当が消えている
"""

import json

import pandas as pd
import requests

API = "http://localhost:8001"
CSV = "data/sample/pattern_a_cafe/desired_shifts.csv"


def show(title, data):
    print(f"\n=== {title} ===")
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


# ── ① 土台（マスタ＋営業情報＋必要人数＋出勤希望） ──────────────────
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

# pattern_a のCSVから p01〜p08 のぶんだけ使う（ルール系noteを含む）
df = pd.read_csv(CSV, dtype=str).fillna("")
df = df[df["person_id"].isin({p["id"] for p in masters["persons"]})]
records = []
for r in df.to_dict(orient="records"):
    rec = {"person_id": r["person_id"], "date": r["date"], "start": r["start"], "end": r["end"]}
    if r.get("note", "").strip():
        rec["note"] = r["note"].strip()
    records.append(rec)
print("desired:", requests.post(f"{API}/setup/desired-shifts", json=records, timeout=30).status_code,
      f"({len(records)}件)")

hc = [{"slot_label": "昼", "time_start": "11:00", "time_end": "15:00", "position_id": "pos_hall", "count": 2},
      {"slot_label": "夜", "time_start": "18:00", "time_end": "22:00", "position_id": "pos_hall", "count": 2}]
print("headcnt:", requests.post(f"{API}/setup/headcounts", json=hc, timeout=20).status_code)

# ── ② 備考解釈（新ルール候補を承認キューへ） ───────────────────────
d = requests.post(f"{API}/setup/interpret-notes", timeout=120).json()
print(f"\n解釈: 🆕新ルール候補 {len(d.get('新ルール候補', []))} 件")

q = requests.get(f"{API}/admin/pending-types", params={"status": "pending"}, timeout=20).json()
target = next((p for p in q if p["suggested_type_name"] == "recurring_day_off"), None)
if target is None:
    print("!! recurring_day_off が検出されませんでした。中断します。")
    raise SystemExit(1)
print(f"対象: {target['suggested_type_name']}（出現{target['occurrence_count']}回 / id={target['id']}）")

# ── ③ ハンドラ生成（Pro） ──────────────────────────────────────────
g = requests.post(f"{API}/admin/pending-types/{target['id']}/generate", timeout=180).json()
print(f"\n生成: テスト={g.get('テスト')} / 自信度={g.get('自信度')}")

# ── ④ 承認（params化が走る） ────────────────────────────────────────
ap = requests.post(f"{API}/admin/pending-types/{target['id']}/approve", timeout=120).json()
show("承認結果", ap)
show("dynamic_constraints（保存された材料）", requests.get(f"{API}/admin/pending-types/{target['id']}").json().get("occurrences"))

# ── ⑤ before/after 差分 ─────────────────────────────────────────────
diff = requests.post(f"{API}/solver/preview-rule-effect", json={"type_name": "recurring_day_off"}, timeout=120).json()
print(f"\n=== 反映効果（before/after） ===")
print(f"消えた割当: {len(diff['diff']['removed'])} 件 / 増えた割当: {len(diff['diff']['added'])} 件")
for a in diff["diff"]["removed"][:10]:
    print(f"  ❌ {a['person_id']} {a['date']} {a['position_id']} {a['start']}-{a['end']}")

# ── ⑥ 確定版になるか ───────────────────────────────────────────────
out = requests.post(f"{API}/solver/run-stored", timeout=120).json()
print(f"\nrun-stored: status={out['status']} / shift_status={out['shift_status']}")
