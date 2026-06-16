"""
T1の実サーバー検証: pattern_a のCSV（ルール系note入り）をアップロード→解釈→キュー確認

実行: python scripts/check_t1_live.py
（起動済みの http://localhost:8001 に対して実行。Gemini Flash 1回 ≒ ¥1）
"""

import json

import pandas as pd
import requests

API = "http://localhost:8001"
CSV = "data/sample/pattern_a_cafe/desired_shifts.csv"

# ── ① UIと同じ形でCSVをアップロード ────────────────────────────────
df = pd.read_csv(CSV, dtype=str).fillna("")
records = []
for r in df.to_dict(orient="records"):
    rec = {"person_id": r["person_id"], "date": r["date"], "start": r["start"], "end": r["end"]}
    if r.get("note", "").strip():
        rec["note"] = r["note"].strip()
    records.append(rec)

resp = requests.post(f"{API}/setup/desired-shifts", json=records, timeout=30)
print("アップロード:", resp.status_code, resp.json() if resp.status_code == 200 else resp.text)

# ── ② 解釈 ──────────────────────────────────────────────────────────
r = requests.post(f"{API}/setup/interpret-notes", timeout=120)
print("解釈:", r.status_code)
d = r.json()
print(f"解釈 {d.get('解釈件数')} 件 / ✅反映 {len(d.get('反映した備考', []))} / "
      f"🆕新ルール候補 {len(d.get('新ルール候補', []))} / ⚠️未反映 {len(d.get('未反映の備考', []))}")
for n in d.get("新ルール候補", []):
    print(f"  🆕 {n['person_id']} {n['date']}「{n['note']}」→ {n.get('suggested_type_name')}")

# ── ③ 承認キュー ────────────────────────────────────────────────────
q = requests.get(f"{API}/admin/pending-types", params={"status": "pending"}, timeout=20).json()
print(f"\n承認キュー: {len(q)} 件")
for p in q:
    print(f"  {p['suggested_type_name']} 出現{p['occurrence_count']}回")
    for s in p["source_texts"]:
        print(f"    - {s}")
