"""
デモデータ投入系（/setup/demo-patterns・/setup/load-demo・/submit/demo-wishes）と
投入データを使った /submit/preview の比較（Gemini不要・ソルバーを実際に回す）。

- demo-patterns が3パターンを返す
- load-demo(cafe_easy) でマスタ10名・10日・必要人数・出勤希望が一括登録される
- demo-wishes(p01) が希望10日分＋overall_note（毎週水曜）を返す
- 投入データで preview すると、before で p01 が水曜に入り、after で消え、店舗は充足維持
"""

from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)

WEDNESDAYS = {"2026-11-04", "2026-11-11"}
FORBID_WED = {"operation": "forbid", "who": "person",
              "when": "weekday", "weekday": 2, "band": "all_day"}


def test_demo_patterns_lists_three():
    r = client.get("/setup/demo-patterns")
    assert r.status_code == 200
    keys = {p["key"] for p in r.json()["patterns"]}
    assert {"cafe_easy", "diner_tight", "izakaya_late"} <= keys


def test_load_demo_registers_everything():
    r = client.post("/setup/load-demo", json={"pattern": "cafe_easy"})
    assert r.status_code == 200
    gaiyou = r.json()["概要"]
    assert gaiyou["スタッフ数"] == 10
    assert gaiyou["提出者(主役)"] == "p01"
    # マスタ・営業情報・出勤希望が入っている
    assert client.get("/setup/masters").status_code == 200
    assert client.get("/setup/frame").status_code == 200
    assert client.get("/setup/desired-shifts").json()["件数"] > 0


def test_load_demo_unknown_pattern_404():
    r = client.post("/setup/load-demo", json={"pattern": "no_such_pattern"})
    assert r.status_code == 404


def test_demo_wishes_returns_wishes_and_overall_note():
    client.post("/setup/load-demo", json={"pattern": "cafe_easy"})
    r = client.get("/submit/demo-wishes", params={"person_id": "p01"})
    assert r.status_code == 200
    body = r.json()
    # 主役 p01 は10日分の希望＋overall_note（毎週水曜）
    assert len(body["wishes"]) == 10
    assert "水曜" in body["overall_note"]
    # 各希望に date/start/end/note が揃っている
    assert all({"date", "start", "end", "note"} <= set(w) for w in body["wishes"])


def test_preview_on_demo_data_removes_wednesday_and_keeps_store():
    client.post("/setup/load-demo", json={"pattern": "cafe_easy"})
    wishes = [w | {} for w in client.get(
        "/submit/demo-wishes", params={"person_id": "p01"}).json()["wishes"]]
    r = client.post("/submit/preview", json={
        "person_id": "p01", "type_name": "recurring_day_off",
        "wishes": wishes, "recipe": FORBID_WED,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["recipe_applied"] is True

    before_wed = {a["date"] for a in body["personal"]["before"]} & WEDNESDAYS
    after_wed = {a["date"] for a in body["personal"]["after"]} & WEDNESDAYS
    assert before_wed == WEDNESDAYS      # 考慮なしでは両水曜に入っていた
    assert after_wed == set()            # 考慮ありで両水曜が消えた
    # 店舗は after でも充足（控えが水曜を埋める）
    assert body["store"]["after_ok"] is True
    assert body["after"]["coverage_score"] == 100.0


def test_commit_then_run_stored_reflects_individual():
    # 個人の希望(p01・全日OK)＋水曜forbidを commit → run-stored で水曜が消え、店舗は充足
    client.post("/setup/load-demo", json={"pattern": "cafe_easy"})
    wishes = client.get("/submit/demo-wishes", params={"person_id": "p01"}).json()["wishes"]
    c = client.post("/submit/commit", json={
        "person_id": "p01", "type_name": "recurring_day_off",
        "wishes": wishes, "recipe": FORBID_WED,
    })
    assert c.status_code == 200
    assert c.json()["recipe_applied"] is True

    r = client.post("/solver/run-stored")
    assert r.status_code == 200
    out = r.json()
    p01_wed = {a["date"] for a in out["assignments"]
               if a["person_id"] == "p01" and a["date"] in WEDNESDAYS}
    assert p01_wed == set()                      # 水曜は割り当てられていない
    assert out["meta"]["shortage_units"] == 0    # 店舗は充足（控えが埋める）


def test_store_compare_before_after():
    # ⑤用：note考慮なし(before)では p01 が水曜に入り、考慮あり(after)では消え、店舗は充足
    client.post("/setup/load-demo", json={"pattern": "cafe_easy"})
    wishes = client.get("/submit/demo-wishes", params={"person_id": "p01"}).json()["wishes"]
    r = client.post("/submit/store-compare", json={
        "person_id": "p01", "type_name": "recurring_day_off",
        "wishes": wishes, "recipe": FORBID_WED,
    })
    assert r.status_code == 200
    body = r.json()
    before_wed = {a["date"] for a in body["before"]["assignments"]
                  if a["person_id"] == "p01" and a["date"] in WEDNESDAYS}
    after_wed = {a["date"] for a in body["after"]["assignments"]
                 if a["person_id"] == "p01" and a["date"] in WEDNESDAYS}
    assert len(before_wed) >= 1       # 考慮なしでは（少なくとも一方の）水曜に入る
    assert after_wed == set()         # 考慮ありで水曜が消える
    assert body["store"]["after_ok"] is True
    # 全体シフトが返っている（before/after とも複数スタッフ分の割当）
    assert len(body["before"]["assignments"]) > 0
    assert len(body["after"]["assignments"]) > 0


def test_preview_translates_per_day_note(monkeypatch):
    """日ごとnote（「17時まで」）をAIが時間補正し、after に反映する（NoteAgentをモック）。"""
    client.post("/setup/load-demo", json={"pattern": "cafe_easy"})

    from src.agents.note_agent import NoteResult

    class FakeNoteAgent:
        def interpret(self, items):
            # 最初のnote付き項目を 17:00 までに時間補正する想定
            return [NoteResult(index=0, interpretable=True, new_end="17:00")]

    monkeypatch.setattr("src.llm.is_available", lambda: True)
    monkeypatch.setattr("src.agents.NoteAgent", FakeNoteAgent)

    wishes = [
        {"date": "2026-11-02", "start": "11:00", "end": "22:00",
         "note": "お迎えがあるので17時までにしてほしいです"},
        {"date": "2026-11-05", "start": "11:00", "end": "22:00"},
    ]
    r = client.post("/submit/preview", json={
        "person_id": "p01", "wishes": wishes, "recipe": None,
    })
    assert r.status_code == 200
    body = r.json()
    # noteが時間補正として適用され、note_applied=True（recipe無しでもnote効果で成立）
    assert body["notes_adjusted"] == 1
    assert body["note_applied"] is True
    assert any(n["status"] == "applied" for n in body["note_results"])
