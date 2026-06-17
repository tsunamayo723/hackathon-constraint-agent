"""
レシピ生成フローのテスト（Gemini不要・エージェントはモック）

- engine がレシピ形式の dynamic_constraints を apply_recipe で適用（execしない）
- validate_recipe の合否
- _fill_recipes_and_store がレシピを埋めて保存（本人ID上書き）
- /generate がレシピ方式で動く（RecipeAgentモック）
- 承認→埋め込み→run-stored で水曜が消える（ParamsAgentモック・真のL2一周）
"""

import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import src.handlers as handlers_mod
import src.storage as storage
from src import llm
from src.agents import GeneratedRecipe, ParamItem, ParamsAgent, RecipeAgent
from src.api.main import app
from src.models.admin_queue import PendingTypeRequest
from src.solver.recipe import validate_recipe

client = TestClient(app)

# 2026-11-02(月)〜11-04(水)。11-04が水曜(weekday=2)。
MASTERS = {
    "persons": [{"id": f"p{i}", "name": f"P{i}"} for i in (1, 2, 3)],
    "positions": [{"id": "pos_hall", "name": "ホール"}],
    "roles": [], "skills": [],
}
FRAME = {
    "period": {"start": "2026-11-02", "end": "2026-11-04"},
    "operating_window": {"open": "11:00", "close": "12:00", "slot_minutes": 60},
    "policy_mode": "balance",
}
FORBID_WED = {"operation": "forbid", "who": "person", "person_id": "p1",
              "when": "weekday", "weekday": 2, "band": "all_day"}


@pytest.fixture(autouse=True)
def _clean():
    for fn in (storage._pending_queue.clear, storage.clear_dynamic_constraints,
               storage.clear_availability, storage.clear_policy_constraints,
               handlers_mod._DYNAMIC_HANDLERS.clear):
        fn()
    storage.save_base_headcounts([])
    yield
    storage._pending_queue.clear()
    storage.clear_dynamic_constraints()
    handlers_mod._DYNAMIC_HANDLERS.clear()


def _setup():
    assert client.post("/setup/masters", json=MASTERS).status_code == 200
    assert client.post("/setup/frame", json=FRAME).status_code == 200
    desired = [{"person_id": p, "date": d, "start": "11:00", "end": "12:00"}
               for p in ("p1", "p2", "p3")
               for d in ("2026-11-02", "2026-11-03", "2026-11-04")]
    assert client.post("/setup/desired-shifts", json=desired).status_code == 200
    hc = [{"slot_label": "L", "time_start": "11:00", "time_end": "12:00",
           "position_id": "pos_hall", "count": 1}]
    assert client.post("/setup/headcounts", json=hc).status_code == 200


# ── engine 統合 ──────────────────────────────────────────────────────

def test_engine_applies_recipe_dynamic_constraint():
    _setup()
    storage.save_dynamic_constraints([{
        "type": "recurring_day_off", "params": FORBID_WED,
        "source": {"person_id": "p1", "date": "2026-11-04", "source_text": "毎週水曜NG"},
    }])
    out = client.post("/solver/run-stored").json()

    wed = [a for a in out["assignments"] if a["person_id"] == "p1" and a["date"] == "2026-11-04"]
    assert wed == []
    assert not any(w["type"].startswith("handler_error") for w in out["warnings"])


# ── validate_recipe ─────────────────────────────────────────────────

def test_validate_recipe_ok():
    ok, _ = validate_recipe(FORBID_WED)
    assert ok


def test_validate_recipe_bad_format():
    ok, msg = validate_recipe({"operation": "nonsense"})
    assert not ok and "形式" in msg


def test_validate_recipe_generates_nothing():
    # 居ない人を対象 → 制約が1つも生まれない＝不合格
    ok, _ = validate_recipe({**FORBID_WED, "person_id": "ZZZ"})
    assert not ok


# ── _fill_recipes_and_store ─────────────────────────────────────────

def test_fill_recipes_overrides_person_id(monkeypatch):
    from src.api.routes_admin import _fill_recipes_and_store

    def fake_convert(self, type_name, param_schema_json, example_params_json, occurrences):
        return [ParamItem(index=o["index"],
                          params_json=json.dumps({**FORBID_WED, "person_id": "GARBAGE"}))
                for o in occurrences]

    monkeypatch.setattr(ParamsAgent, "convert", fake_convert)
    req = PendingTypeRequest(
        id="r", suggested_type_name="recurring_day_off", source_texts=["x"],
        occurrences=[{"person_id": "p1", "date": "2026-11-04", "source_text": "毎週水曜NG", "origin": "note"}],
        suggested_recipe={"operation": "forbid", "who": "person", "when": "weekday", "band": "all_day"},
        tested_params=FORBID_WED, created_at=datetime.now(),
    )
    n = _fill_recipes_and_store(req)

    assert n == 1
    saved = storage.get_dynamic_constraints()
    assert saved[0]["params"]["operation"] == "forbid"
    assert saved[0]["params"]["person_id"] == "p1"   # occurrenceの確かな値で上書き


# ── /generate（RecipeAgentモック） ──────────────────────────────────

def test_generate_endpoint_uses_recipe(monkeypatch):
    monkeypatch.setattr(llm, "is_available", lambda: True)

    def fake_generate(self, req):
        return GeneratedRecipe(
            recipe_template_json=json.dumps({"operation": "forbid", "who": "person",
                                             "when": "weekday", "band": "all_day"}),
            example_recipe_json=json.dumps(FORBID_WED),
            fill_fields=["person_id", "weekday"],
            explanation="毎週その曜日は終日不可", confidence=0.9, concerns=[],
        )

    monkeypatch.setattr(RecipeAgent, "generate", fake_generate)
    storage.add_pending_request(PendingTypeRequest(
        id="req_g", suggested_type_name="recurring_day_off",
        source_texts=["毎週水曜NG"], created_at=datetime.now(),
    ))

    r = client.post("/admin/pending-types/req_g/generate")
    assert r.status_code == 200
    assert r.json()["テスト"] == "合格"
    req = storage.get_pending_request("req_g")
    assert req.suggested_recipe["operation"] == "forbid"
    assert req.test_results.passed


# ── 承認→埋め込み→run-stored（真のL2一周・ParamsAgentモック） ───────

def test_approve_recipe_then_wednesday_removed(monkeypatch):
    monkeypatch.setattr(llm, "is_available", lambda: True)

    def fake_convert(self, type_name, param_schema_json, example_params_json, occurrences):
        return [ParamItem(index=o["index"], params_json=json.dumps(FORBID_WED)) for o in occurrences]

    monkeypatch.setattr(ParamsAgent, "convert", fake_convert)
    _setup()
    storage.add_pending_request(PendingTypeRequest(
        id="req_a", suggested_type_name="recurring_day_off", source_texts=["毎週水曜NG"],
        occurrences=[{"person_id": "p1", "date": "2026-11-04", "source_text": "毎週水曜NG", "origin": "note"}],
        suggested_recipe={"operation": "forbid", "who": "person", "when": "weekday", "band": "all_day"},
        tested_params=FORBID_WED, created_at=datetime.now(),
    ))

    ap = client.post("/admin/pending-types/req_a/approve").json()
    assert ap["方式"] == "レシピ"
    assert ap["反映した要望(params)件数"] == 1

    out = client.post("/solver/run-stored").json()
    wed = [a for a in out["assignments"] if a["person_id"] == "p1" and a["date"] == "2026-11-04"]
    assert wed == []
    assert out["shift_status"] == "confirmed"   # pendingが無くなり確定版
