"""
T1の動作確認スクリプト: noteから未知タイプ検出 → 管理者の承認キューに登録

実行: python scripts/check_t1_notes.py
（Gemini Flash を1回だけ呼ぶ。思考オフ・バッチなので1円未満）

確認すること:
  1. 備考が ✅時間補正 / 🆕新ルール候補 / ⚠️未反映 の3つに分類される
  2. 新ルール候補が承認キューに入る（同じタイプ名は1件に集約）
  3. もう一度解釈しても二重登録されない
"""

import json

from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)


def show(title, data):
    print(f"\n=== {title} ===")
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


# ── ① 土台（マスタ・営業情報・出勤希望） ───────────────────────────
masters = {
    "persons": [
        {"id": "p1", "name": "佐藤", "role_id": "r_staff", "skill_ids": []},
        {"id": "p2", "name": "鈴木", "role_id": "r_staff", "skill_ids": []},
        {"id": "p3", "name": "田中", "role_id": "r_staff", "skill_ids": []},
    ],
    "positions": [{"id": "pos_hall", "name": "ホール"}],
    "roles": [{"id": "r_staff", "name": "スタッフ"}],
    "skills": [],
}
frame = {
    "period": {"start": "2026-11-01", "end": "2026-11-07"},
    "operating_window": {"open": "09:00", "close": "22:00", "slot_minutes": 60},
    "policy_mode": "balance",
}
# 2026-11-04 と 11-11 は水曜
desired = [
    {"person_id": "p1", "date": "2026-11-02", "start": "09:00", "end": "22:00",
     "note": "子どものお迎えで17時までにしてください"},                    # → ✅時間補正
    {"person_id": "p1", "date": "2026-11-04", "start": "09:00", "end": "22:00",
     "note": "毎週水曜は習い事があって入れません"},                        # → 🆕 recurring_day_off
    {"person_id": "p2", "date": "2026-11-05", "start": "09:00", "end": "22:00",
     "note": "12/10〜20は試験期間なので極力入れないでください"},            # → 🆕 exam_period
    {"person_id": "p2", "date": "2026-11-03", "start": "09:00", "end": "22:00",
     "note": "毎週水曜は大学の授業があります"},                            # → 🆕 recurring_day_off（集約確認）
    {"person_id": "p3", "date": "2026-11-03", "start": "09:00", "end": "22:00",
     "note": "今月もよろしくお願いします"},                                # → ⚠️未反映
]

assert client.post("/setup/masters", json=masters).status_code == 200
assert client.post("/setup/frame", json=frame).status_code == 200
assert client.post("/setup/desired-shifts", json=desired).status_code == 200

# ── ② 備考をAIで解釈（Gemini Flash 1回） ────────────────────────────
r = client.post("/setup/interpret-notes")
print("HTTP:", r.status_code)
d = r.json()
show("解釈結果（3分類）", {
    "解釈件数": d.get("解釈件数"),
    "✅反映": d.get("反映した備考"),
    "🆕新ルール候補": d.get("新ルール候補"),
    "⚠️未反映": d.get("未反映の備考"),
})

# ── ③ 承認キューの中身（クラスタリング確認） ────────────────────────
q = client.get("/admin/pending-types", params={"status": "pending"}).json()
show("承認キュー", [
    {"id": p["id"], "type": p["suggested_type_name"],
     "出現回数": p["occurrence_count"], "原文": p["source_texts"],
     "出どころ": p["occurrences"]}
    for p in q
])

# ── ④ もう一度解釈 → 二重登録されないこと（Gemini もう1回） ─────────
r2 = client.post("/setup/interpret-notes")
q2 = client.get("/admin/pending-types", params={"status": "pending"}).json()
show("再解釈後のキュー（件数・出現回数が増えないこと）", [
    {"type": p["suggested_type_name"], "出現回数": p["occurrence_count"]}
    for p in q2
])

# ── ⑤ コスト ────────────────────────────────────────────────────────
usage = client.get("/admin/usage").json()
show("Gemini消費", usage.get("合計", usage))
