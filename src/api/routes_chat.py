"""
要望チャット系エンドポイント（②本人 / ③店舗 共通のAI相談）

ChatAgent(Flash) が、ユーザーの要望（複数可・日ごとメモ含む）を会話で確認し、
要望ごとに queue/memo/reject に整理する。**queue（新ルール）は管理者の承認キュー(④)へ**送る。

ステートレス設計: 会話履歴は毎リクエストで渡す（サーバーに状態を持たない）。
"""

import json
import logging
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Body, HTTPException

from src import llm
from src.models import PendingTypeRequest
from src.storage import (
    add_manager_question,
    add_pending_request,
    find_pending_by_type,
    get_manager_question,
    list_manager_questions,
    save_dynamic_constraints,
    update_pending_request,
)

router = APIRouter(prefix="/chat", tags=["提出者チャット"])

logger = logging.getLogger("uvicorn.error")


def _chat_recipe(rule: dict):
    """チャットが確定したレシピ(recipe_json)を (テンプレ, 検証用) に分けて返す。

    ②で聞き取ったパラメータ入りの完成レシピを④へ渡すことで、④での再質問をなくす。
    検証用は person_id="p1"（検証シナリオの人）で当てる。無ければ (None, None)。
    """
    rj = (rule.get("recipe_json") or "").strip()
    if not rj:
        return None, None
    try:
        v = json.loads(rj)
    except (json.JSONDecodeError, TypeError):
        return None, None
    if not isinstance(v, dict) or "operation" not in v:
        return None, None
    template = {k: val for k, val in v.items() if k != "person_id"}
    tested = dict(v)
    if tested.get("who", "person") == "person":
        tested["person_id"] = "p1"
    return template, tested


def _register_chat_rules(rules: list[dict], person_id, scope: str) -> int:
    """decision=queue のルールを管理者の承認キュー(④)へ登録する（同type名はクラスタリング）。"""
    origin = "policy" if scope == "store" else "submit"
    scope_label = "店舗全体" if scope == "store" else "本人"
    registered = 0
    for r in rules:
        if r.get("decision") != "queue":
            continue
        tname = (r.get("suggested_type_name") or "").strip() or "unknown"
        src = (r.get("source_text") or r.get("summary") or "").strip()
        occurrence = {"person_id": person_id, "date": None, "source_text": src, "origin": origin}
        display = f"（{scope_label}の要望）{r.get('summary') or src}"
        template, tested = _chat_recipe(r)  # ②で確定したレシピ（あれば④でそのまま検証）

        existing = find_pending_by_type(tname) if tname != "unknown" else None
        if existing is not None:
            if occurrence in existing.occurrences:
                continue  # 再送による重複は登録しない
            existing.source_texts.append(display)
            existing.occurrence_count += 1
            existing.occurrences.append(occurrence)
            if not existing.summary and r.get("summary"):
                existing.summary = r["summary"]
            if existing.suggested_recipe is None and template:
                existing.suggested_recipe = template
                existing.tested_params = tested
            update_pending_request(existing)
        else:
            add_pending_request(PendingTypeRequest(
                id=f"req_{uuid4().hex[:8]}",
                suggested_type_name=tname,
                source_texts=[display],
                occurrence_count=1,
                occurrences=[occurrence],
                summary=r.get("summary"),
                ai_assessment="チャットの要望整理から検出（管理者が承認するとシフトに反映）",
                suggested_recipe=template,
                tested_params=tested,
                confidence=0.0,
                created_at=datetime.now(),
            ))
        registered += 1
    return registered


def _register_manager_questions(rules: list[dict], person_id) -> int:
    """decision=ask_manager の要望を「責任者への質問」として保留する（需要依存などを即拒否しない）。"""
    n = 0
    for r in rules:
        if r.get("decision") != "ask_manager":
            continue
        recipe = None
        rj = (r.get("recipe_json") or "").strip()
        if rj:
            try:
                v = json.loads(rj)
                if isinstance(v, dict) and "operation" in v:
                    if v.get("who", "person") == "person" and person_id:
                        v["person_id"] = person_id  # 「はい」のとき本人に当てる
                    recipe = v
            except (json.JSONDecodeError, TypeError):
                recipe = None
        add_manager_question({
            "id": f"q_{uuid4().hex[:8]}",
            "person_id": person_id,
            "question": (r.get("question") or r.get("summary") or "確認をお願いします").strip(),
            "summary": r.get("summary"),
            "recipe": recipe,
            "status": "open",
            "answer": None,
        })
        n += 1
    return n


