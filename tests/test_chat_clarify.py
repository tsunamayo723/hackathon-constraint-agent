"""
要望チャット（/chat/clarify-note）のテスト（Gemini不要・ChatAgentはモック）

新スキーマ（複数ルール対応）:
- 曖昧な要望 → 聞き返し（needs_clarification=true・rules空）
- 会話の続き → 確定（rules[] に decision=queue → ④承認キューへ・queued件数）
- 表現できない要望 → reject（reject_category・キューには行かない）
- requirements 未指定 → 422
- Gemini未設定 → 400
"""

import pytest
from fastapi.testclient import TestClient

import src.storage as storage
from src import llm
from src.agents import ChatAgent, ChatTurn
from src.agents.chat_agent import ChatRule
from src.api.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_queue():
    storage.clear_pending_requests()
    yield
    storage.clear_pending_requests()


def test_clarify_asks_followup(monkeypatch):
    monkeypatch.setattr(llm, "is_available", lambda: True)

    def fake_respond(self, requirements, scope="person", history=None):
        return ChatTurn(reply="早番は何時から何時までを指しますか？", needs_clarification=True)

    monkeypatch.setattr(ChatAgent, "respond", fake_respond)

    r = client.post("/chat/clarify-note", json={"requirements": "早番希望です", "history": []})
    assert r.status_code == 200
    body = r.json()
    assert body["needs_clarification"] is True
    assert "早番" in body["reply"]
    assert body["rules"] == []


def test_clarify_resolves_rule_to_queue(monkeypatch):
    monkeypatch.setattr(llm, "is_available", lambda: True)

    def fake_respond(self, requirements, scope="person", history=None):
        assert history  # 会話履歴が渡っていること
        return ChatTurn(
            reply="承知しました。整理します。",
            needs_clarification=False,
            rules=[ChatRule(
                source_text="水曜は塾", summary="毎週水曜は終日勤務できない",
                decision="queue", suggested_type_name="recurring_day_off",
            )],
        )

    monkeypatch.setattr(ChatAgent, "respond", fake_respond)

    r = client.post("/chat/clarify-note", json={
        "requirements": "水曜は塾があります", "person_id": "p01",
        "history": [
            {"role": "ai", "text": "水曜は毎週ですか？ 終日入れませんか？"},
            {"role": "user", "text": "毎週です。終日入れません。"},
        ],
    })
    assert r.status_code == 200
    body = r.json()
    assert body["needs_clarification"] is False
    assert len(body["rules"]) == 1
    assert body["rules"][0]["decision"] == "queue"
    assert body["rules"][0]["suggested_type_name"] == "recurring_day_off"
    assert body["queued"] == 1  # queueルールが④承認キューへ登録された
    # 実際にキューに入っている
    assert any(p.suggested_type_name == "recurring_day_off"
               for p in storage.list_pending_requests(status="pending"))


def test_clarify_reject_not_queued(monkeypatch):
    monkeypatch.setattr(llm, "is_available", lambda: True)

    def fake_respond(self, requirements, scope="person", history=None):
        return ChatTurn(
            reply="申し訳ないですが今の仕組みでは反映できません。",
            needs_clarification=False,
            rules=[ChatRule(
                source_text="他に休みたい人がいれば出ます", summary="他者の希望しだい",
                decision="reject", reject_category="negotiation_dependent",
            )],
        )

    monkeypatch.setattr(ChatAgent, "respond", fake_respond)

    r = client.post("/chat/clarify-note", json={"requirements": "他に休みたい人がいれば私は出ます", "history": []})
    assert r.status_code == 200
    body = r.json()
    assert body["rules"][0]["decision"] == "reject"
    assert body["rules"][0]["reject_category"] == "negotiation_dependent"
    assert body["queued"] == 0  # reject はキューに行かない


def test_clarify_requires_input(monkeypatch):
    monkeypatch.setattr(llm, "is_available", lambda: True)
    r = client.post("/chat/clarify-note", json={"requirements": "   ", "history": []})
    assert r.status_code == 422


def test_clarify_needs_llm(monkeypatch):
    monkeypatch.setattr(llm, "is_available", lambda: False)
    r = client.post("/chat/clarify-note", json={"requirements": "早番希望", "history": []})
    assert r.status_code == 400