_clarify_examples = {
    "① 曖昧な要望（聞き返し）": {"value": {"requirements": "早番希望です", "scope": "person", "history": []}},
    "② 複数の要望をまとめて": {
        "value": {
            "requirements": "毎週水曜は塾で入れません。前日が遅番なら翌日は休みたい。人が足りなければ入ります。",
            "scope": "person", "person_id": "p01", "history": [],
        },
    },
    "③ 店舗の要望": {"value": {"requirements": "新人だけの時間帯は作らないで。朝の人数を増やしたい。", "scope": "store", "history": []}},
}


@router.post(
    "/clarify-note",
    summary="要望を会話で確認し、要望ごとに整理する（②本人/③店舗 共通・Flash）",
    description=(
        "ユーザーの要望（複数可）を ChatAgent(Flash) に渡し、次の返答を返します。\n\n"
        "- 曖昧なら **1つだけ短く質問**（`needs_clarification: true`）\n"
        "- はっきりしたら **要望ごとに rules[]**（decision = queue/memo/reject）\n"
        "- **queue（新ルール）は自動で管理者の承認キュー(④)へ登録**されます（即適用しない）\n\n"
        "body: `{requirements, scope:\"person\"|\"store\", person_id?, history}`。"
        "会話履歴は毎回まるごと渡してください（サーバーは状態を持ちません）。"
    ),
)
def clarify_note(body: dict = Body(openapi_examples=_clarify_examples)):
    requirements = ((body or {}).get("requirements") or (body or {}).get("note") or "").strip()
    scope = (body or {}).get("scope") or "person"
    person_id = (body or {}).get("person_id")
    history = (body or {}).get("history") or []

    if not requirements:
        raise HTTPException(status_code=422, detail="requirements（要望）が必要です。")
    if not llm.is_available():
        raise HTTPException(
            status_code=400,
            detail="Gemini未設定のため会話できません（.env の GEMINI_API_KEY を設定してください）。",
        )

    from src.agents import ChatAgent

    try:
        turn = ChatAgent().respond(requirements, scope, history)
    except Exception as exc:
        logger.exception("要望チャットに失敗")
        raise HTTPException(status_code=502, detail=f"会話に失敗しました: {exc}")

    # ラリー上限: 何度も聞き返して堂々巡りになるのを防ぐ（反映不可なら正直に打ち切る）
    MAX_USER_TURNS = 4
    user_turns = sum(1 for m in history if (m or {}).get("role") == "user") + 1
    if turn.needs_clarification and user_turns >= MAX_USER_TURNS:
        turn.needs_clarification = False
        if not turn.rules:
            _note = ("※ うまく要望を確定できませんでした。今の仕組みでは反映が難しいか、"
                     "情報が足りないようです。言い方を変えるか、管理者にご相談ください。")
            turn.reply = (turn.reply + "\n\n" + _note) if turn.reply else _note

    # 確定したら：queueルール→承認キュー(④) / ask_manager→責任者への質問 として登録
    queued = 0
    asked = 0
    if not turn.needs_clarification and turn.rules:
        rules = [r.model_dump() for r in turn.rules]
        queued = _register_chat_rules(rules, person_id, scope)
        asked = _register_manager_questions(rules, person_id)

    out = turn.model_dump()
    out["queued"] = queued
    out["asked"] = asked
    return out


@router.get(
    "/manager-questions",
    summary="責任者への確認待ちの質問一覧（需要に依存する要望など）",
)
def manager_questions(status: str = "open"):
    return {"questions": list_manager_questions(status)}


@router.post(
    "/manager-questions/{qid}/answer",
    summary="責任者の回答を記録（はい→そのルールをソルバーに反映）",
)
def answer_manager_question(qid: str, body: dict = Body(...)):
    q = get_manager_question(qid)
    if not q:
        raise HTTPException(status_code=404, detail=f"見つかりません: {qid}")
    yes = bool((body or {}).get("yes"))
    q["status"] = "answered"
    q["answer"] = yes
    applied = False
    if yes and q.get("recipe"):
        save_dynamic_constraints([{
            "type": "manager_conditional",
            "params": q["recipe"],
            "source": {"person_id": q.get("person_id"), "origin": "manager"},
        }])
        applied = True
    return {"結果": "回答を記録しました", "applied": applied}
